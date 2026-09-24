"""规则依据：不允许"没有出处的规则"，且前后端两份依据不能分叉。

为什么专门一个文件：
1. 这些标点/表记规则过去只有"我们觉得该这样"。作者看到提示的第一反应是"凭什么"——
   现在每条都要指向公开可查的规范（GB/T 15834-2011、GB/T 15835-2011、CY/T 154-2017、
   W3C clreq），或者如实标成"作品自身的一致性（启发式）"。**没有依据的规则不该上线**：
   它会让作者无法判断该不该听。
2. 依据有两份副本（前端在打字时跑、后端在全书体检时跑）。分叉时作者会看到最难查的那种
   bug：同一处，写作辅助说"用单书名号"，稿件体检一声不吭。所以这里直接解析 TS 源文件比对。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.novel_consistency import (
    _RULE_BASIS,
    _TYPO_RULES,
    analyze_novel_consistency,
)
from app.core.project import normalize_project

FRONTEND_TS = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend"
    / "src"
    / "lib"
    / "editorAssist.ts"
)

#: TS 里 RULE_BASIS 表的条目：code: "依据…",
_TS_BASIS_RE = re.compile(r'^\s{2}([a-z_]+):\s*$|^\s{2}([a-z_]+):\s*"', re.MULTILINE)

#: 会真正报出来的规则码（写成常量而不是"跑一遍看看"，是为了让新增规则时必须**显式**
#: 在这里登记——否则守卫会被"新规则没被覆盖到"悄悄绕过）。
EXPECTED_CODES = {
    "punct_half_full_adjacent",
    "punct_halfwidth_near_cjk",
    "digit_width_mixed",
    "letter_width_mixed",
    "name_spaced_variant",
    "quote_unbalanced",
    "quote_order_illegal",
    "quote_nested_level",
    "title_mark_nested",
    "dash_ascii_double",
    "dash_single_em",
    "dash_ascii_range",
    "cjk_year_digits",
    "arabic_with_ji",
    "arabic_dunhao_range",
    "cjk_latin_spacing_mixed",
    "ellipsis_ascii_dots",
    "ellipsis_fullwidth_period",
    "ellipsis_style_mixed",
    "ellipsis_with_deng",
    "name_char_variant",
    "name_char_variant_suspect",
    "pov_shift",
    "address_level_drift",
    "typo_confusion",
}


def _frontend_basis_codes() -> set[str]:
    """解析 TS 里 RULE_BASIS 的键。

    注意要同时支持两种书写形式（第一版只认了单行，少解析了 4 条）：
        code: "依据…",
        code:
          "跨行写得很长的依据…",
    """
    text = FRONTEND_TS.read_text(encoding="utf-8")
    block = text.split("export const RULE_BASIS", 1)[1].split("};", 1)[0]
    codes: set[str] = set()
    for line in block.splitlines():
        # 恰好两个空格缩进的 `key:` —— 值可能在同行，也可能在下一行
        m = re.match(r"^ {2}([a-z_]+):", line)
        if m:
            codes.add(m.group(1))
    return codes


def test_frontend_file_is_parsable():
    assert FRONTEND_TS.exists(), f"找不到前端文件：{FRONTEND_TS}"
    codes = _frontend_basis_codes()
    assert len(codes) >= 10, f"只解析到 {len(codes)} 条依据，TS 结构可能变了"


def test_every_known_rule_has_a_basis():
    """后端每个规则都要有依据，且依据不能是空话。"""
    missing = sorted(EXPECTED_CODES - set(_RULE_BASIS))
    assert not missing, f"这些规则没有登记依据：{missing}"
    for code, basis in _RULE_BASIS.items():
        assert len(basis.strip()) > 8, f"{code} 的依据太短，等于没写：{basis!r}"


def test_basis_points_at_a_checkable_source_or_says_it_does_not():
    """依据要么给出公开规范，要么如实说明"没有规范依据/作品自身一致性"。"""
    for code, basis in _RULE_BASIS.items():
        ok = any(
            token in basis
            for token in (
                "GB/T",
                "CY/T",
                "clreq",
                "作品自身",
                "编辑规范",
                "通用写法",
                "无规范依据",
            )
        )
        assert ok, f"{code} 的依据看不出出处：{basis}"


def test_rule_table_codes_are_all_documented():
    """`_TYPO_RULES` 里的 code 也必须都在依据表里（加了规则忘了写依据会红）。"""
    undocumented = sorted(set(_TYPO_RULES) - set(_RULE_BASIS))
    assert not undocumented, f"规则表里有、依据表里没有：{undocumented}"


def test_frontend_and_backend_share_the_same_rule_vocabulary():
    """前后端依据表的 code 集合必须一致，例外必须显式登记并写清原因。"""
    frontend = _frontend_basis_codes()
    backend = set(_RULE_BASIS)

    # 只有前端会做的"清洁度"规则：后端不查它们，因为
    # 1) 它们不是规范问题（行尾空格不影响阅读，也不影响导出）；
    # 2) 后端扫的是 `_author_lines`（逐行原文），行尾空格在那里本来就被 strip 掉了。
    allowed_frontend_only = {"space_between_cjk", "trailing_space"}
    assert frontend - backend <= allowed_frontend_only, (
        f"前端有而后端没有的规则超出允许集合：{sorted(frontend - backend - allowed_frontend_only)}"
    )

    # 只有后端会做的：全书级判断（人名变体、视角、称呼）与章级判断（宽度混用、引号顺序）。
    # 前端要么拿不到全书视野，要么按行判会误报，所以刻意不做。
    allowed_backend_only = {
        "name_char_variant",
        "name_char_variant_suspect",
        "name_spaced_variant",
        "digit_width_mixed",
        "letter_width_mixed",
        "quote_order_illegal",
        "ellipsis_style_mixed",
        # 全书级启发式：前端没有全书视野（也不该为了一句话去扫描整部作品）
        "pov_shift",
        "address_level_drift",
        # 全书级一致性：中英间距是否自相矛盾要看整本书（单看一行无从判断）
        "cjk_latin_spacing_mixed",
        # 全书级一致性（GB/T 15835 的体例统一要求）：百分号形态、计量单位的中文/国际符号
        # 混用同样要看整本书——单看一行既看不出混用，也没法给"两边各多少处"的证据。
        "percent_style_mixed",
        "unit_style_mixed",
    }
    assert backend - frontend <= allowed_backend_only, (
        f"后端有而前端没有的规则超出允许集合：{sorted(backend - frontend - allowed_backend_only)}"
    )


def test_issues_carry_the_basis():
    """每条问题都要带上依据——界面上要能直接显示"凭什么"。"""
    vn = normalize_project(
        {
            "id": "p-basis",
            "title": "依据",
            "chapters": [
                {
                    "id": "c1",
                    "title": "第一章",
                    "prose": "我在读《钟声与《第七个抽屉》》。\n2019-2020 年间，他迫不急待地来了。",
                }
            ],
        }
    )
    report = analyze_novel_consistency(vn)
    assert report["issues"], "这段文本本该报出问题"
    for issue in report["issues"]:
        assert issue["basis"], f"{issue['code']} 的问题没有带依据"
        assert issue["basis"] == _RULE_BASIS[issue["code"]]


def test_new_standard_backed_rules_do_not_fire_on_clean_text():
    """干净正文不能被新规则误伤（国标类规则最容易一加就到处报）。"""
    clean = (
        "雨停的时候，站台的灯还亮着。\n"
        "「走吧，」她说，「反正末班车已经过去了。」\n"
        "《钟声与失物招领处》是他最喜欢的一本。\n"
        "他点了点头——那种没什么意义的、习惯性的点头。\n"
        "后来的事，他已经不想再提了……\n"
        "2019—2020 年间，这里还很安静。\n"
    )
    report = analyze_novel_consistency(normalize_project({"id": "p", "title": "t", "chapters": [{"id": "c1", "title": "x", "prose": clean}]}))
    codes = {i["code"] for i in report["issues"]}
    for noisy in (
        "quote_nested_level",
        "title_mark_nested",
        "dash_ascii_range",
        "ellipsis_with_deng",
    ):
        assert noisy not in codes, f"{noisy} 在干净正文上误报了"
