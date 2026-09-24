"""分片窗口的暴露率：不变量 + 实测数字（Distance between Relevant Information Pieces）。

这一层不调用模型，所以可以在测试里跑真实测量：**用数字选窗口参数，而不是凭手感**。
测试既钉住结构性不变量（分片必须不漏章、相邻章必须同窗），也把当前默认值
（size=6, overlap=2）在若干书规模下的表现算出来，便于回归对比。
"""

from __future__ import annotations

from app.core.project import normalize_project
from app.core.scan_exposure import (
    chapter_exposure,
    compare_settings,
    pair_exposure,
    worst_distance_covered,
)


def _book(chapters: int, *, empty_every: int | None = None):
    """造一本 n 章的书；`empty_every` 用来插入没有正文的章（考验"按有正文的序列切"）。"""
    rows = []
    for i in range(1, chapters + 1):
        prose = "" if (empty_every and i % empty_every == 0) else f"第{i}章的正文。"
        rows.append({"id": f"c{i}", "title": f"第{i}章", "prose": prose, "blocks": []})
    return normalize_project({"id": "p", "title": "分片", "chapters": rows})


# ---- 不变量：分片方案最基本的承诺 -----------------------------------------------


def test_every_chapter_with_text_is_covered():
    """分片方案的卖点：任何有正文的章节都至少落在一窗里（旧审计会漏）。"""
    for chapters in (1, 5, 6, 7, 13, 40):
        for size, overlap in ((2, 0), (4, 1), (6, 2), (8, 4)):
            exposure = chapter_exposure(_book(chapters), size=size, overlap=overlap)
            assert exposure["min"] >= 1, (chapters, size, overlap, exposure)
            assert exposure["coverage"] == 1.0, (chapters, size, overlap, exposure)


def test_pairs_within_overlap_distance_always_share_a_window():
    """**定理**（可由规划器推导）：相距 ≤ overlap 章的章对必然同窗。

    推导：窗口起点是 stride = size - overlap 的倍数。取 ≤ i 的最大窗口起点 s，
    则 i ≤ s + stride - 1，于是 j = i + d ≤ s + stride - 1 + d；
    要保证 j 也在这一窗内，只需 stride - 1 + d ≤ size - 1，即 **d ≤ overlap**。

    这条定理就是"默认 overlap=2"的由来：它保证"一章与隔两章之间的矛盾"一定能被同一窗看到。
    """
    for chapters in (3, 6, 9, 25, 40):
        for size, overlap in ((3, 1), (6, 2), (8, 4), (12, 4)):
            pairs = pair_exposure(_book(chapters), size=size, overlap=overlap)
            for d in range(1, overlap + 1):
                if d > chapters - 1:
                    continue  # 书里根本没有这么远的章对（例如 3 章书最多相距 2）
                entry = pairs["byDistance"].get(str(d))
                assert entry is not None, (chapters, size, overlap, d)
                assert entry["rate"] == 1.0, (chapters, size, overlap, d, entry)


def test_zero_overlap_breaks_adjacent_pairs_at_window_boundaries():
    """overlap=0 时**相邻章也可能不同窗**（实测：size=2、6 章时相邻对暴露率只有 0.6）。

    这不是实现问题，是分片的固有代价：窗口边界把相邻章切在两侧。所以默认不是 overlap=0
    ——这条测试把这个反例固定下来，避免以后有人"省点成本把 overlap 设成 0"。
    """
    pairs = pair_exposure(_book(6), size=2, overlap=0)["byDistance"]
    assert pairs["1"]["rate"] == 0.6
    # 对齐在同一个窗口内的章对仍然能看见（c1-c2、c3-c4、c5-c6）
    assert pairs["1"]["exposed"] == 3


def test_exposure_decays_with_distance_for_small_overlap():
    """重叠很小时，距离越远的章对暴露率越低——这正是要测量的现象。"""
    project = _book(40)
    pairs = pair_exposure(project, size=4, overlap=1)["byDistance"]
    rates = [pairs[str(d)]["rate"] for d in range(1, 5) if str(d) in pairs]
    assert rates[0] == 1.0  # overlap ≥ 1 ⇒ 相邻章必然同窗（见上面的定理）
    assert rates == sorted(rates, reverse=True), rates  # 单调不增


def test_worst_distance_covered_equals_overlap_and_grows_with_it():
    """`worst_distance_covered` 的实测值就是 overlap（定理的另一面）。"""
    project = _book(40)
    assert worst_distance_covered(project, size=6, overlap=0, max_distance=6) == 0
    assert worst_distance_covered(project, size=6, overlap=1, max_distance=6) == 1
    assert worst_distance_covered(project, size=6, overlap=2, max_distance=6) == 2
    assert worst_distance_covered(project, size=8, overlap=4, max_distance=6) == 4


def test_empty_chapters_do_not_waste_window_slots():
    """空章不该占窗口位置：分片按"有正文的章节序列"切，所以覆盖仍然完整。

    （如果按"章节序号"切，空章会吃掉窗口名额，有正文的章反而更容易被挤出窗口。）
    """
    project = _book(20, empty_every=3)  # 每 3 章插一个空章
    exposure = chapter_exposure(project, size=6, overlap=2)
    assert exposure["coverage"] == 1.0
    assert exposure["chapters"] == 20 - 6  # 20 章里有 6 章没有正文（3,6,9,12,15,18）


def test_bigger_size_or_overlap_never_reduces_pair_exposure():
    """窗口变大或重叠变多，同窗的章对只可能更多、不可能更少（单调性）。"""
    project = _book(30)

    def total(size: int, overlap: int) -> int:
        pairs = pair_exposure(project, size=size, overlap=overlap)["byDistance"]
        return sum(int(v["exposed"]) for v in pairs.values())

    assert total(8, 2) >= total(6, 2) >= total(4, 2)
    assert total(6, 2) >= total(6, 0)
    assert total(12, 4) >= total(8, 4)


# ---- 当前默认值：把数字固定下来，便于回归对比 -----------------------------------


def test_current_default_settings_report():
    """默认 size=6 / overlap=2 在几种书规模下的表现（数字**故意**写进测试里）。

    不是"断言它够好"——而是让以后有人改分片策略时，能看到这些数字变了多少。
    断言的是最低要求：全书覆盖 1.0、相邻章同窗、距离 2 以内也全部同窗。
    """
    rows = {
        n: compare_settings(_book(n), [(6, 2)])[0] for n in (10, 30, 100)
    }
    for n, row in rows.items():
        assert row["chapterCoverage"] == 1.0, (n, row)
        assert row["minChapterWindows"] >= 1, (n, row)
        assert row["neighbourPairRate"] == 1.0, (n, row)
        assert row["byDistance"]["2"]["rate"] == 1.0, (n, row)


# ---- 窗口预算下的**书覆盖**：默认值就是照这个改的 -------------------------------


def test_window_cap_makes_size_the_lever_for_book_coverage():
    """窗口预算会被用满，所以"能扫多少章"由窗口大小决定（这条决定了新默认值）。

    实测（40/200 章、预算 16 窗）：
    - size=6 / overlap=2：每窗前进 4 章 → 6 + 15×4 = **66 章**
    - size=12 / overlap=4：每窗前进 8 章 → 12 + 15×8 = **132 章**，且同窗距离上限 2 → 4
    """
    from app.core.scan_exposure import coverage_under_cap

    book = _book(200)
    small = coverage_under_cap(book, size=6, overlap=2, max_windows=16)
    large = coverage_under_cap(book, size=12, overlap=4, max_windows=16)

    assert small["chaptersCovered"] == 66, small
    assert large["chaptersCovered"] == 132, large
    assert large["coverage"] > small["coverage"]
    assert small["distanceCovered"] == 2
    assert large["distanceCovered"] == 4
    # 同一预算下窗口数一样多：多出来的覆盖不是靠更多次调用换来的
    assert small["windowsRun"] == large["windowsRun"] == 16


def test_defaults_in_code_match_the_measured_choice():
    """代码里的默认值必须是测出来的那一组（12/4），别被改回手感值。"""
    import inspect

    from app.core.consistency_scan import plan_windows, run_consistency_scan

    for fn in (plan_windows, run_consistency_scan):
        params = inspect.signature(fn).parameters
        assert params["size"].default == 12, fn.__name__
        assert params["overlap"].default == 4, fn.__name__


def test_budget_below_one_window_covers_nothing_but_does_not_crash():
    from app.core.scan_exposure import coverage_under_cap

    row = coverage_under_cap(_book(30), size=12, overlap=4, max_windows=0)
    assert row["windowsRun"] == 0
    assert row["chaptersCovered"] == 0
    assert row["coverage"] == 0.0


def test_compare_settings_grid_is_usable():
    """对照实验的默认网格：每组都要给出可比较的字段（供人选参数）。"""
    rows = compare_settings(_book(40))
    assert len(rows) >= 5
    for row in rows:
        for key in ("size", "overlap", "windows", "chapterCoverage", "neighbourPairRate"):
            assert key in row, row
        assert row["chapterCoverage"] == 1.0, row
    # 窗口数随书规模与步长变化：更小的步长（更大的重叠）意味着更多窗口、更贵
    by_windows = {row["windows"] for row in rows}
    assert len(by_windows) > 1
