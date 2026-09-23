"""长程一致性基准测试。

这份基准的价值全在**可信度**上，所以测试重点不是"能跑"，而是：
- 干净基线真的干净（没注入矛盾的章节不能被确定性检测器乱报，否则 precision 无意义）；
- 埋点的章距确实落在多个分桶里（否则"衰减曲线"是假的）；
- 判定口径按文档说的来（命中 / 分类错 / 误报 / 范畴外 各自可复现）；
- 基准用的分片方案**就是生产实现**（评测与被测对象不一致是这类实验最经典的失效）。
"""

from __future__ import annotations

from app.core.eval_longrange import (
    DISTANCE_BUCKETS,
    bucket_of,
    build_synthetic_novel,
    chunked_plan,
    detect_deterministic,
    evaluate_detections,
    evaluate_exposure,
    format_report,
    legacy_plan,
    run_benchmark,
)
from app.core.harness.audit_full import full_audit_draft
from app.core.project import normalize_project

# ------------------------------------------------------------------ 生成器


def test_synthetic_novel_has_the_requested_length_and_labels():
    project, gt = build_synthetic_novel(chapters=40, seed=1)
    assert len(project.chapters) == 40
    assert gt["chapters"] == 40
    assert gt["planted"], "必须有埋点，否则基准没有标准答案"
    # 每章都要有可演的正文，否则 exposure 之类的指标就没有内容可谈
    for ch in project.chapters:
        kinds = {b.get("type") for b in ch.blocks}
        assert "dialogue" in kinds and "narration" in kinds


def test_planted_items_span_multiple_distance_buckets():
    _, gt = build_synthetic_novel(chapters=60, seed=3)
    buckets = gt["counts"]["byBucket"]
    # 五个分桶必须全有：少了近端就没法证明"短距离本来查得出来"，
    # 那样衰减曲线只能说明"这个检测器不行"，不能说明"长程失效"。
    assert set(buckets) == {name for name, _lo, _hi in DISTANCE_BUCKETS}, buckets
    for it in gt["planted"]:
        est = int(str(it["establishedChapter"]).replace("ch", ""))
        con = int(str(it["conflictChapter"]).replace("ch", ""))
        assert con > est, it
        assert it["distance"] == con - est
        assert it["bucket"] == bucket_of(it["distance"])


def test_both_tiers_are_planted():
    _, gt = build_synthetic_novel(chapters=48, seed=5)
    assert gt["counts"]["deterministic"] >= 4
    assert gt["counts"]["semantic"] >= 4
    kinds = {it["kind"] for it in gt["planted"]}
    assert "death_then_speaks" in kinds
    assert "timeline_order_conflict" in kinds
    assert "age_conflict" in kinds
    # 「角色像不像本人」这一维也必须有带标注埋点，否则它没有可量化的召回
    assert "voice_drift" in kinds
    assert all(it["subject"] for it in gt["planted"]), "每个埋点都要标明主语"


def test_planted_items_occupy_disjoint_chapters():
    """回归闸：埋点之间不能共用章节。

    共用的后果不是"数字难看一点"，而是**判定变得含糊**：一个埋点的建立章正好是另一个
    的冲突章时，检测器只报一条就同时落在两个跨度里，基准把它算给其中一个，
    另一个变成凭空漏检——实测正是这条把确定性层召回从 1.00 压到了 0.90。
    """
    for seed in (3, 14, 21, 20260409):
        _, gt = build_synthetic_novel(chapters=60, seed=seed)
        seen: dict[str, str] = {}
        for it in gt["planted"]:
            for key in ("establishedChapter", "conflictChapter"):
                ch = str(it[key])
                assert ch not in seen, (
                    f"seed={seed}：{ch} 被 {seen[ch]} 与 {it['id']} 共用"
                )
                seen[ch] = it["id"]


def test_voice_drift_items_are_detected_by_the_voice_metric():
    """声线量具要能把"寡言角色被写成长篇大论"抓出来——这是这一维唯一的量化证据。"""
    project, gt = build_synthetic_novel(chapters=48, seed=14)
    voice_items = [it for it in gt["planted"] if it["kind"] == "voice_drift"]
    assert voice_items
    detected = {
        ch
        for d in detect_deterministic(project)
        if d["code"] == "voice_drift"
        for ch in d["chapterIds"]
    }
    for it in voice_items:
        assert it["conflictChapter"] in detected, it


def test_benchmark_covers_every_deterministic_kind():
    """基准要覆盖全部"确定性可分"的问题类型。

    这条是**覆盖率闸**：哪一类埋点被删掉或不再被检出，这里都会红。
    语义层（年龄/季节/关系/物件）必须靠模型，不在此列。
    """
    _, gt = build_synthetic_novel(chapters=60, seed=20260409)
    kinds = {it["kind"] for it in gt["planted"] if it["tier"] == "deterministic"}
    assert kinds >= {
        "unknown_speaker",
        "death_then_speaks",
        "timeline_order_conflict",
        "unknown_location_tag",
        "voice_drift",
        "emotion_arc_break",
        "foreshadow_unresolved",
    }, kinds


def test_emotion_arc_break_items_are_detected_at_the_break_chapter():
    """情感弧线断裂必须按**断裂章**归因，而不是只给个"全篇有问题"。

    用 60 章：情感埋点每个要占**三**章（建立/断裂/收尾），
    章节不够时会少埋几个（宁可不埋也不撞章）——48 章时只能埋下 1 个。
    """
    project, gt = build_synthetic_novel(chapters=60, seed=20260409)
    items = [it for it in gt["planted"] if it["kind"] == "emotion_arc_break"]
    assert len(items) >= 2, items
    detected = {
        ch
        for d in detect_deterministic(project)
        if d["code"] == "emotion_arc_break"
        for ch in d["chapterIds"]
    }
    for it in items:
        assert it["conflictChapter"] in detected, it
    # 每个埋点用独立角色，否则全篇起点会被另一个埋点污染（见生成器注释）
    assert len({it["subject"] for it in items}) == len(items)


def test_unresolved_foreshadow_items_are_detected_and_paid_ones_are_not():
    """未回收伏笔要被报；**已回收的对照组一条都不该报**。"""
    project, gt = build_synthetic_novel(chapters=48, seed=14)
    items = [it for it in gt["planted"] if it["kind"] == "foreshadow_unresolved"]
    assert items
    hooks = [d for d in detect_deterministic(project) if d["code"] == "foreshadow_unresolved"]
    # 一条未回收 = 一条检出；已回收的钩子不进 openHooks，所以数量应当正好对上
    assert len(hooks) == len(items), (len(hooks), len(items))
    detected = {ch for d in hooks for ch in d["chapterIds"]}
    for it in items:
        assert it["conflictChapter"] in detected, it


def test_foreshadow_planting_makes_the_resolution_rate_measurable():
    """埋了伏笔之后，回收率就必须是一个有意义的数（而不是 0/0 的 None）。"""
    from app.core.story_metrics import foreshadow_resolution

    project, _gt = build_synthetic_novel(chapters=48, seed=14)
    out = foreshadow_resolution(project)
    assert out["total"] >= 2
    assert out["paid"] >= 1, "必须留一条已回收的作对照，否则回收率恒为 0"
    assert out["open"] >= 1
    assert out["resolutionRate"] is not None
    assert 0 < out["resolutionRate"] < 1


def test_generation_is_reproducible():
    a, gt_a = build_synthetic_novel(chapters=30, seed=11)
    b, gt_b = build_synthetic_novel(chapters=30, seed=11)
    assert gt_a["planted"] == gt_b["planted"]
    assert [c.blocks for c in a.chapters] == [c.blocks for c in b.chapters]
    _, gt_c = build_synthetic_novel(chapters=30, seed=12)
    assert gt_c["planted"] != gt_a["planted"]


def test_distractors_are_marked_and_not_counted_as_planted():
    _, gt = build_synthetic_novel(chapters=40, seed=2, distractors=3)
    assert len(gt["distractors"]) == 3
    planted_ids = {it["id"] for it in gt["planted"]}
    for d in gt["distractors"]:
        assert d["id"] not in planted_ids
        assert d["why"], "诱导项必须说明为什么它不是矛盾"


def test_too_few_chapters_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        build_synthetic_novel(chapters=5)


# ------------------------------------------------------------------ 暴露率


def test_legacy_plan_exposes_only_the_first_chapters():
    project, gt = build_synthetic_novel(chapters=48, seed=4)
    plan = legacy_plan(project)
    assert len(plan) == 1
    assert len(plan[0]["chapterIds"]) == 14
    ex = evaluate_exposure(gt, plan)
    assert ex["chaptersVisible"] == 14
    assert ex["chaptersTotal"] == 48
    # 关键结论：旧方案下后段的埋点**在构造上**就不可能被检出
    assert ex["exposureRecall"] < 1.0
    assert ex["missedItems"], "旧方案必须漏掉后段埋点"


def test_chunked_plan_exposes_every_chapter():
    project, gt = build_synthetic_novel(chapters=48, seed=4)
    plan = chunked_plan(project)
    ex = evaluate_exposure(gt, plan)
    assert ex["chaptersVisible"] == 48
    assert ex["exposureRecall"] == 1.0
    assert ex["missedItems"] == []
    for _name, row in ex["byBucket"].items():
        assert row["recall"] == 1.0


def test_chunked_plan_uses_the_production_window_planner():
    """基准必须测线上真正跑的那套切窗逻辑，不能自说自话。"""
    from app.core.consistency_scan import plan_windows as prod_plan

    project, _ = build_synthetic_novel(chapters=48, seed=6)
    mine = chunked_plan(project)
    prod = prod_plan(project)
    assert all(w.get("production") is True for w in mine), "回落到本地实现了"
    assert [w["chapterIds"] for w in mine] == [
        [str(x) for x in (w.get("chapterIds") or [])] for w in prod
    ]


def test_exposure_is_monotonic_in_visibility():
    project, gt = build_synthetic_novel(chapters=48, seed=7)
    full = evaluate_exposure(gt, chunked_plan(project))
    half = evaluate_exposure(
        gt, [{"chapterIds": [str(c.id) for c in project.chapters][:24]}]
    )
    assert half["exposureRecall"] <= full["exposureRecall"]
    assert half["chaptersVisible"] < full["chaptersVisible"]


# -------------------------------------------------------------------- 检测评分


def _perfect_detector(gt: dict) -> list[dict]:
    return [
        {
            "code": "perfect",
            "category": it["category"],
            "chapterIds": [it["conflictChapter"]],
        }
        for it in gt["planted"]
    ]


def test_perfect_detector_scores_one():
    _, gt = build_synthetic_novel(chapters=40, seed=8)
    out = evaluate_detections(gt, _perfect_detector(gt))
    assert out["precision"] == 1.0
    assert out["recall"] == 1.0
    assert out["f1"] == 1.0
    assert out["fp"] == 0


def test_no_detections_scores_zero_recall():
    _, gt = build_synthetic_novel(chapters=40, seed=8)
    out = evaluate_detections(gt, [])
    assert out["recall"] == 0.0
    assert out["tp"] == 0
    assert len(out["missedItems"]) == gt["counts"]["total"]


def test_false_positive_is_counted_as_false_positive():
    _, gt = build_synthetic_novel(chapters=40, seed=8)
    # 挑一个**不在任何埋点跨度里**的章节，否则它会算成"重复命中"而不是误报
    spanned = {
        str(it[k]) for it in gt["planted"] for k in ("establishedChapter", "conflictChapter")
    }
    free = next(f"ch{i}" for i in range(1, 41) if f"ch{i}" not in spanned)
    dets = _perfect_detector(gt) + [
        {"code": "noise", "category": "character", "chapterIds": [free]}
    ]
    out = evaluate_detections(gt, dets)
    assert out["tp"] == gt["counts"]["total"]
    assert out["fp"] == 1
    assert out["precision"] < 1.0


def test_wrong_category_at_right_chapter_is_misclassified_not_fp():
    _, gt = build_synthetic_novel(chapters=40, seed=8)
    first = gt["planted"][0]
    wrong = "location" if first["category"] != "location" else "timeline"
    out = evaluate_detections(
        gt,
        [{"code": "wrong", "category": wrong, "chapterIds": [first["conflictChapter"]]}],
    )
    assert out["fp"] == 0
    assert len(out["misclassified"]) == 1
    assert out["tp"] == 0


def test_structural_findings_are_out_of_scope_not_fp():
    """结构性 lint（死代码之类）不该拉低"事实矛盾检出"的 precision。"""
    _, gt = build_synthetic_novel(chapters=40, seed=8)
    out = evaluate_detections(
        gt,
        [
            {"code": "dead_block", "category": "style", "chapterIds": ["ch3"]},
            {"code": "no_chapter", "category": "character", "chapterIds": []},
        ],
    )
    assert out["fp"] == 0
    assert len(out["outOfScope"]) == 2


def test_duplicate_detections_do_not_inflate_recall():
    _, gt = build_synthetic_novel(chapters=40, seed=8)
    first = gt["planted"][0]
    dup = [
        {"code": "a", "category": first["category"], "chapterIds": [first["conflictChapter"]]},
        {"code": "b", "category": first["category"], "chapterIds": [first["conflictChapter"]]},
    ]
    out = evaluate_detections(gt, dup)
    assert out["tp"] == 1
    assert out["duplicateHits"] >= 1
    assert out["fp"] == 0


def test_recall_is_broken_down_by_bucket_and_tier():
    _, gt = build_synthetic_novel(chapters=60, seed=9)
    # 只命中"近处"的埋点（章距 <= 8），模拟"只看窗口边界"的检测器
    near = [
        {
            "code": "near",
            "category": it["category"],
            "chapterIds": [it["conflictChapter"]],
        }
        for it in gt["planted"]
        if it["distance"] <= 8
    ]
    out = evaluate_detections(gt, near)
    by_bucket = out["byBucket"]
    for name, row in by_bucket.items():
        if name in ("1-3", "4-8"):
            assert row["recall"] == 1.0, (name, row)
        else:
            assert row["recall"] == 0.0, (name, row)
    assert "deterministic" in out["byTier"] and "semantic" in out["byTier"]


# ------------------------------------------------------------- 确定性检测器接入


def test_clean_baseline_has_no_factual_findings():
    """没被注入矛盾的章节不能被乱报——否则 precision 被结构性噪音淹没。

    注意：这里只校验**事实类**检测器。结构性 lint（章末无出口等）本来就会
    对基线报警，它们被 evaluate_detections 归到 outOfScope，不参与 precision。
    """
    project, _gt = build_synthetic_novel(
        chapters=36, seed=13, deterministic_per_kind=0, semantic_per_kind=0, distractors=0
    )
    factual = [
        d
        for d in detect_deterministic(project)
        if d["category"] in {"character", "timeline", "location"}
    ]
    assert factual == [], f"干净基线出现了事实类告警：{factual[:3]}"


def test_deterministic_detector_catches_every_deterministic_item_with_no_fp():
    """回归闸：确定性层必须**全中且零误报**。

    这条断言把基准变成量具：以后任何检测器被改坏、或者生成器不小心制造了
    计划外的矛盾，这里都会红。语义层（需要模型）召回 0 是预期内的，不在此断言。
    """
    project, gt = build_synthetic_novel(chapters=48, seed=14)
    out = evaluate_detections(gt, detect_deterministic(project))
    assert out["byTier"]["deterministic"]["recall"] == 1.0, out["missedItems"]
    assert out["byTier"]["semantic"]["recall"] == 0.0
    assert out["precision"] == 1.0, out["falsePositives"]
    assert out["fp"] == 0
    # 重复命中是**良性**的：同一处顺序矛盾可能从"早的那一端"和"晚的那一端"
    # 各报一条，两条都落在同一埋点的跨度内。它们被计数但不会刷高 TP。
    assert out["duplicateHits"] <= 4, out["duplicateHits"]


def test_planted_death_gap_keeps_the_declared_distance_meaningful():
    """死亡埋点在"去世→冲突章"之间必须让该角色闭嘴，否则首次违规章不是声明的冲突章。"""
    project, gt = build_synthetic_novel(chapters=48, seed=21)
    from app.core.blocks import iter_dialogue

    spoken: dict[str, set] = {}
    for cid, char_id, _text in iter_dialogue(project):
        spoken.setdefault(char_id, set()).add(cid)

    deaths = [it for it in gt["planted"] if it["kind"] == "death_then_speaks"]
    assert deaths
    for it in deaths:
        # 主语由埋点自己标注，不靠"哪个角色在这章说过话"去反推
        # （多埋点并存时那个推断会串台——之前就因此误报过）
        who = str(it["subject"])
        assert who, it
        est_i = int(str(it["establishedChapter"]).replace("ch", ""))
        con_i = int(str(it["conflictChapter"]).replace("ch", ""))
        assert who in spoken.get(str(it["conflictChapter"]), set()) or True
        for gap in range(est_i + 1, con_i):
            assert f"ch{gap}" not in spoken.get(who, set()), (
                f"{who} 在死亡后到冲突章之间仍有台词：ch{gap}"
            )
        assert f"ch{con_i}" in spoken.get(who, set()), "冲突章该角色必须真的出场"


def test_deterministic_detector_returns_scorable_shape():
    project, _ = build_synthetic_novel(chapters=30, seed=15)
    for d in detect_deterministic(project):
        assert d["category"] in {"character", "timeline", "location"}
        assert isinstance(d["chapterIds"], list)


# ---------------------------------------------------------------- 端到端报告


def test_run_benchmark_reports_both_plans_and_formats():
    report = run_benchmark(chapters=48, seed=16, detector=detect_deterministic)
    assert "exposure" in report and set(report["exposure"]) == {"legacy", "chunked"}
    assert report["exposure"]["legacy"]["exposureRecall"] < 1.0
    assert report["exposure"]["chunked"]["exposureRecall"] == 1.0
    assert "detection" in report
    text = format_report(report)
    assert "旧方案" in text and "分片方案" in text
    assert "precision" in text


def test_run_benchmark_without_detector_is_still_useful():
    report = run_benchmark(chapters=48, seed=17)
    assert "detection" not in report
    assert report["exposure"]["chunked"]["exposureRecall"] == 1.0
    assert "长程一致性基准" in format_report(report)


def test_bucket_boundaries_are_well_defined():
    assert bucket_of(1) == "1-3"
    assert bucket_of(3) == "1-3"
    assert bucket_of(4) == "4-8"
    assert bucket_of(15) == "9-15"
    assert bucket_of(16) == "16-30"
    assert bucket_of(999) == "31+"
    # 分桶必须无缝覆盖正整数，否则会有埋点掉进不存在的桶
    for d in range(1, 200):
        assert any(lo <= d <= hi for _n, lo, hi in DISTANCE_BUCKETS)


def test_empty_project_is_safe():
    project = normalize_project({"id": "p", "title": "空"})
    assert chunked_plan(project)
    assert legacy_plan(project)
    # 空作品也要能审（audit 不该崩）
    assert full_audit_draft("")["pass"] is True
