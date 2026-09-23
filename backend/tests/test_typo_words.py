"""别字词表：后端那份与前端那份必须逐条一致，且真的会出现在全书体检里。

为什么要这个文件：
- 词表存在两份是**架构决定的**（前端要在打字时跑，后端要在全书体检时跑，两边语言不同）。
  两份一旦分叉，作者会遇到最难受的一种 bug：写作辅助提示了、全书体检不报（或者反过来），
  而两边看起来都"没错"。所以这里直接解析 TS 源文件逐条比对。
- 另外要证明它**真的接进了 `analyze_novel_consistency`**：词表写得再对，
  没挂到检查链路上等于没有。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.novel_consistency import analyze_novel_consistency
from app.core.project import normalize_project
from app.core.typo_words import WORD_CONFUSIONS, find_word_confusions, line_of

FRONTEND_TS = (
    Path(__file__).resolve().parent.parent.parent
    / "frontend"
    / "src"
    / "lib"
    / "typoRules.ts"
)

#: TS 里成对出现的字面量： ["迫不急待", "迫不及待"],
_PAIR_RE = re.compile(r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\]')


def _frontend_pairs() -> list[tuple[str, str]]:
    text = FRONTEND_TS.read_text(encoding="utf-8")
    # 只取 IDIOMS 与 FIXED 两个数组里的内容（文件里没有别的成对字面量，
    # 但仍按数组边界切一次，免得以后加了别的表被误收）
    idioms = text.split("const IDIOMS", 1)[1].split("];", 1)[0]
    fixed = text.split("const FIXED", 1)[1].split("];", 1)[0]
    return _PAIR_RE.findall(idioms) + _PAIR_RE.findall(fixed)


def test_frontend_word_list_exists():
    """解析不到就说明前端文件被改名/改结构了，必须显式失败而不是静默通过。"""
    assert FRONTEND_TS.exists(), f"找不到前端词表：{FRONTEND_TS}"
    pairs = _frontend_pairs()
    assert len(pairs) >= 60, f"只解析到 {len(pairs)} 条，TS 结构可能变了"


def test_backend_list_matches_frontend_exactly():
    """逐条、同顺序比对（顺序也要求一致：这样 diff 起来能一眼看出谁多谁少）。"""
    assert [(w, r) for w, r, _k in WORD_CONFUSIONS] == _frontend_pairs()


def test_no_duplicates_or_self_referential_pairs():
    wrongs = [w for w, _r, _k in WORD_CONFUSIONS]
    assert len(set(wrongs)) == len(wrongs)
    rights = {r for _w, r, _k in WORD_CONFUSIONS}
    # A→B 与 B→A 同时存在会互相打架
    assert not (rights & set(wrongs))
    # 错写形式不能是正确写法的子串，否则会重复命中同一处
    for wrong, right, _kind in WORD_CONFUSIONS:
        assert wrong not in right


def test_find_word_confusions_reports_positions():
    hits = find_word_confusions("他迫不急待地推开门，又好象在等谁。")
    assert [h["wrong"] for h in hits] == ["迫不急待", "好象"]
    assert [h["right"] for h in hits] == ["迫不及待", "好像"]
    assert hits[0]["offset"] < hits[1]["offset"]


def test_line_of_counts_lines():
    text = "第一行。\n第二行，迫不急待。"
    hit = find_word_confusions(text)[0]
    assert line_of(text, int(hit["offset"])) == 2


def test_clean_text_has_no_hits():
    clean = "雨停的时候，站台的灯还亮着。\n「走吧，」她说，「反正末班车已经过去了。」"
    assert find_word_confusions(clean) == []


def _project(prose: str):
    return normalize_project(
        {
            "id": "p-typo",
            "title": "别字样本",
            "chapters": [{"id": "ch1", "title": "第一章", "prose": prose}],
        }
    )


def test_typo_confusion_is_reported_by_book_audit():
    """接进了检查链路：全书体检要报出别字，且带上行号与建议写法。"""
    report = analyze_novel_consistency(
        _project("他迫不急待地推开门。\n一切一如继往。")
    )
    typos = [i for i in report["issues"] if i["code"] == "typo_confusion"]
    assert len(typos) == 2
    codes = {i["quote"] for i in typos}
    assert codes == {"迫不急待", "一如继往"}
    first = next(i for i in typos if i["quote"] == "迫不急待")
    assert first["severity"] == "warn"
    assert first["line"] == 1
    assert "迫不及待" in first["message"]
    assert first["evidence"]["right"] == "迫不及待"
    second = next(i for i in typos if i["quote"] == "一如继往")
    assert second["line"] == 2


def test_typo_check_does_not_group_away_the_suggestion():
    """同一个别字出现三次要报三条（每条都带"应该怎么写"），不是合并成一条"共 3 处"。"""
    report = analyze_novel_consistency(_project("迫不急待。迫不急待。迫不急待。"))
    typos = [i for i in report["issues"] if i["code"] == "typo_confusion"]
    assert len(typos) == 3
    assert all("迫不及待" in i["message"] for i in typos)


def test_clean_chapter_reports_no_typos():
    report = analyze_novel_consistency(_project("他迫不及待地推开门，一如既往地沉默。"))
    assert [i for i in report["issues"] if i["code"] == "typo_confusion"] == []


def test_script_block_chapter_also_gets_typos():
    """脚本工程的章节同样要查：只读 prose 会让"用块写的稿子"整章漏检。"""
    project = normalize_project(
        {
            "id": "p-blocks",
            "title": "块工程",
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "blocks": [{"type": "narration", "text": "他迫不急待地说。"}],
                }
            ],
        }
    )
    report = analyze_novel_consistency(project)
    assert [i["quote"] for i in report["issues"] if i["code"] == "typo_confusion"] == ["迫不急待"]
