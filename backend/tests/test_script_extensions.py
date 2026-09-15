"""剧本 DSL 扩展：演出指令（音频/等待/镜头/特效）+ 条件分支 + 变量赋值。

这一层是"从脚本到成片"的关键：此前作者只能在 raw 里手写 Ren'Py，试玩也演不出来。
这里钉住三件事：导出成合法 Ren'Py、摘要/Agent 上下文能看到它们、写错条件不会静默变恒真。
"""

from __future__ import annotations

from app.core.chapter_digest import make_chapter_digest
from app.core.project import normalize_project
from app.core.renpy import export_camera_transforms, export_to_renpy


def _project(blocks):  # noqa: ANN001
    return normalize_project(
        {
            "id": "p1",
            "title": "测试剧本",
            "characters": [
                {"id": "yuki", "defineName": "yuki", "displayName": "由纪"},
            ],
            "chapters": [{"id": "ch1", "title": "第一章", "blocks": blocks}],
        }
    )


def _emit(blocks) -> str:  # noqa: ANN001
    return export_to_renpy(_project(blocks))


# ---------------------------------------------------------------- 音频指令


def test_music_play_and_stop_export_with_fade():
    out = _emit(
        [
            {"type": "music", "action": "play", "file": "bgm/rain.ogg", "fade": 2},
            {"type": "music", "action": "stop", "fade": 3},
        ]
    )
    assert 'play music "bgm/rain.ogg" fadein 2' in out
    assert "stop music fadeout 3" in out


def test_sound_and_voice_export():
    out = _emit(
        [
            {"type": "sound", "action": "play", "file": "sfx/door.mp3", "volume": 0.6},
            {"type": "voice", "action": "play", "file": "voice/y01.ogg"},
            {"type": "dialogue", "characterId": "yuki", "text": "你来了。"},
            {"type": "voice", "action": "stop"},
        ]
    )
    assert 'play sound "sfx/door.mp3" volume 0.6' in out
    assert 'voice "voice/y01.ogg"' in out
    assert "stop voice" in out


def test_audio_path_is_sanitized_against_injection():
    out = _emit(
        [{"type": "music", "action": "play", "file": 'x"; os.system("rm -rf /") #'}]
    )
    assert "os.system" not in out
    assert '"audio/missing.ogg"' in out


# ---------------------------------------------------------------- 等待 / 镜头 / 特效


def test_wait_exports_pause_and_clamps_bad_values():
    assert "pause 1.5" in _emit([{"type": "wait", "seconds": 1.5}])
    assert "pause 0.25" in _emit([{"type": "wait", "seconds": 0.25}])
    # 非法值 → 退化成"点击继续"（Ren'Py 的裸 pause），而不是崩掉或注入
    bare = _emit([{"type": "wait", "seconds": "abc"}])
    assert "pause" in bare
    assert "abc" not in bare


def test_camera_generates_transform_definition_and_statement():
    blocks = [
        {"type": "camera", "zoom": 1.2, "x": 30},
        {"type": "camera", "at": "my_cam"},
    ]
    project = _project(blocks)
    transforms = export_camera_transforms(project)
    out = export_to_renpy(project)

    assert "transform vnss_cam_z1_2_x30_y0:" in transforms
    assert "zoom 1.2" in transforms
    assert "xoffset 30" in transforms
    # 具名 transform 优先，不再生成多余定义
    assert "camera at my_cam" in out
    assert "camera at vnss_cam_z1_2_x30_y0" in out
    # transform 定义必须在导出文件里（否则 camera 语句引用不存在的名字）
    assert "transform vnss_cam_z1_2_x30_y0:" in out


def test_effect_kinds_map_to_renpy_transitions():
    assert "with hpunch" in _emit([{"type": "effect", "kind": "shake"}])
    assert "with vpunch" in _emit([{"type": "effect", "kind": "vshake"}])
    assert "with dissolve" in _emit([{"type": "effect", "kind": "dissolve"}])
    flash = _emit([{"type": "effect", "kind": "flash_white", "duration": 0.4}])
    assert 'Fade(0.2, 0.0, 0.2, color="#ffffff")' in flash
    # 未知特效：输出注释而不是猜一个假效果
    unknown = _emit([{"type": "effect", "kind": "sparkle"}])
    assert "[VNSS] 未知特效" in unknown


# ---------------------------------------------------------------- 变量与条件


def test_set_variable_export_is_literal_only():
    out = _emit(
        [
            {"type": "set", "key": "affection", "op": "+=", "value": 1},
            {"type": "set", "key": "flag", "op": "=", "value": True},
            {"type": "set", "key": "who", "op": "=", "value": "由纪"},
        ]
    )
    assert "$ affection += 1" in out
    assert "$ flag = True" in out
    assert '$ who = "由纪"' in out


def test_set_variable_rejects_bad_key_and_value():
    out = _emit([{"type": "set", "key": "os.system", "value": 1}])
    # 变量名必须是纯标识符：`$ os.system = 1` 这种既无意义又危险
    assert "$ os.system" not in out
    assert "[VNSS] 变量名不合法" in out

    # 恶意值只能作为**转义后的字符串字面量**落地（引号被转义 → 逃不出字符串）
    injected = _emit([{"type": "set", "key": "x", "value": '1; os.system("rm -rf /")'}])
    assert '$ x = "1; os.system(\\"rm -rf /\\")"' in injected


def test_if_block_exports_if_elif_else_chain():
    out = _emit(
        [
            {
                "type": "if",
                "branches": [
                    {
                        "condition": "affection >= 3",
                        "blocks": [{"type": "narration", "text": "她笑了。"}],
                    },
                    {
                        "condition": "affection >= 1",
                        "blocks": [{"type": "narration", "text": "她点点头。"}],
                    },
                    {"blocks": [{"type": "narration", "text": "她别过头。"}]},
                ],
            }
        ]
    )
    assert "if affection >= 3:" in out
    assert "elif affection >= 1:" in out
    assert "else:" in out
    assert "她笑了。" in out


def test_menu_choice_condition_exports_inline_if():
    out = _emit(
        [
            {
                "type": "menu",
                "id": "menu",
                "choices": [
                    {"text": "接受她的伞", "condition": "affection >= 2", "jump": "end"},
                    {"text": "谢绝", "jump": "end"},
                ],
            },
            {"type": "label", "id": "end", "name": "end"},
        ]
    )
    assert '"接受她的伞" if affection >= 2:' in out
    assert '"谢绝":' in out


def test_invalid_condition_is_never_silently_true():
    """条件写错时不能当成恒真——那会把分支发错，比报错更糟。"""
    out = _emit(
        [
            {
                "type": "menu",
                "id": "menu",
                "choices": [{"text": "只有在好感够时才出现", "condition": "affection >=> 3"}],
            },
            {
                "type": "if",
                "branches": [
                    {
                        "condition": "affection >=> 3",
                        "blocks": [{"type": "narration", "text": "A"}],
                    },
                    {"blocks": [{"type": "narration", "text": "B"}]},
                ],
            },
        ]
    )
    assert "[VNSS] 选项条件无法解析，已跳过" in out
    assert "[VNSS] 分支条件无法解析，已跳过" in out
    assert '"只有在好感够时才出现"' not in out
    assert "A" not in out.split("menu:")[1]  # 坏条件的分支内容没有被当成恒真发出去
    # 坏条件分支被跳过后，剩下的无条件分支成为唯一分支 → 必须显式 True，不能凭空生成 elif
    assert "if True:" in out
    assert "B" in out


def test_invalid_middle_branch_keeps_else_chain_valid():
    """坏条件出现在中间时，其余分支仍要组成合法的 if/else。"""
    out = _emit(
        [
            {
                "type": "if",
                "branches": [
                    {"condition": "a >= 1", "blocks": [{"type": "narration", "text": "甲"}]},
                    {"condition": "b >=> 2", "blocks": [{"type": "narration", "text": "乙"}]},
                    {"blocks": [{"type": "narration", "text": "丙"}]},
                ],
            }
        ]
    )
    assert "if a >= 1:" in out
    assert "elif" not in out  # 坏分支没被当成 elif
    assert "else:" in out
    assert "乙" not in out
    assert "丙" in out


# ---------------------------------------------------------------- 摘要 / 上下文可见性


def test_chapter_digest_sees_staging_blocks():
    digest = make_chapter_digest(
        _project(
            [
                {"type": "music", "action": "play", "file": "bgm/rain.ogg"},
                {"type": "narration", "text": "雨还在下。"},
                {"type": "effect", "kind": "shake"},
            ]
        ).chapters[0],
        [],
    )
    assert "音乐 bgm/rain.ogg" in digest.beatSummary
    assert "特效 shake" in digest.beatSummary


def test_agent_plain_text_sees_conditions_and_audio():
    from app.core.agent_context import _blocks_to_plain

    project = _project(
        [
            {"type": "music", "action": "play", "file": "bgm/rain.ogg"},
            {"type": "set", "key": "affection", "op": "+=", "value": 1},
            {
                "type": "if",
                "branches": [
                    {"condition": "affection >= 3", "blocks": [{"type": "narration", "text": "她笑了。"}]},
                ],
            },
        ]
    )
    plain = _blocks_to_plain(project.chapters[0].blocks, project.characters)
    assert "[音乐 bgm/rain.ogg]" in plain
    assert "[变量 affection += 1]" in plain
    assert "affection >= 3" in plain
    assert "她笑了。" in plain


# ---------------------------------------------------------------- 字段透传


def test_normalize_preserves_undeclared_but_model_known_fields():
    """normalize_project 曾经手写枚举字段，导致新字段被静默丢弃（styleMemory 全站 null）。"""
    raw = {
        "id": "p",
        "title": "T",
        "styleMemory": {"guide": "短句为主"},
        "shareId": "share-1",
        "voiceReports": [{"chapterId": "ch1"}],
        "analysisMeta": {"autoRun": True},
    }
    project = normalize_project(raw)
    assert project.styleMemory == {"guide": "短句为主"}
    assert project.shareId == "share-1"
    assert project.voiceReports == [{"chapterId": "ch1"}]
    # 二次归一化不能丢（保存路径上会走很多次）
    again = normalize_project(project)
    assert again.styleMemory == {"guide": "短句为主"}
    assert again.analysisMeta is not None
