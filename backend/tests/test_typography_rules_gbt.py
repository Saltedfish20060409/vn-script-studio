"""按国标新增的表记规则：真阳性要报、假阳性不能报。

为什么单独一个文件：这些规则的**误报代价最高**——它们会在每个作者身上反复出现，
一次误报就足以让作者关掉整个体检。所以每条规则都配"应该报"和"绝不能报"两边的用例。

依据：GB/T 15835-2011《出版物上数字用法》、CY/T 154-2017《中文出版物夹用英文的编辑规范》。
"""

from __future__ import annotations

from app.core.novel_consistency import analyze_novel_consistency
from app.core.project import normalize_project


def _codes(prose: str) -> set[str]:
    vn = normalize_project(
        {
            "id": "p",
            "title": "r",
            "chapters": [{"id": "c1", "title": "第一章", "prose": prose}],
        }
    )
    return {i["code"] for i in analyze_novel_consistency(vn)["issues"]}


def _codes_multi(chapters: list[str]) -> set[str]:
    vn = normalize_project(
        {
            "id": "p",
            "title": "r",
            "chapters": [
                {"id": f"c{i}", "title": f"第{i}章", "prose": p}
                for i, p in enumerate(chapters, start=1)
            ],
        }
    )
    return {i["code"] for i in analyze_novel_consistency(vn)["issues"]}


# ---- GB/T 15835-2011 数字用法 -------------------------------------------------


def test_cjk_year_is_reported_and_arabic_year_is_not():
    assert "cjk_year_digits" in _codes("二〇一九年的秋天，他回到这里。")
    assert "cjk_year_digits" not in _codes("2019 年的秋天，他回到这里。")
    # 「三年」「那一年」不是公历年份，不能报
    assert "cjk_year_digits" not in _codes("三年后，他又回来了。那一年他十九岁。")


def test_arabic_digits_with_ji_is_reported():
    assert "arabic_with_ji" in _codes("大约10几个人挤在门口。")
    assert "arabic_with_ji" not in _codes("大约十几个人挤在门口。")
    # 「10 多个人」是规范允许的写法
    assert "arabic_with_ji" not in _codes("大约10多个人挤在门口。")


def test_arabic_dunhao_approximation_is_reported_but_ordinal_list_is_not():
    assert "arabic_dunhao_range" in _codes("那是3、4年前的事了。")
    # 并列编号（第3、4章）不是概数，绝不能报
    assert "arabic_dunhao_range" not in _codes("请翻到第3、4章对照着看。")
    # 汉字概数是规范写法
    assert "arabic_dunhao_range" not in _codes("那是三四年前的事了。")


def test_digit_range_dash_is_reported_on_numbers_only():
    assert "dash_ascii_range" in _codes("2019-2020 年间，他还在这里。")
    # 英文里的连字符是正常写法
    assert "dash_ascii_range" not in _codes("他打开了 well-known 的 SARS-CoV-2 词条。")


# ---- CY/T 154-2017：中英间距的**内部一致性** ----------------------------------


def test_mixed_cjk_latin_spacing_is_reported():
    prose = "他打开 Steam 看了一眼，又关掉了 KDE。然后打开Steam再看，又关掉KDE。"
    assert "cjk_latin_spacing_mixed" in _codes(prose)


def test_consistent_cjk_latin_spacing_is_not_reported():
    # 全书统一加空格
    spaced = "他打开 Steam 看了一眼，又打开 Steam 看了第二眼。"
    assert "cjk_latin_spacing_mixed" not in _codes(spaced)
    # 全书统一不加空格
    tight = "他打开Steam看了一眼，又打开Steam看了第二眼。"
    assert "cjk_latin_spacing_mixed" not in _codes(tight)


def test_spacing_check_needs_both_styles_at_least_twice():
    """只有一两处时不要提——那更可能是笔误而不是风格摇摆，提了就是噪音。"""
    prose = "他打开 Steam 看了一眼，然后打开Steam。"
    assert "cjk_latin_spacing_mixed" not in _codes(prose)


def test_spacing_issue_reports_counts_and_basis():
    """报出来时要能说清"两边各有多少处"，并带上依据。"""
    prose = "他打开 Steam 看了一眼，又关掉了 KDE。然后打开Steam再看，又关掉KDE。"
    vn = normalize_project(
        {"id": "p", "title": "r", "chapters": [{"id": "c1", "title": "第一章", "prose": prose}]}
    )
    issues = {
        i["code"]: i for i in analyze_novel_consistency(vn)["issues"]
    }
    issue = issues["cjk_latin_spacing_mixed"]
    assert issue["evidence"]["spaced"] >= 2
    assert issue["evidence"]["tight"] >= 2
    assert "CY/T 154-2017" in issue["basis"]
    # 依据里要写明"不判定哪种对"，否则作者会以为我们在替他做风格决定
    assert "不判定" in issue["basis"]


def test_no_digit_rules_fire_on_clean_prose():
    clean = (
        "2019 年的秋天，他回到这座小镇。\n"
        "三四年前的事，他已经记不清了。\n"
        "大约十几个人挤在门口，谁也没有说话。\n"
        "他打开 Steam 看了一眼，又打开 Steam 看了第二眼。\n"
    )
    codes = _codes(clean)
    for noisy in (
        "cjk_year_digits",
        "arabic_with_ji",
        "arabic_dunhao_range",
        "dash_ascii_range",
        "cjk_latin_spacing_mixed",
    ):
        assert noisy not in codes, f"{noisy} 在干净正文上误报了"
