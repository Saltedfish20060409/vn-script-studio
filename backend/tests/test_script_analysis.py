"""剧本工程分析：分支覆盖 / 结局统计 / 变量使用 / 时长估算 / 重复率。

这些指标直接对应作者最怕的三件事：分支写歪（死 label、悬空跳转、错条件）、
结局漏了（写了但走不到）、体量估不准（时长、重复文本）。
"""

from __future__ import annotations

from app.core.project import normalize_project
from app.core.script_analysis import (
    analyze_script,
    estimate_duration,
    reachable_labels,
    repetition_report,
    variable_usage,
)


def _project(blocks_by_chapter):  # noqa: ANN001
    return normalize_project(
        {
            "id": "p1",
            "title": "T",
            "variables": [
                {"id": "v1", "name": "好感度", "key": "affection", "type": "number", "value": 0},
                {"id": "v2", "name": "没用过", "key": "never_used", "type": "bool", "value": False},
            ],
            "chapters": [
                {"id": f"ch{i + 1}", "title": f"第{i + 1}章", "blocks": b}
                for i, b in enumerate(blocks_by_chapter)
            ],
        }
    )


def test_reachable_labels_follows_jumps_and_choices():
    blocks = [
        {"type": "label", "id": "start", "name": "start"},
        {"type": "narration", "text": "开场"},
        {
            "type": "menu",
            "id": "m1",
            "choices": [
                {"text": "去 A", "jump": "a"},
                {"text": "去 B", "jump": "b"},
            ],
        },
        {"type": "label", "id": "a", "name": "a"},
        {"type": "narration", "text": "A 线"},
        {"type": "jump", "target": "end"},
        {"type": "label", "id": "b", "name": "b"},
        {"type": "narration", "text": "B 线"},
        {"type": "label", "id": "orphan", "name": "orphan"},
        {"type": "narration", "text": "没人能到这里"},
        {"type": "label", "id": "end", "name": "end"},
        {"type": "narration", "text": "结局"},
        {"type": "return"},
    ]
    reach = reachable_labels(_project([blocks]))
    assert "start" in reach
    assert "a" in reach and "b" in reach and "end" in reach
    assert "orphan" not in reach


def test_analyze_reports_unreachable_dangling_and_invalid_conditions():
    blocks = [
        {"type": "label", "id": "start", "name": "start"},
        {"type": "jump", "target": "ghost"},  # 悬空跳转
        {"type": "label", "id": "orphan", "name": "orphan"},
        {
            "type": "menu",
            "id": "m",
            "choices": [
                {"text": "条件写错", "condition": "affection >=> 3", "jump": "start"},
                {"text": "正常", "condition": "affection >= 1", "jump": "start"},
            ],
        },
    ]
    out = analyze_script(_project([blocks]))
    assert out["labels"]["unreachable"] == ["orphan"]
    assert [d["target"] for d in out["danglingJumps"]] == ["ghost"]
    assert len(out["invalidConditions"]) == 1
    assert out["invalidConditions"][0]["text"] == "affection >=> 3"
    assert out["branchPoints"][0]["choices"] == 2
    assert out["branchPoints"][0]["conditional"] == 2


def test_endings_are_listed_with_reachability():
    blocks = [
        {"type": "label", "id": "start", "name": "start"},
        {
            "type": "menu",
            "id": "m",
            "choices": [
                {"text": "好结局", "jump": "good"},
                {"text": "坏结局", "jump": "bad"},
            ],
        },
        {"type": "label", "id": "good", "name": "good"},
        {"type": "narration", "text": "她笑了。"},
        {"type": "return"},
        {"type": "label", "id": "bad", "name": "bad"},
        {"type": "narration", "text": "她走了。"},
        {"type": "return"},
        {"type": "label", "id": "secret", "name": "secret"},
        {"type": "narration", "text": "隐藏结局（没人能到）"},
        {"type": "return"},
    ]
    out = analyze_script(_project([blocks]))
    labels = {e["label"]: e for e in out["endings"]}
    assert labels["good"]["reachable"] is True
    assert labels["bad"]["reachable"] is True
    assert labels["secret"]["reachable"] is False
    assert out["endingsReachable"] == 2


def test_variable_usage_flags_unused_and_undeclared():
    blocks = [
        {"type": "label", "id": "start", "name": "start"},
        {
            "type": "if",
            "branches": [
                {"condition": "affection >= 2", "blocks": [{"type": "narration", "text": "A"}]},
                {"blocks": [{"type": "narration", "text": "B"}]},
            ],
        },
        {"type": "set", "key": "surprise", "op": "+=", "value": 1},
        {"type": "return"},
    ]
    usage = variable_usage(_project([blocks]))
    assert "affection" in usage["used"]
    assert usage["unused"] == ["never_used"]
    assert usage["undeclared"] == ["surprise"]


def test_duration_estimate_counts_text_and_waits():
    blocks = [
        {"type": "label", "id": "start", "name": "start"},
        {"type": "narration", "text": "字" * 240},
        {"type": "wait", "seconds": 6},
        {"type": "dialogue", "characterId": "c", "text": "字" * 160},
    ]
    d = estimate_duration(_project([blocks]))
    assert d["chars"] == 400
    assert d["readSeconds"] == 100  # 400 / 4
    assert d["waitSeconds"] == 6
    assert d["totalSeconds"] == 106
    assert d["minutes"] == 1.8
    assert "字/秒" in d["assumption"]


def test_repetition_report_ignores_short_lines():
    dup = "这是一句被重复写了很多次的台词。"
    blocks = [
        {"type": "label", "id": "start", "name": "start"},
        {"type": "dialogue", "characterId": "c", "text": dup},
        {"type": "dialogue", "characterId": "c", "text": dup},
        {"type": "dialogue", "characterId": "c", "text": dup},
        {"type": "dialogue", "characterId": "c", "text": "嗯。"},
        {"type": "dialogue", "characterId": "c", "text": "嗯。"},
        {"type": "narration", "text": "只有一次的话"},
    ]
    rep = repetition_report(_project([blocks]))
    assert rep["uniqueDuplicated"] == 1
    assert rep["top"][0]["count"] == 3
    assert rep["duplicateChars"] > 0
    assert 0 < rep["ratio"] < 1
    # 短句（"嗯。"）不计入重复
    assert all("嗯" not in item["text"] for item in rep["top"])


def test_counts_include_nested_blocks():
    blocks = [
        {"type": "label", "id": "start", "name": "start"},
        {
            "type": "if",
            "branches": [
                {
                    "condition": "affection >= 1",
                    "blocks": [
                        {"type": "music", "action": "play", "file": "bgm/a.ogg"},
                        {"type": "narration", "text": "分支里的旁白"},
                    ],
                }
            ],
        },
        {
            "type": "menu",
            "id": "m",
            "choices": [
                {
                    "text": "选",
                    "blocks": [{"type": "sound", "action": "play", "file": "sfx/a.mp3"}],
                }
            ],
        },
    ]
    out = analyze_script(_project([blocks]))
    counts = out["counts"]
    assert counts["music"] == 1
    assert counts["sound"] == 1
    assert counts["narration"] == 1
    assert counts["if"] == 1
    assert counts["menu"] == 1
