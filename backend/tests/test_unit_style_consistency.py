"""GB/T 15835 剩余那一项：百分号与计量单位的**体例统一**（只判一致性，不判对错）。

依据：GB/T 15835-2011《出版物上数字用法》除"什么时候用阿拉伯数字"外，还要求
**同一出版物内体例统一**——计量单位可用中文符号（公里/公斤）或国际符号（km/kg），
但不能在一本书里两种混着写。百分号的半角/全角同理。

判定纪律（与 `cjk_latin_spacing_mixed` 同款）：
- 只判"本书内部是否一致"，**不说哪种写法对**（两种都合规），所以是 `info`；
- 单位必须紧跟数字（`5km` / `5 公里`）才算——这是它的正常用法，
  也让 `m`（米）、`s`（秒）、`L`（升）这类单字母符号不在英文/变量名里误命中；
- 两边各 ≥2 次才报（孤零零一处不值得打扰作者）。

为什么值得单独测：这类"一致性"规则最容易变成噪音源——要么在干净稿子上乱报
（假阳性），要么阈值太松根本没触发过（等于没做）。这里真假两侧都钉。
"""

from __future__ import annotations

import pytest

from app.core.novel_consistency import _rule, analyze_novel_consistency
from app.core.project import normalize_project


def _project(*bodies: str):
    chapters = [
        {"id": f"c{i + 1}", "title": f"第{i + 1}章", "prose": body}
        for i, body in enumerate(bodies)
    ]
    return normalize_project({"id": "p-units", "title": "体例", "chapters": chapters})


def _codes(report) -> list[str]:
    return [str(i.get("code")) for i in report.get("issues") or []]


def _issue(report, code: str):
    return next((i for i in report.get("issues") or [] if i.get("code") == code), None)


# ---- 计量单位 ----------------------------------------------------------------


def test_mixed_unit_styles_are_reported_with_both_counts():
    report = analyze_novel_consistency(
        _project("他跑了五公里，又走了三公里。", "第二天又跑了 5km 和 3km，累得说不出话。")
    )
    issue = _issue(report, "unit_style_mixed")
    assert issue is not None, _codes(report)
    assert issue["severity"] == "info", "两种写法都合规，只报不一致，不能升级成错误"
    assert issue["evidence"]["unit"] == "公里"
    assert issue["evidence"]["chinese"] == 2
    assert issue["evidence"]["symbol"] == 2
    assert "GB/T 15835" in issue["basis"]
    assert "同一本书里应统一" in issue["message"]


@pytest.mark.parametrize(
    "bodies",
    [
        ("他跑了 5km，又走了 3km。", "第二天还是 2km。"),  # 全用国际符号
        ("他跑了五公里，又走了三公里。", "第二天又是两公里。"),  # 全用中文符号
        ("他跑了 5km，又走了三公里。", "第二天还是 2km。"),  # 一方只有 1 次
    ],
)
def test_single_style_or_thin_evidence_is_not_reported(bodies):
    """只写一种（或另一种只出现一次）不该报——这是最常见的假阳性来源。"""
    report = analyze_novel_consistency(_project(*bodies))
    assert "unit_style_mixed" not in _codes(report)


def test_unit_must_follow_a_number():
    """`m`/`s`/`L` 这类单字母符号只在紧跟数字时才算单位。"""
    report = analyze_novel_consistency(
        _project(
            "他量了三次米，也量了三次米。",  # 中文符号 2 次
            "The M and L are just letters; s is a letter too.",  # 没有数字跟在后面
        )
    )
    assert "unit_style_mixed" not in _codes(report)


def test_bare_symbols_without_digits_do_not_count():
    report = analyze_novel_consistency(
        _project("他量了两次米。" * 1 + "又量了两次米。", "km km km 只是字母而已。")
    )
    assert "unit_style_mixed" not in _codes(report)


def test_same_concept_alias_counts_together():
    """「公里」与「千米」是同义的两种中文写法，不再各自算一类（否则永远不触发）。"""
    report = analyze_novel_consistency(
        _project("路程是 5 千米。", "第二段是 3 公里，第三段 4km，第四段 6km。")
    )
    issue = _issue(report, "unit_style_mixed")
    assert issue is not None
    assert issue["evidence"]["chinese"] == 2
    assert issue["evidence"]["symbol"] == 2


# ---- 百分号 ------------------------------------------------------------------


def test_mixed_percent_styles_are_reported():
    report = analyze_novel_consistency(
        _project("出货率 30%，合格率 92%。", "退货率 5％ 与损耗 3％ 都记在表里。")
    )
    issue = _issue(report, "percent_style_mixed")
    assert issue is not None, _codes(report)
    assert issue["evidence"]["ascii"] == 2
    assert issue["evidence"]["fullwidth"] == 2
    assert "GB/T 15835" in issue["basis"]


def test_consistent_percent_style_is_not_reported():
    report = analyze_novel_consistency(_project("出货率 30%，合格率 92%，损耗 3%。"))
    assert "percent_style_mixed" not in _codes(report)


# ---- 与其它检查的配合 --------------------------------------------------------


def test_clean_manuscript_stays_clean():
    """一条"一致性"规则如果在正常稿子上乱报，就没人会看这些提示。"""
    report = analyze_novel_consistency(
        _project(
            "雨停了。他跑了五公里，回来时天已经黑了。",
            "第二天他跑了三公里，膝盖有点疼。",
        )
    )
    assert "unit_style_mixed" not in _codes(report)
    assert "percent_style_mixed" not in _codes(report)


def test_script_block_projects_are_covered_too():
    """正文在脚本块里的工程同样要查（只读 prose 会整章漏检——这是踩过的坑）。"""
    project = normalize_project(
        {
            "id": "p-units-blocks",
            "title": "体例",
            "chapters": [
                {
                    "id": "c1",
                    "title": "第一章",
                    "blocks": [
                        {"type": "narration", "text": "他跑了五公里，又走了三公里。"},
                        {"type": "narration", "text": "第二天又跑了 5km 和 3km。"},
                    ],
                }
            ],
        }
    )
    report = analyze_novel_consistency(project)
    assert "unit_style_mixed" in _codes(report)


def test_rules_have_headline_and_advice_for_the_ui():
    """界面直接显示 headline/advice：缺了会露出英文 code。"""
    for code in ("unit_style_mixed", "percent_style_mixed"):
        rule = _rule(code)
        assert rule["headline"] and rule["headline"] != code
        assert rule["advice"]
        assert rule["severity"] == "info"
        assert "GB/T 15835" in rule["basis"]
