"""导出后的 .rpy 体检：悬空跳转 / 未转义方括号 / 入口点 / 安全化降级。

为什么值得单独一个测试文件：这些缺陷的共同点是**导出时一声不响、跑到 Ren'Py 里才炸**
（跳转到不存在的 label → 玩家卡死；台词里的 `[重点]` → 被当成变量替换；工程没有
`label start` → 引擎拒绝启动）。导出端点是 PlainTextResponse，除了"下载了"没有任何
反馈，所以"产物有没有问题"过去完全不可测——现在它是一条纯函数。

本文件按仓库惯例两个方向都钉：真阳性（该报的必须报）与假阳性（合法产物必须一条都不报，
否则作者会直接无视整个体检）。
"""

from __future__ import annotations

from app.core.project import normalize_project
from app.core.renpy import export_script_rpy, export_to_renpy
from app.core.rpy_validate import (
    SEVERITY_ERROR,
    first_error,
    has_errors,
    label_names,
    summarize,
    validate_project_rpy,
    validate_script_rpy,
)


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


def _project(blocks, characters=None):
    return normalize_project(
        {
            "id": "p-validate",
            "title": "体检",
            "characters": characters
            if characters is not None
            else [{"id": "lx", "defineName": "lx", "displayName": "林夏"}],
            "chapters": [{"id": "c1", "title": "第一章", "blocks": blocks}],
        }
    )


def _clean_blocks():
    return [
        {"type": "label", "id": "ch1", "name": "ch1"},
        {"type": "scene", "image": "bg_street"},
        {"type": "narration", "text": "雨还在下。"},
        {"type": "dialogue", "characterId": "lx", "text": "往东走。"},
        {"type": "jump", "id": "j1", "target": "ch2"},
        {"type": "label", "id": "ch2", "name": "ch2"},
        {"type": "return"},
    ]


# ------------------------------------------------------------------ 假阳性方向


def test_clean_export_and_demo_export_have_no_findings():
    """合法产物必须**一条结论都没有**。

    假阳性是这类体检的致命伤：作者被误报几次之后就会永久无视它。所以这里拿两个
    探针一起钉——一个最小的正常工程，和仓库自带的示例工程（它有 menu / 跳转 / 演出指令）。
    """
    from app.core import create_demo_project

    assert validate_project_rpy(_project(_clean_blocks())) == []
    assert validate_project_rpy(create_demo_project()) == []


def test_resolvable_targets_are_not_reported():
    """跳转目标存在时不许报悬空（同一条判定的另一面）。"""
    findings = validate_script_rpy(
        "label start:\n    jump ch2\n\nlabel ch2:\n    return\n"
    )
    assert "dangling_target" not in _codes(findings)
    assert findings == []


def test_escaped_bracket_is_not_reported():
    """`[[` 是 Ren'Py 的字面方括号写法，已经转义过的文本不许再报一次。"""
    findings = validate_script_rpy('label start:\n    "[[存档] 保存"\n    return\n')
    assert findings == []


def test_percent_sign_without_a_conversion_is_not_reported():
    """「50%」这种普通文本不许报——`%` 的替换开关默认关闭，而 `%%` 只在开关
    打开时才会被还原，转义它反而会把「50%」变成「50%%」（见 `_escape_renpy_string`）。"""
    assert validate_script_rpy('label start:\n    "胜率 50%，别赌。"\n    return\n') == []


def test_text_tags_are_not_reported_as_unescaped_braces():
    """模型/作者写的合法文本标签（`{b}粗体{/b}`）不能触发任何结论。

    花括号在文本层面分不清"写错的正文"和"合法的文本标签"，所以体检**刻意不查它**
    （导出器那一侧统一转义成 `{{`，由 `test_ruby_render.py` 钉住）。
    """
    assert validate_script_rpy('label start:\n    "{b}雨还在下。{/b}"\n    return\n') == []


def test_ascii_label_and_target_names_are_not_flagged_as_sanitized():
    assert "sanitized_name" not in _codes(
        validate_script_rpy("label start:\n    jump ch2\n\nlabel ch2:\n    return\n")
    )


def test_valid_project_export_gains_no_new_marker_lines():
    """合法工程的产物里不许出现任何 `# [VNSS]` 标记。

    这条钉的是"体检与留痕不得改动合法项目的字节"：新加的标记只该出现在**确实被安全化
    改写/跳过**的地方，否则作者会对着一个本来就没问题的脚本看见一堆噪音。
    """
    assert "[VNSS]" not in export_script_rpy(_project(_clean_blocks()))


# ------------------------------------------------------------------ 真阳性方向


def test_missing_start_is_reported_on_the_body_but_not_on_the_download_text():
    """入口点：`export_to_renpy` 是"剧本正文"（没有入口桥），下载产物必须有。

    这条同时是"单文件下载 vs 整包导出不一致"那个缺陷的文本级守卫：
    两个方向的断言都要在——正文缺 start 要报，下载产物缺 start 才是缺陷。
    """
    project = _project(
        [
            {"type": "label", "id": "ch1", "name": "ch1"},
            {"type": "narration", "text": "雨还在下。"},
            {"type": "return"},
        ]
    )
    body = validate_script_rpy(export_to_renpy(project))
    assert "start_label_missing" in _codes(body)
    assert not has_errors(body)  # 缺入口是 warn：正文导出本身没有"必须拦下"的错

    download = validate_project_rpy(project)
    assert _codes(download) == []
    assert "label start:" in export_script_rpy(project)


def test_dangling_jump_is_reported_with_the_target_name():
    findings = validate_script_rpy(
        "label start:\n    jump ghost_label\n    return\n"
    )
    assert _codes(findings) == ["dangling_target"]
    err = first_error(findings)
    assert err is not None and err.severity == SEVERITY_ERROR
    assert "ghost_label" in err.message
    assert err.line == 2


def test_dangling_call_is_reported_too():
    """`call` 与 `jump` 一样会卡住玩家，不能只查 jump。"""
    assert "dangling_target" in _codes(
        validate_script_rpy("label start:\n    call nowhere\n    return\n")
    )


def test_text_level_and_block_level_dangling_agree():
    """同一份剧本，块级体检与文本体检必须给出同一个"悬空"结论。

    这是"判定只有一份实现"的守卫：两处各写一份判定迟早会分叉
    （一处报了另一处没报 → "体检说没问题、导出却跑不起来"）。
    """
    from app.core.branch_analysis import analyze_branches

    project = _project(
        [
            {"type": "label", "id": "start", "name": "start"},
            {"type": "jump", "id": "j1", "target": "ghost"},
            {"type": "return"},
        ]
    )
    block_level = {d["target"] for d in analyze_branches(project)["danglingJumps"]}
    text_level = {
        f.message.split("「")[1].split("」")[0]
        for f in validate_project_rpy(project)
        if f.code == "dangling_target"
    }
    assert block_level == {"ghost"}
    assert text_level == block_level


def test_unescaped_bracket_in_say_text_is_reported():
    """`[重点]` 在 Ren'Py 里是变量替换：文本被吞掉，或者直接报错。"""
    findings = validate_script_rpy('label start:\n    "她说：[重点]"\n    return\n')
    assert _codes(findings) == ["unescaped_bracket"]
    assert first_error(findings).line == 2


def test_menu_choice_text_is_checked_too():
    """选项文本也是 say 文本（菜单项），同样不能漏。"""
    rpy = 'label start:\n    menu:\n        "[拒绝] 我不去":\n            return\n'
    assert "unescaped_bracket" in _codes(validate_script_rpy(rpy))


def test_percent_substitution_shape_is_info_only():
    """`%(名字)s` 形态只报 info、不算失败：`%` 那套开关的真实值包内读不到，
    只能提示作者确认，不能替他把文本改掉。"""
    findings = validate_script_rpy('label start:\n    "你好 %(name)s"\n    return\n')
    assert _codes(findings) == ["percent_substitution"]
    assert not has_errors(findings)
    assert summarize(findings)["ok"] is True


def test_duplicate_label_is_reported():
    findings = validate_script_rpy(
        "label start:\n    return\n\nlabel start:\n    return\n"
    )
    assert "duplicate_label" in _codes(findings)
    assert has_errors(findings)


def test_sanitized_label_and_target_names_are_reported():
    """中文 label 名会被安全化成 `unnamed`：产物能跑，但跳转网已经不是作者写的那张。"""
    project = _project(
        [
            {"type": "label", "id": "l1", "name": "第二章"},
            {"type": "jump", "id": "j1", "target": "第二章"},
            {"type": "return"},
        ]
    )
    findings = validate_project_rpy(project)
    # label 一条、chapter 里的跳转一条、start 桥补的那条跳转一条
    assert _codes(findings).count("sanitized_name") >= 2
    assert not has_errors(findings)  # 只提示，不拦下载
    # 产物里必须留下原名，否则作者不知道该改哪个 label
    assert "第二章" in export_script_rpy(project)


def test_unknown_character_id_is_surfaced_through_the_exporter_marker():
    """未登记的 characterId 按旁白输出，但必须在产物里留痕，并进体检结论。"""
    project = _project(
        [
            {"type": "label", "id": "start", "name": "start"},
            {"type": "dialogue", "characterId": "ghost", "text": "谁在说话？"},
            {"type": "return"},
        ]
    )
    out = export_script_rpy(project)
    assert 'narrator "谁在说话？"' in out
    assert "ghost" in out  # 标记里带着原始 id，作者才找得到是哪儿写错了
    assert "skipped_by_exporter" in _codes(validate_script_rpy(out))


def test_unknown_character_marker_cannot_smuggle_a_newline_into_code():
    """同一个注入面在台词路径上也必须堵住：characterId 里的换行不能变成代码行。"""
    project = _project(
        [
            {"type": "label", "id": "start", "name": "start"},
            {"type": "dialogue", "characterId": "ghost\n$ os.system('x')", "text": "？"},
            {"type": "return"},
        ]
    )
    out = export_script_rpy(project)
    assert "$ os.system('x')" not in out.splitlines()
    assert "[VNSS] 未找到角色" in out


def test_known_character_produces_no_marker_and_no_finding():
    """假阳性方向：正常角色不能被"未知角色"标记碰上。"""
    out = export_script_rpy(_project(_clean_blocks()))
    assert "[VNSS] 未找到角色" not in out
    assert "skipped_by_exporter" not in _codes(validate_script_rpy(out))


def test_unknown_speaker_in_raw_llm_text_is_reported():
    """LLM 那条路的典型缺陷：说了话但从没 define 过这个人。"""
    findings = validate_script_rpy(
        "label start:\n    linxia \"你好\"\n    return\n"
    )
    assert "unknown_speaker" in _codes(findings)


def test_defined_speaker_is_not_reported():
    findings = validate_script_rpy(
        'define linxia = Character("林夏")\n\nlabel start:\n    linxia "你好"\n    return\n'
    )
    assert "unknown_speaker" not in _codes(findings)


# ------------------------------------------------------------------ 接口形状


def test_summarize_reports_ok_and_counts():
    findings = validate_script_rpy("label start:\n    jump ghost\n    return\n")
    summary = summarize(findings)
    assert summary["ok"] is False
    assert summary["counts"]["error"] == 1
    assert summary["findings"][0]["code"] == "dangling_target"
    assert {"code", "severity", "message", "line"} == set(summary["findings"][0])


def test_label_names_reads_definitions_in_order():
    assert label_names("label start:\n    return\n\nlabel ch2:\n    return\n") == [
        "start",
        "ch2",
    ]
    assert label_names("") == []


def test_validate_script_rpy_accepts_none():
    """调用方（端点/LLM 那条路）可能拿到 None，不能在这里炸。

    空文本唯一说得通的结论就是"没有入口"——别的检查都无从谈起。
    """
    assert _codes(validate_script_rpy(None)) == ["start_label_missing"]


# ------------------------------------------------------- 接口接线（不依赖数据库）


def test_validate_endpoint_is_wired_and_requires_auth():
    """体检端点必须真的挂上去，而且**不是谁都能读**。

    不依赖测试库：未登录请求在鉴权那一步就返回 401，所以"401 而不是 404"同时证明了
    "路由存在"和"要登录"。带凭据的完整往返在 `test_api_export.py`（DB 版）。
    """
    import asyncio

    from httpx import ASGITransport, AsyncClient

    from app.main import app

    spec = app.openapi()
    path = "/api/v1/projects/{project_id}/export/rpy/validate"
    assert path in spec["paths"]
    params = [p.get("name") for p in spec["paths"][path]["get"].get("parameters", [])]
    # 开关必须和下载端点一样能传：否则"体检通过"可能对应的是另一个开关下的产物
    assert "adaptive_reader" in params

    async def _call(url: str):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            return await c.get(url)

    assert asyncio.run(_call("/api/v1/projects/p1/export/rpy/validate")).status_code == 401
    # 反方向：路径真写错了就是 404（证明上面那个 401 不是"什么都返回 401"）
    assert asyncio.run(_call("/api/v1/projects/p1/export/rpy/validateX")).status_code == 404


def test_cli_export_writes_a_script_with_an_entry_point():
    """命令行导出与网页下载必须一致：都是**能启动**的脚本。

    缺陷回顾：单文件导出有三条路（网页下载 / CLI / zip 里的 script.rpy），过去用了
    两个不同的导出函数，于是"有没有 label start"取决于走了哪条路。

    这里不落盘：被测的是"命令用了哪个导出函数"，文件系统只是噪音
    （本机沙箱下连 pytest 的 tmp_path 都建不出来），所以换成两个只会读/写字符串的替身。
    """
    import json
    import types

    from app.cli import export_cmd
    from app.core import create_demo_project

    data = create_demo_project().model_dump(mode="json", by_alias=True)
    data["chapters"][0]["blocks"] = [
        {"type": "label", "id": "ch1", "name": "ch1"},  # 工程自己没有 start
        {"type": "narration", "text": "雨还在下。"},
        {"type": "return"},
    ]
    written: dict[str, str] = {}
    src = types.SimpleNamespace(
        read_text=lambda encoding=None: json.dumps(data, ensure_ascii=False)
    )
    out = types.SimpleNamespace(
        write_text=lambda text, encoding=None: written.setdefault("text", text)
    )

    export_cmd(src, out)  # type: ignore[arg-type]

    text = written["text"]
    assert "label start:" in text
    assert validate_script_rpy(text) == []
