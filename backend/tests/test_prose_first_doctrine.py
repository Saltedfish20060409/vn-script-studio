"""先把自然语言剧本写好，再谈 RPY——写作面与转换面不许再混成一份提示词。

作者的原话（2026-09-30）："写视觉小说的时候也得先把自然语言剧本写好再考虑怎么转换成
RPY 语言，没有自然语言剧本不用考虑 RPY 语言脚本的事。"

改之前这条口径是**反着写的、而且散在四处**：`AGENT_SYSTEM` 说"正文优先 Ren'Py 可粘贴
风格"、写作通道说"Ren'Py 风格优先"、工艺 Skills 里有"默认 Ren'Py 友好"、导师模板说
"优先 Ren'Py 可粘贴"。四处一起把"写戏"和"照顾语法"压成一件事——模型一边写剧情一边数
label/jump，先被牺牲的必然是戏；作者改稿也得先读懂引擎语法才能改一句台词。

所以本文件钉四件事：

1. 口径**真的进了**三处关键提示词（驻场责编 system / 写作通道 writer 角色 / 任务硬规则 + 输出契约）；
2. 旧的反向文案**真的删了**（按黑名单扫源码，谁把它加回来就红）；
3. 硬规则是头尾各一次（长上下文里末尾那次才是"当场生效"的位置）；
4. 转换面**没有被砍掉**：作者明确要 rpy 时仍然产出引擎语法，导出/生成脚本那条路还在。
"""

from __future__ import annotations

from pathlib import Path

from app.core.agent import AGENT_SYSTEM
from app.core.agent_context import (
    build_agent_context,
    output_contract,
    task_key_rules_for,
)
from app.core.genre_write import GENRE_OUTPUT_CONTRACT, GENRE_TASK_RULES
from app.core.project import normalize_project
from app.core.writing_craft import SKILLS, build_writing_craft_prompt

BACKEND_APP = Path(__file__).resolve().parent.parent / "app"

#: 旧的反向文案：写的时候不该再出现这些"默认落 Ren'Py"的说法。
#: 扫描范围只限**提示词来源**（core 的 .py 与 .md），不含转换/导出那几条链路。
#: 只收"正面要求"的说法——"不要输出 Ren'Py menu 语法"这类**否定**写法是合规的，不在此列。
FORBIDDEN_IN_PROMPTS = (
    "输出纯 Ren'Py",
    "Ren'Py 风格优先",
    "Ren'Py 可粘贴",
    "默认贴近 Ren'Py",
    "默认 Ren'Py 友好",
    "Ren'Py menu 形态",
)

#: 允许保留 RPY 字样/旧说法的地方：
#: - **转换面**（把剧本转成引擎脚本、校验、导出）与解析工具；
#: - `writing_surface.py` 自己：它的说明里必须能指名那几处旧文案，否则后人读不懂为什么改。
CONVERSION_FILES = {
    "writing_surface.py",
    "renpy.py",
    "prose_rpy.py",
    "rpy_validate.py",
    "ruby_render.py",
    "adaptive_reader.py",
    "conditions.py",
    "branch_analysis.py",
    "import_text.py",
    "file_text.py",
    "localization.py",
    "localization_ai.py",
    "novel_craft.py",
    "usage_kinds.py",
    "analytics.py",
    "continuity_graph.py",
    "asset_audit.py",
    "map_extract_smart.py",
    "chapter_revise.py",
    "adaptation_checklist.py",
    "llm_text.py",
    "agent_loop.py",
    "voice_check.py",
    "style_memory.py",
    "candidates.py",
    "gate.py",
}


def _vn_project():
    return normalize_project(
        {
            "id": "p-surface",
            "title": "写作面",
            "genre": "视觉小说",
            "writingGenre": "vn",
            "bible": {"world": "雨城。"},
            "characters": [{"id": "c1", "displayName": "雪菜", "defineName": "yukina"}],
            "chapters": [
                {"id": "ch1", "title": "第一章", "prose": "她坐在沙发上。" * 12},
            ],
        }
    )


# ---- 1. 三处提示词都带上了 ------------------------------------------------


def test_reviewer_system_carries_the_doctrine():
    assert "写作面与转换面分开" in AGENT_SYSTEM
    assert "没有自然语言剧本之前，不要考虑 RPY" in AGENT_SYSTEM
    assert "根据剧本生成" in AGENT_SYSTEM
    assert "不是生成 .rpy 的入口" in AGENT_SYSTEM
    # 也要写清"什么时候才可以落引擎语法"，否则模型会把整条路当成禁止
    assert "作者" in AGENT_SYSTEM and "rpy" in AGENT_SYSTEM.replace("RPY", "rpy")


def test_writer_channel_role_carries_the_doctrine():
    from app.core.harness.roles import build_role_system

    system = build_role_system("writer", extra="作品上下文（节选）：…")
    assert "自然语言剧本" in system
    assert "没有自然语言剧本就不要碰 RPY" in system
    assert "根据剧本生成" in system
    # 旧的输出约定已经删掉
    assert "可粘贴的 Ren'Py 风格片段" not in system


def test_task_rules_and_contract_say_it_in_one_line():
    project = _vn_project()
    for task in ("continue", "scene", "branch"):
        rules = task_key_rules_for(task, project)
        assert any("只写自然语言剧本" in r for r in rules), task
        # 硬规则说"留到转换"，契约说"不要引擎语法"——两处至少一处把禁止项点明，
        # 否则模型只知道"有个转换步骤"，不知道 label/menu 现在不该写。
        joined = " ".join(rules) + output_contract(task, project)
        assert "引擎语法" in joined or "menu" in joined, (task, joined)


def test_hard_rule_appears_at_both_ends_of_the_context():
    """头尾各一次是这套提示词的老规矩：末尾那次才是"当场生效"的位置。"""
    ctx = build_agent_context(
        _vn_project(), chapterId="ch1", userMessage="接着写", task="continue"
    )
    assert ctx.text.count("只写自然语言剧本") >= 2, ctx.text.count("只写自然语言剧本")
    assert "只写自然语言剧本" in ctx.text[:1500]
    assert "只写自然语言剧本" in ctx.text[-1500:]


def test_craft_skill_is_about_the_script_form_not_engine_syntax():
    assert "script_form" in SKILLS
    assert "renpy_hygiene" not in SKILLS, "写作面的技能不该再叫「Ren'Py 脚本卫生」"
    body = SKILLS["script_form"].body
    assert "自然语言剧本" in body
    assert "menu / label / jump" in body
    # ln_vn_bridge 那条也不再教人"默认贴近 Ren'Py"
    assert "默认贴近 Ren'Py" not in SKILLS["ln_vn_bridge"].body
    assert "自然语言剧本" in SKILLS["ln_vn_bridge"].body
    assert "自然语言剧本" in build_writing_craft_prompt("continue", "full")


def test_genre_overrides_for_vn_dont_push_engine_syntax():
    """视觉小说的体裁覆盖不该再要"Ren'Py menu 形态"。

    "不写引擎语法"由通用硬规则（`PROSE_FIRST_RULE`）兜住，体裁差分只管体裁特有的东西——
    两处重复会让末尾硬规则区变长，而那些字数是白花的。
    """
    vn_rules = " ".join(sum(GENRE_TASK_RULES["vn"].values(), []))
    assert "Ren'Py" not in vn_rules, "体裁规则又在推引擎语法了"
    assert "自然语言" in vn_rules, "分支那条要写清选项也用自然语言"
    vn_contracts = " ".join(GENRE_OUTPUT_CONTRACT["vn"].values())
    assert "Ren'Py menu" not in vn_contracts
    assert "自然语言" in vn_contracts
    # 小说体裁那两条是**否定**写法（"不要 Ren'Py 语法"），照旧允许
    novel = " ".join(GENRE_OUTPUT_CONTRACT["novel"].values())
    assert "不要 Ren'Py 语法" in novel


# ---- 2. 旧文案真的删了（守卫） -------------------------------------------


def test_no_prompt_source_still_defaults_to_renpy():
    """谁把"默认落 Ren'Py"加回来就红——这是这次改动的护栏。"""
    offenders: list[str] = []
    for path in sorted(BACKEND_APP.rglob("*")):
        if path.suffix not in (".py", ".md") or path.name in CONVERSION_FILES:
            continue
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for bad in FORBIDDEN_IN_PROMPTS:
            if bad in text:
                offenders.append(f"{path.relative_to(BACKEND_APP)}: {bad}")
    assert not offenders, "这些提示词又在写作面默认落 Ren'Py 了：\n  " + "\n  ".join(offenders)


def test_legacy_ai_prompts_were_updated_too():
    from app.core.ai import ACTION_PROMPTS

    assert "Ren'Py" not in ACTION_PROMPTS["continue"]
    assert "自然语言剧本" in ACTION_PROMPTS["continue"]
    assert "menu/jump/label" in ACTION_PROMPTS["choices"], "选项也要说清别写引擎语法"


# ---- 3. 转换面没被砍掉 ----------------------------------------------------


def test_conversion_side_still_exists():
    """doctrine ≠ 不要 RPY：作者明确要脚本时那条路必须还在。"""
    from app.core.prose_rpy import generate_rpy_from_prose  # noqa: F401
    from app.core.renpy import export_script_rpy  # noqa: F401

    assert "根据剧本生成" in AGENT_SYSTEM
    assert "生成脚本" in build_writing_craft_prompt("continue", "full") or (
        "根据剧本生成" in build_writing_craft_prompt("continue", "full")
    )
