"""删除思维包：**只删思维包，示例库一条不动**。

为什么要这个功能：`voiceMind` 此前只有"写"两条路（`/voice/synthesize` 合成、
`/voice/import-mind` 导入），**没有任何清空方式**。于是作者一旦合成或导入一份不满意的包，
就只能再导入一份覆盖，或者放弃这个角色——而那份包会一直参与写作与审稿
（`format_mind_for_prompt` 会把它塞进提示词，`dialogue_write_policy` 会因为
`hasMindPack` 把策略锁在 `anchored`）。

本文件分两层写，理由与仓库现状一致：

- **行为断言**（到处能跑）：用 `patch_character` + `corpus_stats` + `dialogue_write_policy`
  + `format_mind_for_prompt` 验证"清空之后真的回到没有思维包的状态"，且示例库没被碰；
- **接线守卫**（解析源码，不 import fastapi）：确认路由是 `DELETE .../voice/mind`、
  用的是清空 `voiceMind` 而不是删示例库、且没有思维包时返回 404。
  真正的端到端 API 用例需要 Postgres + fastapi（本机缺这两个依赖，`tests/test_api_*.py`
  同理是环境受限的），所以这里不重复那一层。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.core.character_voice.corpus import (
    corpus_stats,
    dialogue_write_policy,
    format_mind_for_prompt,
    patch_character,
)
from app.domain.types import Character, VnProject, VoiceCorpusLine, VoiceCorpusSample

BACKEND = Path(__file__).resolve().parent.parent
API_SRC = BACKEND / "app" / "api" / "v1" / "character_voice.py"


def _char(*, mind: str, samples: int) -> Character:
    corpus = [
        VoiceCorpusSample(
            id=f"s{i}",
            scenario="misunderstood",
            scenarioLabel="被误解时",
            axis=f"轴{i}",
            lines=[VoiceCorpusLine(speaker="self", text=f"第{i}句。")],
            source="preference",
        )
        for i in range(samples)
    ]
    return Character.model_validate(
        {
            "id": "c1",
            "defineName": "senpai",
            "displayName": "学姐",
            "voiceMind": mind,
            "voiceCorpus": [s.model_dump(mode="json") for s in corpus],
        }
    )


def _project(char: Character) -> VnProject:
    return VnProject.model_validate(
        {
            "id": "p1",
            "title": "雨夜",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [char.model_dump(mode="json")],
        }
    )


# ---- 行为：清空之后真的回到"没有思维包" -------------------------------------


def test_clearing_the_mind_pack_drops_it_from_prompt_and_stats():
    char = _char(mind="# 思维包\n说话短、克制。", samples=1)
    assert format_mind_for_prompt(char).startswith("  【角色思维包】")
    assert corpus_stats(char)["hasMindPack"] is True

    cleared = patch_character(_project(char), "c1", voiceMind="").characters[0]

    assert (cleared.voiceMind or "").strip() == "", "清空后不该还留着内容"
    assert format_mind_for_prompt(cleared) == "", "清空后不该再往提示词里塞思维包"
    assert corpus_stats(cleared)["hasMindPack"] is False


def test_clearing_the_mind_pack_downgrades_the_write_policy():
    """这条是"为什么需要删除键"的核心：只有 1 条样本时，有思维包会把策略锁在
    `anchored`（可代写长对白）；删掉之后应回到 `advise_only`。"""
    char = _char(mind="# 思维包", samples=1)
    assert dialogue_write_policy(char)["mode"] == "anchored"

    cleared = patch_character(_project(char), "c1", voiceMind="").characters[0]
    policy = dialogue_write_policy(cleared)

    assert policy["mode"] == "advise_only", "没有思维包、样本又不足时应劝退代写"
    assert policy["mustSample"] is False


def test_clearing_the_mind_pack_keeps_every_corpus_sample():
    """**最容易搞错的一点**：删思维包不能连示例库一起删（那是作者一条条攒出来的）。"""
    char = _char(mind="# 思维包", samples=3)
    before = [s.model_dump(mode="json") for s in char.voiceCorpus]

    cleared = patch_character(_project(char), "c1", voiceMind="").characters[0]

    assert [s.model_dump(mode="json") for s in cleared.voiceCorpus] == before
    assert corpus_stats(cleared)["sampleCount"] == 3


def test_clearing_only_touches_the_target_character():
    other = _char(mind="# 别人的思维包", samples=1).model_dump(mode="json")
    other["id"] = "c2"
    other["displayName"] = "学妹"
    project = VnProject.model_validate(
        {
            "id": "p1",
            "title": "雨夜",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [_char(mind="# 思维包", samples=1).model_dump(mode="json"), other],
        }
    )

    out = patch_character(project, "c1", voiceMind="")
    by_id = {c.id: c for c in out.characters}

    assert (by_id["c1"].voiceMind or "") == ""
    assert by_id["c2"].voiceMind == "# 别人的思维包"


# ---- 接线守卫：路由与语义（解析源码，不 import fastapi） ---------------------


def _api_source() -> str:
    assert API_SRC.exists(), f"找不到 {API_SRC}"
    return API_SRC.read_text(encoding="utf-8")


def _delete_mind_handler_code() -> str:
    """`DELETE .../voice/mind` 那个 handler 的**可执行代码体**。

    用 AST 取、并丢掉文档字符串：直接在源码里搜 `voiceCorpus` 会命中 handler 的注释
    （注释里正好在解释"示例库 voiceCorpus 不动"），那是"注释里提到"而不是"代码在做"。

    注意 `async def` 在 AST 里是 `ast.AsyncFunctionDef`——只匹配 `FunctionDef` 会一个
    handler 都找不到（本文件里的端点全是 async），这是第一次写这条守卫时踩的坑。
    """
    src = _api_source()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            seg = ast.get_source_segment(src, dec) or ""
            if "voice/mind" in seg:
                body = [
                    n
                    for n in node.body
                    if not (
                        isinstance(n, ast.Expr)
                        and isinstance(n.value, ast.Constant)
                        and isinstance(n.value.value, str)
                    )
                ]
                return "\n".join(ast.get_source_segment(src, n) or "" for n in body)
    raise AssertionError("没找到 DELETE .../voice/mind 的 handler")


def test_delete_mind_route_exists_and_is_a_delete():
    src = _api_source()
    m = re.search(
        r'@router\.delete\(\s*"(?P<path>[^"]*voice/mind)"\s*\)\s*\n'
        r"async def (?P<fn>\w+)",
        src,
    )
    assert m, "没找到 DELETE .../voice/mind 路由（前端 deleteCharacterVoiceMind 会打空）"
    assert m.group("path").endswith("/voice/mind")


def test_delete_mind_route_clears_the_mind_and_not_the_corpus():
    """守卫的是"删的是思维包、不是示例库"——这是本功能唯一容易写错的地方。"""
    code = _delete_mind_handler_code()
    assert "voiceMind=" in code, "handler 里没有设置 voiceMind"
    assert '""' in code, "handler 没有把 voiceMind 清空（应赋空串）"
    assert "voiceCorpus" not in code, "删除思维包不该动 voiceCorpus"


def test_delete_mind_route_404s_when_there_is_nothing_to_delete():
    """没有思维包时不能静默成功——那会让界面以为删掉了。"""
    code = _delete_mind_handler_code()
    assert "404" in code and "还没有思维包" in code
