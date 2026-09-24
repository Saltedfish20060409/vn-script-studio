"""分片窗口的**暴露率**测量（纯计算，不调用模型）。

## 为什么需要它

依据 **"Distance between Relevant Information Pieces Causes Bias in Long-Context LLMs"**
（ACL 2025 Findings, https://aclanthology.org/2025.findings-acl.28/）：相关片段
**彼此之间的距离**本身就会让模型用不上它们——不只是片段在上下文里的绝对位置。

我们的分片扫描（`consistency_scan`）正是拿"窗口"来控制这件事的：跨章矛盾要能被发现，
两个相关章节必须**同时落进某一个窗口**。窗口太小 → 距离稍远的线索永远不同窗（构造上
不可能被发现）；窗口太大 → 每次调用更贵、也更靠近长上下文的失效区。所以窗口大小与重叠
不是手感问题，是**可测量的覆盖率问题**。

## 口径（与 `docs/longrange-consistency-and-eval.md` 的暴露率口径一致）

- **章暴露率**：有正文的章节里，至少落在一个窗口中的比例。分片方案的卖点就是它恒为 1。
- **对暴露率**：把"相距 d 章以内"的章对全部枚举，能在某一窗里同时出现的比例。
  按 d 分桶（1, 2, 3, …）分别给——因为论文说的正是"距离越远越难"，一张按距离展开的表
  才能看出窗口在哪一档开始跟不上。

这份测量**不产生任何模型调用**：它只算窗口规划的结果，所以可以在测试里跑、可以当实验跑，
结论用来选默认参数，而不是用来宣称"扫描质量更好"。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Tuple

from app.core.consistency_scan import plan_windows
from app.domain.types import VnProject

#: 对照实验默认试的窗口大小 / 重叠组合。
DEFAULT_GRID: Tuple[Tuple[int, int], ...] = (
    (4, 0),
    (4, 1),
    (6, 0),
    (6, 2),
    (8, 2),
    (8, 4),
    (12, 4),
)


def chapter_exposure(project: VnProject, *, size: int, overlap: int) -> Dict[str, Any]:
    """每个有正文的章节落进几个窗口。

    `min=0` 就意味着有章节根本没被任何窗口覆盖（旧审计的漏章问题），
    所以这个最小值本身就是一条不变量：分片方案下它必须 ≥ 1。
    """
    windows = plan_windows(project, size=size, overlap=overlap)
    counts: Dict[str, int] = {}
    order: List[str] = []
    for win in windows:
        for cid in win["chapterIds"]:
            if cid not in counts:
                counts[cid] = 0
                order.append(cid)
            counts[cid] += 1
    if not counts:
        return {"chapters": 0, "min": 0, "max": 0, "covered": 0, "coverage": 0.0, "windows": len(windows)}
    values = list(counts.values())
    covered = sum(1 for v in values if v > 0)
    return {
        "chapters": len(values),
        "min": min(values),
        "max": max(values),
        "covered": covered,
        "coverage": round(covered / len(values), 4),
        "windows": len(windows),
    }


def _same_window_pairs(windows: Sequence[Dict[str, Any]]) -> set:
    pairs = set()
    for win in windows:
        ids = list(win["chapterIds"])
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pairs.add((ids[i], ids[j]))
    return pairs


def pair_exposure(
    project: VnProject,
    *,
    size: int,
    overlap: int,
    max_distance: int = 6,
) -> Dict[str, Any]:
    """按"相距几章"分桶统计：这些章对里有多少能落进同一个窗口。

    距离按**章序差**算（相邻章 = 1），只用有正文的章节参与——中间的空章不会凭空
    增加距离，因为分片本来就是按"有正文的章节序列"切的。
    """
    windows = plan_windows(project, size=size, overlap=overlap)
    ids: List[str] = []
    seen = set()
    for win in windows:
        for cid in win["chapterIds"]:
            if cid not in seen:
                seen.add(cid)
                ids.append(cid)
    same = _same_window_pairs(windows)

    buckets: Dict[int, List[int]] = {}
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            distance = j - i
            if distance > max_distance:
                continue
            buckets.setdefault(distance, []).append(1 if (ids[i], ids[j]) in same else 0)
    per_distance = {
        str(d): {
            "pairs": len(flags),
            "exposed": sum(flags),
            "rate": round(sum(flags) / len(flags), 4) if flags else None,
        }
        for d, flags in sorted(buckets.items())
    }
    return {"size": size, "overlap": overlap, "windows": len(windows), "byDistance": per_distance}


def compare_settings(
    project: VnProject,
    settings: Iterable[Tuple[int, int]] = DEFAULT_GRID,
    *,
    max_distance: int = 6,
) -> List[Dict[str, Any]]:
    """把几组 (size, overlap) 并排算出来，供人选默认值（也供测试断言单调性）。"""
    rows: List[Dict[str, Any]] = []
    for size, overlap in settings:
        exposure = chapter_exposure(project, size=size, overlap=overlap)
        pairs = pair_exposure(project, size=size, overlap=overlap, max_distance=max_distance)
        # 相邻章（距离 1）的暴露率是最低要求：连它都保不住，方案就是坏的
        nearest = pairs["byDistance"].get("1", {}).get("rate")
        rows.append(
            {
                "size": size,
                "overlap": overlap,
                "windows": exposure["windows"],
                "chapterCoverage": exposure["coverage"],
                "minChapterWindows": exposure["min"],
                "neighbourPairRate": nearest,
                "byDistance": pairs["byDistance"],
            }
        )
    return rows


def worst_distance_covered(
    project: VnProject, *, size: int, overlap: int, max_distance: int = 12
) -> int:
    """在这组参数下，**所有**相距 d 章以内的章对都同窗的最大 d。0 = 连相邻章都保不住。

    这是给"默认窗口该多大"用的单一指标：它把一条按距离展开的曲线压成一个数，
    比"平均暴露率"更能说明"再远的线索就查不到了"。实测值恒等于 `overlap`（见测试里的推导）。
    """
    pairs = pair_exposure(project, size=size, overlap=overlap, max_distance=max_distance)
    best = 0
    for d in range(1, max_distance + 1):
        entry = pairs["byDistance"].get(str(d))
        if not entry or entry["rate"] != 1.0:
            break
        best = d
    return best


def coverage_under_cap(
    project: VnProject,
    *,
    size: int,
    overlap: int,
    max_windows: int | None,
) -> Dict[str, Any]:
    """**在窗口预算被用满的情况下**，这本书实际能覆盖到哪些章。

    为什么这个函数比 `chapter_exposure` 更接近现实：HTTP 路径默认带一个窗口上界
    （`HTTP_DEFAULT_MAX_WINDOWS = 16`），长书几乎一定被截断，于是"能扫多少章"由
    **窗口大小**决定，而不是由窗口数决定：

    - size=6 / overlap=2（窗口数不变的前提下）每个窗口前进 4 章 → 16 窗覆盖 6+15×4 = 66 章；
    - size=12 / overlap=4 每窗前进 8 章 → 16 窗覆盖 12+15×8 = 132 章，且同窗距离上限从 2 提到 4。

    也就是说：在预算受限的现实里，**放大窗口是"少漏章"的主要杠杆**，
    它同时改善了远距离章对的暴露率。代价是每窗文本更长（更靠近长上下文的失效区），
    所以不能无限放大——这也是为什么默认值取 12 而不是 20。
    """
    windows = plan_windows(project, size=size, overlap=overlap)
    total_chapters = len({cid for win in windows for cid in win["chapterIds"]})
    if max_windows is None:
        run = windows
    else:
        run = windows[: max(0, int(max_windows))]
    covered = {cid for win in run for cid in win["chapterIds"]}
    return {
        "size": size,
        "overlap": overlap,
        "windowsPlanned": len(windows),
        "windowsRun": len(run),
        "chaptersTotal": total_chapters,
        "chaptersCovered": len(covered),
        "coverage": round(len(covered) / total_chapters, 4) if total_chapters else 0.0,
        "distanceCovered": worst_distance_covered(project, size=size, overlap=overlap),
    }
