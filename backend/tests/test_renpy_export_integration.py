"""Export full-project integration: multi-chapter + menu + jump must yield a
structurally sound .rpy bundle (no duplicate defines, every label present,
indentation correct for Ren'Py)."""

from app.core.renpy import (
    export_character_defines,
    export_project_bundle,
    export_script_rpy,
    export_to_renpy,
)
from app.domain.types import Character, VnProject


def _characters():
    return [
        Character(id="lx", defineName="lx", displayName="林夏", color="#e8b64c"),
        Character(id="zy", defineName="zy", displayName="周屿", color="#7cc4ff"),
    ]


def _two_chapter_project():
    """Chapter 1 has a label + menu jumping to chapter 2's label; chapter 2 returns."""
    return VnProject.model_validate(
        {
            "id": "p",
            "title": "雨夜站台",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "logline": "末班车前的重逢。",
            "genre": "悬疑",
            "characters": [
                {"id": "lx", "defineName": "lx", "displayName": "林夏", "color": "#e8b64c"},
                {"id": "zy", "defineName": "zy", "displayName": "周屿", "color": "#7cc4ff"},
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "天桥",
                    "synopsis": "过桥，便利店。",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {"type": "scene", "image": "bg_street"},
                        {"type": "narration", "text": "雨还在下。"},
                        {
                            "type": "dialogue",
                            "characterId": "zy",
                            "text": "往东走就是那家便利店。",
                        },
                        {
                            "type": "menu",
                            "id": "m1",
                            "prompt": "你怎么知道？",
                            "choices": [
                                {
                                    "text": "跟着他走",
                                    "blocks": [
                                        {
                                            "type": "dialogue",
                                            "characterId": "lx",
                                            "text": "好。",
                                        }
                                    ],
                                },
                                {"text": "问他为何熟悉", "jump": "ch2"},
                            ],
                        },
                        {"type": "return"},
                    ],
                },
                {
                    "id": "ch2",
                    "title": "便利店",
                    "blocks": [
                        {"type": "label", "id": "ch2", "name": "ch2"},
                        {"type": "scene", "image": "bg_shop"},
                        {
                            "type": "dialogue",
                            "characterId": "zy",
                            "text": "她以前常来。",
                        },
                        {"type": "return"},
                    ],
                },
            ],
        }
    )


def test_export_defines_once():
    vn = _two_chapter_project()
    defines = export_character_defines(vn)
    # exactly one define per character, at top level (not inside a label)
    assert defines.count("define lx") == 1
    assert defines.count("define zy") == 1
    assert "    define" not in defines  # no indented (in-label) define


def test_export_all_labels_present():
    vn = _two_chapter_project()
    script = export_script_rpy(vn)
    # every chapter label survives, plus the injected start bridge
    assert "label start:" in script
    assert "label ch2:" in script
    # start bridges to the first real chapter label (not start itself → no self loop)
    assert "jump ch2" in script or "jump start" not in script.split("label start:")[1][:200]


def test_export_no_self_loop_bridge():
    vn = _two_chapter_project()
    script = export_script_rpy(vn)
    # The auto start bridge must not jump to itself.
    bridge = script.split("label start:")[1].split("\n\n")[0]
    assert "jump start" not in bridge


def test_export_menu_jump_targets_exist():
    vn = _two_chapter_project()
    blob = export_to_renpy(vn)
    labels = {ln.split()[1].rstrip(":") for ln in blob.splitlines() if ln.startswith("label ")}
    # menu jump target ch2 must resolve to a label present in the export
    assert "ch2" in labels
    # every jump references an existing label
    for ln in blob.splitlines():
        if ln.strip().startswith("jump "):
            target = ln.strip().split()[1]
            assert target in labels, f"jump target {target} missing label"


def test_export_bundle_has_all_files():
    vn = _two_chapter_project()
    bundle = export_project_bundle(vn)
    assert set(bundle) == {"script.rpy", "options.rpy", "gui.rpy", "README.txt"}
    assert "label start:" in bundle["script.rpy"]
    # gui accent color is a valid hex (M-7 safety)
    assert '"#' in bundle["gui.rpy"]


def test_export_rpy_is_parseable_shape():
    """Rough structural sanity: no bare `scene`, no `menu menu`, labels top-level."""
    vn = _two_chapter_project()
    rpy = export_to_renpy(vn)
    for line in rpy.splitlines():
        s = line.strip()
        if s.startswith("scene"):
            parts = s.split()
            # scene must have an image token after 'scene'
            assert len(parts) >= 2, f"bare scene in export: {s}"
        assert "menu menu" not in s


def test_export_chapter_with_own_start_no_duplicate():
    """A chapter whose only label is `start` must not produce two label start:."""
    vn = VnProject.model_validate(
        {
            "id": "p",
            "title": "test",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "characters": [
                {"id": "lx", "defineName": "lx", "displayName": "林夏"}
            ],
            "chapters": [
                {
                    "id": "c1",
                    "title": "一",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {"type": "scene", "image": "bg_a"},
                        {
                            "type": "dialogue",
                            "characterId": "lx",
                            "text": "你好",
                        },
                        {"type": "return"},
                    ],
                }
            ],
        }
    )
    script = export_script_rpy(vn)
    # exactly one `label start:` in the whole file
    assert script.count("label start:") == 1
    # the chapter body itself is present (not swallowed by the empty fallback)
    assert "你好" in script
    # and the placeholder "空项目" must NOT appear
    assert "空项目" not in script


# ------------------------------------------------------- define / 台词同一个代码名
#
# 缺陷回顾：define 走 `_safe_ident(defineName, "character")`，台词却直接用
# `ch.defineName`。defineName 是中文时，`define character = Character("林夏")`
# 与 `林夏 "台词"` 同时出现——脚本能导出，一跑就 NameError。
# 所以这里钉的不是"某个函数返回值"，而是**两处必须落在同一个名字上**。


def _non_ascii_character_project():
    return VnProject.model_validate(
        {
            "id": "p-cjk",
            "title": "中文角色名",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "characters": [
                {
                    "id": "char-1a2b-3c",
                    "defineName": "林夏",
                    "displayName": "林夏",
                    "color": "#e8b64c",
                }
            ],
            "chapters": [
                {
                    "id": "c1",
                    "title": "一",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {
                            "type": "dialogue",
                            "characterId": "char-1a2b-3c",
                            "text": "雨还在下。",
                        },
                        {"type": "return"},
                    ],
                }
            ],
        }
    )


def test_define_and_dialogue_use_the_same_sanitized_name():
    """非 ASCII 的 defineName：define 与台词必须落到同一个（可用的）代码名上。"""
    import re

    from app.core.rpy_validate import validate_script_rpy

    script = export_script_rpy(_non_ascii_character_project())
    defined = re.search(r"^define (\S+) = Character", script, re.M)
    assert defined is not None
    name = defined.group(1)
    # 说话用的是**同一个名字**（这就是这条缺陷的核心断言）
    assert f'{name} "雨还在下。"' in script
    # 原始中文名绝不能出现在代码位置（Ren'Py 会把它当 Python 标识符求值）
    assert '林夏 "' not in script
    # 而且这个名字能被体检解析到 → 不会报"说话人没有 define"
    assert "unknown_speaker" not in [f.code for f in validate_script_rpy(script)]


def test_two_unusable_define_names_do_not_collapse_onto_one_code_name():
    """两个都用不了 defineName 的角色不能共用同一个兜底名——那等于第二个覆盖第一个。"""
    import re

    vn = _non_ascii_character_project()
    data = vn.model_dump(mode="json", by_alias=True)
    data["characters"] = [
        {"id": "char-1a2b-3c", "defineName": "林夏", "displayName": "林夏"},
        {"id": "char-4d5e-6f", "defineName": "周屿", "displayName": "周屿"},
    ]
    data["chapters"][0]["blocks"] = [
        {"type": "label", "id": "start", "name": "start"},
        {"type": "dialogue", "characterId": "char-1a2b-3c", "text": "甲"},
        {"type": "dialogue", "characterId": "char-4d5e-6f", "text": "乙"},
        {"type": "return"},
    ]
    script = export_script_rpy(VnProject.model_validate(data))
    names = re.findall(r"^define (\S+) = Character", script, re.M)
    assert len(names) == 2 and names[0] != names[1]
    assert f'{names[0]} "甲"' in script
    assert f'{names[1]} "乙"' in script


def test_character_ident_prefers_define_name_then_id():
    """代码名派生规则本身：能用 defineName 就用它，否则用 id 收敛出的合法标识符。"""
    from app.core.renpy import character_ident

    assert character_ident(
        Character(id="char-1a2b-3c", defineName="lx", displayName="林夏")
    ) == "lx"
    # id 里的 `-` 不是合法 Python 名，必须收敛
    assert character_ident(
        Character(id="char-1a2b-3c", defineName="林夏", displayName="林夏")
    ) == "char_1a2b_3c"
    # 连 id 都没有时才是固定兜底
    assert character_ident(Character(id="", defineName="", displayName="某")) == "character"


def test_sanitized_name_note_cannot_smuggle_a_newline_into_code():
    """注释里回显作者原文时**换行必须被压平**：`a\\njump evil` 不能凭空多出一行代码。

    这是"给作者留痕"这个动作引入的新注入面，所以配一条专门的守卫。
    """
    vn = VnProject.model_validate(
        {
            "id": "p-inject",
            "title": "注入",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "characters": [],
            "chapters": [
                {
                    "id": "c1",
                    "title": "一",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {"type": "jump", "id": "j1", "target": "a\njump evil"},
                        {"type": "return"},
                    ],
                }
            ],
        }
    )
    script = export_script_rpy(vn)
    assert not any(ln.strip() == "jump evil" for ln in script.splitlines())
    # 但作者仍然看得到原名与被改写的事实
    assert "[VNSS]" in script and "已改写为 unnamed" in script


# ------------------------------------------------------- 下载端点（不依赖数据库）
#
# 为什么直接调处理函数：这条缺陷的形态是"两个导出路径用了不同的函数"，而本机可能
# 没有测试库（DB 版用例会整体 skip，"跳过"等于没测到）。直接调处理函数能把
# "端点到底用哪个导出函数"钉住，且不需要任何 DB。


class _FakeRow:
    def __init__(self, project: VnProject) -> None:
        import datetime as _dt

        self.data = project.model_dump(mode="json", by_alias=True)
        self.id = project.id
        self.title = project.title
        self.logline = project.logline
        self.genre = project.genre
        self.updated_at = _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)


def _patch_readable(monkeypatch, project: VnProject):
    from app.api.v1 import projects as projects_api

    async def fake_readable(_db, _user, _project_id):
        return _FakeRow(project)

    monkeypatch.setattr(projects_api, "get_project_readable", fake_readable)
    return projects_api


def test_download_endpoint_returns_the_same_bytes_as_the_bundle_script(monkeypatch):
    """`GET /export/rpy` 的产物必须**逐字**等于 zip 里的 script.rpy。

    缺陷回顾：端点调的是 `export_to_renpy`（不含 `label start` 桥），于是单文件下载
    可能是 Ren'Py 拒绝启动的脚本，而整包导出是好的。
    """
    import asyncio

    project = _project_without_a_start_label()
    api = _patch_readable(monkeypatch, project)
    response = asyncio.run(api.export_rpy("p", False, user=None, db=None))
    text = response.body.decode("utf-8")
    assert text == export_project_bundle(project)["script.rpy"]
    assert "label start:" in text


def test_validate_endpoint_reports_findings_for_the_same_text(monkeypatch):
    """体检端点报的必须是**下载产物**的问题（同源：同一个导出函数）。"""
    import asyncio

    project = _project_without_a_start_label()
    api = _patch_readable(monkeypatch, project)
    body = asyncio.run(api.validate_rpy("p", False, user=None, db=None))
    assert body["ok"] is True
    assert body["findings"] == []

    broken = VnProject.model_validate(
        {
            **project.model_dump(mode="json", by_alias=True),
            "chapters": [
                {
                    "id": "c1",
                    "title": "一",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {"type": "jump", "id": "j1", "target": "ghost"},
                        {"type": "return"},
                    ],
                }
            ],
        }
    )
    api = _patch_readable(monkeypatch, broken)
    body = asyncio.run(api.validate_rpy("p", False, user=None, db=None))
    assert body["ok"] is False
    assert body["findings"][0]["code"] == "dangling_target"


def _project_without_a_start_label() -> VnProject:
    """有 label 但没有 `start`：入口桥必须由下载路径补上。"""
    return VnProject.model_validate(
        {
            "id": "p-nostart",
            "title": "没有 start 的工程",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "characters": [
                {"id": "lx", "defineName": "lx", "displayName": "林夏"}
            ],
            "chapters": [
                {
                    "id": "c1",
                    "title": "一",
                    "blocks": [
                        {"type": "label", "id": "ch1", "name": "ch1"},
                        {"type": "narration", "text": "雨还在下。"},
                        {"type": "return"},
                    ],
                }
            ],
        }
    )
