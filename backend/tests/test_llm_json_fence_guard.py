"""同一个坑的其余入口：**任何**从模型输出里取 JSON 的地方，都不许被字符串值里的围栏劫持。

背景见 `test_agent_json_parse.py`：Agent 那条链路的症状是"审稿意见被吞掉，只剩一段示例
对白"，根因是"先找围栏、把第一段围栏内容当成 JSON"。同一处写法当时还有 12 个模块，
它们各自的症状是另一副样子，但**病因完全一样**：

- 改章（`chapter_revise._parse_json_obj`）：诊断/分段意见被吞 → 空诊断或改错段；
- 改章剥壳（`_strip_rewrite_wrapper`）：把文中**引用的示例**当成改写稿 → 拿示例替换整章；
- 一致性审计 / 事实精炼 / 地图提取 / 设定整理 / 文风学习 / 声线体检 / 角色工坊 / 本地化：
  JSON 里的内容被换成字符串值里那段示例，界面显示成"模型没给东西"或"解析失败"。

本文件逐个钉住：**字符串值里带围栏时，JSON 里的内容必须完整活着**；取不到 JSON 时的兜底
行为（抛错 / 判失败）保持原样。角色工坊与声线检查走完整调用路径（假 provider）。
"""
from __future__ import annotations

import asyncio
import importlib
import json
import pathlib
import re
from typing import Any, List

import pytest

from app.core import chapter_revise, style_memory
from app.core.consistency_audit import _parse_json as audit_parse_json
from app.core.fact_llm import _parse_llm_json
from app.core.localization_ai import _extract_json, parse_translation_response
from app.core.map_extract_smart import _parse_llm_json as map_parse_llm_json
from app.core.narrative_review import _parse_review_json
from app.core.settings_ingest import _parse_json_obj as ingest_parse_json_obj
from app.core.voice_check import run_voice_check
from app.domain.types import VnProject

#: 角色工坊这两个名字在包 `__init__` 里被重导出成了**同名函数**，所以按模块取，
#: 免得 `monkeypatch.setattr` 落到函数上（AttributeError）。
voice_generate = importlib.import_module("app.core.character_voice.generate")
workshop_chat = importlib.import_module("app.core.character_voice.workshop_chat")

ANALYSIS = "先说结论：公寓段从「戏」退化成了「说明书」，只保留一个主冲突，其余砍成背景。"
SAMPLE = "（她在中岛台边站了很久。你切菜的时候，余光瞥见她伸手，指尖悬在砧板边缘。）"

#: 迁移到 `llm_text.extract_json_object` 的模块（结构性守卫用；相对 `app/`）。
MIGRATED = [
    "core/agent.py",
    "core/agent_loop.py",
    "core/chapter_revise.py",
    "core/consistency_audit.py",
    "core/fact_llm.py",
    "core/localization_ai.py",
    "core/map_extract_smart.py",
    "core/narrative_review.py",
    "core/settings_ingest.py",
    "core/style_memory.py",
    "core/voice_check.py",
    "core/character_voice/generate.py",
    "core/character_voice/workshop_chat.py",
]


def _payload(**extra: Any) -> str:
    """一个合法 JSON，其中 `message` 里**嵌着**一段 ```renpy 示例。"""
    body = {"message": f"{ANALYSIS}\n\n示例改法：\n```renpy\n{SAMPLE}\n```"}
    body.update(extra)
    return json.dumps(body, ensure_ascii=False)


class _FakeProvider:
    def __init__(self, content: str):
        self.content = content

    async def chat_completions(self, **_kwargs: Any) -> Any:
        payload = {"choices": [{"message": {"content": self.content}}], "model": "fake"}
        return type("Resp", (), {"json": lambda self: payload})()


def _cfg() -> Any:
    from app.core.ai import DeepSeekConfig

    return DeepSeekConfig(apiKey="test-key", baseUrl="http://localhost", model="fake")


def _project() -> VnProject:
    return VnProject.model_validate(
        {
            "id": "p1",
            "title": "拟合少女",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [
                {
                    "id": "c1",
                    "defineName": "male_lead",
                    "displayName": "男主",
                    "voice": "惜话",
                    "voiceMind": "## 视角一句话\n他宁可动手也不解释。",
                }
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "blocks": [{"type": "narration", "text": "他把雪菜带回了公寓。"}],
                }
            ],
        }
    )


# ---- 改章 --------------------------------------------------------------------


def test_chapter_revise_parse_keeps_json_content():
    data = chapter_revise._parse_json_obj(_payload(verdict="诊断", segments=[{"id": "s1"}]))
    assert ANALYSIS in data["message"]
    assert data["verdict"] == "诊断"


def test_chapter_revise_parse_still_raises_on_garbage():
    """解不出 JSON 时照旧抛 JSONDecodeError——调用方靠这个异常走兜底诊断。"""
    with pytest.raises(json.JSONDecodeError):
        chapter_revise._parse_json_obj("模型说了句人话，没给 JSON。")


def test_strip_rewrite_wrapper_takes_the_longest_fence():
    """示例在前、改写稿在后时，不能拿示例去替换整章。"""
    rewrite = "（雨停了。她把伞收起来，没看他。）\n" * 20
    raw = f"我先给你一段示例：\n```renpy\n{SAMPLE}\n```\n\n### 改写稿\n```renpy\n{rewrite}\n```"
    out = chapter_revise._strip_rewrite_wrapper(raw)
    assert "她把伞收起来" in out
    assert SAMPLE not in out


# ---- 一致性审计 / 事实 / 地图 / 设定 / 文风 ------------------------------------


def test_consistency_audit_parse_keeps_issues():
    data = audit_parse_json(_payload(issues=[{"category": "plot", "description": "时间对不上"}]))
    assert ANALYSIS in data["message"]
    assert data["issues"][0]["description"] == "时间对不上"


def test_fact_llm_parse_keeps_content():
    data = _parse_llm_json(_payload(items=[{"quote": "雨还在下"}]))
    assert ANALYSIS in data["message"]
    assert data["items"] == [{"quote": "雨还在下"}]


def test_map_extract_parse_keeps_content():
    data = map_parse_llm_json(_payload(places=[{"name": "车站"}]))
    assert ANALYSIS in data["message"]
    assert data["places"] == [{"name": "车站"}]


def test_settings_ingest_parse_keeps_bible_patch():
    data = ingest_parse_json_obj(_payload(bible={"outline": "三幕"}))
    assert ANALYSIS in data["message"]
    assert data["bible"] == {"outline": "三幕"}


def test_style_memory_parse_keeps_guide():
    result = style_memory._parse(
        _payload(guide="短句、白描、忌『仿佛』。", samples=["雨停的时候，站台已经没人了。"])
    )
    assert result.guide == "短句、白描、忌『仿佛』。"
    assert result.samples == ["雨停的时候，站台已经没人了。"]


def test_narrative_review_keeps_verdict_and_revision():
    raw = json.dumps(
        {
            "ok": False,
            "issues": ["公寓段没有冲突"],
            "revised_text": f"重写后的正文在围栏里：\n```renpy\n{SAMPLE}\n```",
            "note": "自检未过",
        },
        ensure_ascii=False,
    )
    result = _parse_review_json(raw)
    assert result.ok is False
    assert result.issues == ["公寓段没有冲突"]
    assert result.note == "自检未过"
    assert "重写后的正文" in result.revisedText


def test_narrative_review_garbage_still_fails_loudly():
    """解析不出来时必须判失败（不得静默放行），这条老行为不能变。"""
    result = _parse_review_json("not json at all {{{")
    assert result.ok is False
    assert result.issues == ["critic_parse_failed"]


# ---- 本地化（值可能是对象或数组）----------------------------------------------


def test_localization_extract_json_keeps_translations():
    raw = json.dumps({"k1": f"译文里带围栏：\n```renpy\n{SAMPLE}\n```"}, ensure_ascii=False)
    data = _extract_json(raw)
    assert isinstance(data, dict)
    assert "译文里带围栏" in data["k1"]


def test_localization_still_accepts_a_row_list():
    raw = f'解释在前：\n{json.dumps([{"key": "k1", "text": "译文"}], ensure_ascii=False)}'
    data = _extract_json(raw)
    assert data == [{"key": "k1", "text": "译文"}]
    assert parse_translation_response(raw, ["k1"]) == {"k1": "译文"}


# ---- 角色工坊 / 声线体检：走完整调用路径 ---------------------------------------


def test_voice_generate_keeps_all_variants(monkeypatch):
    payload = json.dumps(
        {
            "message": f"{ANALYSIS}\n```renpy\n{SAMPLE}\n```",
            "variants": [{"text": "（她把碗放下。）", "label": "克制"}],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(voice_generate, "provider_from_config", lambda _cfg: _FakeProvider(payload))
    parsed, _model = asyncio.run(voice_generate._post_json_with_model(_cfg(), system="s", user="u"))
    assert ANALYSIS in parsed["message"]
    assert parsed["variants"][0]["label"] == "克制"


def test_workshop_chat_reply_is_not_replaced_by_the_sample(monkeypatch):
    payload = json.dumps(
        {
            "reply": f"{ANALYSIS}\n```renpy\n{SAMPLE}\n```",
            "action": "别过头",
            "mood": "试探",
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(workshop_chat, "provider_from_config", lambda _cfg: _FakeProvider(payload))
    out = asyncio.run(
        workshop_chat.workshop_chat(_cfg(), _project(), character_id="c1", message="你倒是说话啊")
    )
    assert ANALYSIS in out["reply"], "角色回复被换成围栏里那段示例了"
    assert out["action"] == "别过头"


def test_voice_check_keeps_summary_and_issues():
    payload = json.dumps(
        {
            "summary": f"{ANALYSIS}\n```renpy\n{SAMPLE}\n```",
            "issues": [{"character": "男主", "severity": "warn", "quote": "你连这个都记？"}],
        },
        ensure_ascii=False,
    )
    report = asyncio.run(
        run_voice_check(_cfg(), _project(), "ch1", provider=_FakeProvider(payload))
    )
    assert ANALYSIS in report.summary
    assert report.issues and report.issues[0].character == "男主"


# ---- 结构性守卫 ---------------------------------------------------------------


def test_migrated_modules_use_the_shared_extractor():
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    missing: List[str] = []
    for rel in MIGRATED:
        src = (root / rel).read_text(encoding="utf-8")
        if "extract_json_object" not in src and "extract_json_value" not in src:
            missing.append(rel)
    assert not missing, "这些模块没有走共享的 JSON 抽取：" + "、".join(missing)


def test_nobody_greps_a_fence_before_parsing_json():
    """不许再出现"先找围栏"的取 JSON 写法。

    `_FENCE_RE.search` 只允许留在纯文本场景（改章剥壳、思维包剥壳取**最长**那一段），
    以及 `llm_text` 自己的注释里。`\".search(\"` 一旦回来，字符串值里的围栏就会重新劫持解析。
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders: List[str] = []
    for path in sorted(root.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        if re.search(r"_CODE_FENCE_RE\.search\(", src):
            offenders.append(f"{path.relative_to(root)}: _CODE_FENCE_RE.search")
        if path.name == "llm_text.py":
            continue
        if re.search(r"_FENCE_RE\.search\(", src):
            offenders.append(f"{path.relative_to(root)}: _FENCE_RE.search")
    assert not offenders, "又出现『先找围栏』的写法：" + "、".join(offenders)
