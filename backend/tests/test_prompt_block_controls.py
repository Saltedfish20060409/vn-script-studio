"""提示词块的"可调"与"可关"：工艺详述条数、风格清单、导师块开关。

这三条都是 2026-09-28 那次 prompt/skills 审计的直接产物：

- **工艺 Skills 的详述条数**：full 档把 17 条优先级技能全文铺开（约 2.5k 字），
  而一次写作真正用得上的通常只有几条。`detail_max` 让"详述 N 条 + 其余进简表"可配，
  消融臂 `craft_lean`(6) 用它量"精简会不会掉分"——**默认值不动**，先量再改。
- **`style_guide.md` 硬约束块（约 2k 字）**：它此前会因为 `style_skill` 与
  `harness` 的**循环导入**而静默消失（调用方是 `try/except: pass`），提示词看着正常、
  规则没了。这里钉住"先导入 style_skill 也能拿到这段"。
- **写作导师块**：1.6k 字、线上每轮都注入且**关不掉**。现在可以按 `exclude_sections`
  的 `mentor` 键摘掉（走「⚙ 资料」面板同一个开关），并在 promptMeta 里留痕。
"""
from __future__ import annotations

import importlib
import sys
from typing import Any, Dict, List

from app.core.writing_craft import build_writing_craft_prompt, skills_for_task

BLOCK_MARKER = "写作工艺 Skills"
STYLE_MARKER = "写作风格 Skill"


# ---- 工艺详述条数（craft detail_max）-----------------------------------------


def test_default_full_craft_lists_every_priority_skill_in_detail():
    """默认行为不变：优先级技能全部详述（`【技能：…】` 逐条出现）。"""
    text = build_writing_craft_prompt("continue", "full", include_style=False)
    detailed = text.count("【技能：")
    assert detailed >= 10, detailed
    assert "【亦须遵守（简表）】" in text


def test_detail_max_moves_the_extras_into_the_title_list():
    full = build_writing_craft_prompt("continue", "full", include_style=False)
    lean = build_writing_craft_prompt("continue", "full", include_style=False, detail_max=6)

    assert lean.count("【技能：") == 6
    assert len(lean) < len(full), "精简版必须更短，否则等于没省"
    # 被降级的技能不能**消失**：标题要进简表（规则还在，只是不再逐条展开）
    for skill in skills_for_task("continue", "full")[6:]:
        assert skill.title in lean, f"{skill.id} 被整个丢掉了"
    assert "【亦须遵守（简表）】" in lean


def test_detail_max_does_not_touch_off_or_lite_modes():
    """off / lite 两档与详述条数无关：off 是那句占位，lite 本来就只上 8 条。"""
    assert build_writing_craft_prompt("continue", "off", detail_max=6).endswith("——")
    assert "轻量" in build_writing_craft_prompt("continue", "lite", detail_max=6)


# ---- 风格硬约束块：循环导入断掉之后还在吗 --------------------------------------


def test_style_skill_can_be_imported_first_without_cycles():
    """以前先导入 `style_skill` 会 ImportError（它 ←→ `harness` 互相依赖），
    而调用方吞异常 → 2k 字硬约束静默消失。这里在**干净的解释器**里先导入它。
    """
    import subprocess

    code = (
        "import sys; sys.path.insert(0, 'backend');"
        "from app.core.pipeline.style_skill import load_style_skill;"
        "print(len(load_style_skill().prompt_block(max_chars=2000)))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8"
    )
    assert out.returncode == 0, out.stderr[-500:]
    assert int(out.stdout.strip()) > 500, "风格清单块不该是空的"


def test_craft_block_actually_carries_the_style_guide():
    """`build_writing_craft_prompt` 的 try/except 会吞掉导入失败——所以必须正面断言它进了。"""
    text = build_writing_craft_prompt("continue", "full")
    assert STYLE_MARKER in text
    assert "禁用" in text


# ---- 导师块可关（exclude_sections 里的 mentor）--------------------------------


def _run_with_exclusions(monkeypatch, exclusions: List[str]) -> Dict[str, Any]:
    import asyncio

    from app.core.agent_loop import run_agent_loop
    from app.core.ai import DeepSeekConfig
    from app.domain.types import AgentRequest, VnProject

    project = VnProject.model_validate(
        {
            "id": "p1",
            "title": "雨夜",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [
                {"id": "c1", "defineName": "a", "displayName": "甲", "voice": "惜话"}
            ],
            "chapters": [
                {"id": "ch1", "title": "第一章", "blocks": [{"type": "narration", "text": "雨。"}]}
            ],
        }
    )

    async def fake_chat_json(*_a: Any, **_k: Any) -> tuple[str, bool]:
        # 第二个元素是"是否撞到输出上限"（见 agent_loop._chat_json）
        return '{"message":"好。","actions":[],"tool_calls":[],"done":true}', False

    from app.core import agent_loop as al

    monkeypatch.setattr(al, "_chat_json", fake_chat_json)
    checkpoints: List[Dict[str, Any]] = []

    async def on_checkpoint(state: Dict[str, Any]) -> None:
        checkpoints.append(state)

    async def _go():
        return await run_agent_loop(
            DeepSeekConfig(apiKey="test-key", baseUrl="http://x", model="m"),
            AgentRequest(
                project=project,
                messages=[{"role": "user", "content": "续写"}],  # type: ignore[arg-type]
                task="continue",
                excludeSections=exclusions,
            ),
            on_checkpoint=on_checkpoint,
        )

    asyncio.run(_go())
    return checkpoints[-1]["promptMeta"]


def test_mentor_block_can_be_excluded(monkeypatch):
    meta_on = _run_with_exclusions(monkeypatch, [])
    meta_off = _run_with_exclusions(monkeypatch, ["mentor"])

    assert meta_on["blocks"]["mentor"] > 800, "默认该带导师块（线上行为）"
    assert meta_off["blocks"]["mentor"] == 0, "写了 mentor 就该真摘掉"
    assert meta_off["mentorExcluded"] is True
    assert meta_on["mentorExcluded"] is False
    # 摘掉导师块之后整体提示词必须变短（否则说明没真去掉）
    assert meta_off["systemChars"] < meta_on["systemChars"]


def test_unknown_exclusion_key_does_not_break_the_run(monkeypatch):
    """前端版本不一致时可能发来未知 key：忽略即可，不能把整轮打挂。"""
    meta = _run_with_exclusions(monkeypatch, ["不存在的块"])
    assert meta["blocks"]["mentor"] > 0
    assert meta["mentorExcluded"] is False


def test_agent_sections_module_is_importable():
    """模块级导入一遍，确保没有循环导入把 `agent_loop` 拽坏。"""
    for name in ("app.core.agent_loop", "app.core.pipeline.style_skill"):
        assert importlib.import_module(name) is not None
