"""全书一致性扫描：分片窗口 + 跨窗合并。

为什么分片
----------
`consistency_audit` 把"全书扫描"压进一次请求里，靠两个常量硬切：只取前 14 章、
每章只留 1600 字。作品写到几十万字之后，这个审计实际只看得到开头几章，而且切法是
**静默**的——作者以为查了全书，其实后面几十章从未进入模型视野。这里把"一次全量"
换成"按章序切窗口、逐窗扫完、再跨窗合并"：窗口数随章节数线性增长，没有隐性上限；
预算截断与失败逐条报进 coverage，作者能看到"扫了多少章 / 共多少章"。

为什么重叠
----------
一致性冲突的形态本身就是跨章对照（第 3 章写的设定 vs 第 8 章的正文）。窗口首尾相接时，
恰好落在边界两侧的对照谁也看不见——这不是模型漏报，而是输入里根本没让这两章同时出现。
所以相邻窗口留重叠章（默认 6 章窗口重叠 2 章），让边界附近的章节总能在某个窗口里
与两侧邻居同时在场，边界才不会变成盲区。

为什么把"跨窗复发"当置信度
--------------------------
同一个冲突被两个窗口独立报出，说明它在两组不同的章节对照下都成立，比只在一个窗口里
出现一次的判断更值得先看，因此记 `foundInWindows`，并在 >= 2 时给 `confidence="high"`。
这里说的置信度不是概率，而是"独立证据条数"，只用来给结果排序，不做任何自动修改。

为什么限制并发、为什么逐窗容错
------------------------------
每个窗口的请求体都是一整块正文加全量权威设定，同时开太多会顶到上游的速率限制；
而 `llm_http` 的进程级并发闸是全站共享的，一次扫描不该把它占满，所以自留一个更小的上限。
单窗超时、上游报错、返回的 JSON 坏掉，都只记该窗的 error 并计入 `coverage.windowsFailed`：
一个窗口失败不该让作者连其余章节的结论也一起丢掉。同理，本模块任何路径都不抛异常。

与 `consistency_audit` 的关系
-----------------------------
system prompt、authority 结构、issue 解析与去重上限都直接复用该模块的私有实现，
保证"单窗口扫描"与旧的一次性扫描在提示词层面完全一致，两边结果可以对照着看。
唯一有意为之的差异是正文来源（见 `_chapter_source_text`）与不再有 14 章上限。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from app.core import llm_budget
from app.core.ai import DeepSeekConfig
from app.core.blocks import iter_project_blocks
from app.core.consistency_audit import (
    _CHAPTER_TEXT_CAP,
    _MAX_CHAPTER_TEXTS,
    _MAX_ISSUES,
    _SYSTEM_PROMPT,
    ConsistencyIssue,
    _build_authority,
    _parse_issues,
    _parse_json,
)
from app.core.llm_http import chat_completions, content_from_response
from app.domain.types import VnProject

from .agent_context import _blocks_to_plain

# 可注入的补全函数：收 messages，回模型输出的原始文本。测试注入假实现即可完全离线。
Completer = Callable[[List[Dict[str, str]]], Awaitable[str]]

# 窗口并发上限。每个窗口都要发"6 章正文 + 全量权威设定"，而上游按 token 速率限流；
# 4 路既能压住总时长，又不会顶到 llm_http 里那个全站共享的 16 路闸（一次扫描不该独占）。
_MAX_CONCURRENT_WINDOWS = 4

# 合并后的条数上限。每个窗口各自有 _MAX_ISSUES 上限，跨窗合并的结果天然可能更多，
# 但响应还要发给前端，仍得有个界：超出部分计数上报（issuesTruncated），不静默丢。
_MAX_MERGED_ISSUES = 60

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# 判重用的归一化：\W 覆盖中英文标点与空白（CJK 属于 \w，会被保留），下划线一并去掉。
_NON_WORD_RE = re.compile(r"[\W_]+")

_OUTPUT_SCHEMA: Dict[str, Any] = {
    "summary": "一句话总结本章段的一致性状况",
    "issues": [
        {
            "category": "character | timeline | location | bible | plot | style",
            "severity": "high | medium | low",
            "chapterIds": ["章节 id"],
            "quote": "原文证据",
            "description": "矛盾说明",
            "suggestion": "最小修改建议",
        }
    ],
}


# ------------------------------------------------------------------- 正文与窗口规划


def _chapter_source_text(ch: Any, project: VnProject) -> str:
    """一章的送审正文：优先 `prose`，没有正文才回落到 script blocks。

    与 `writing_stats.count_chapter_words` 同一约定。旧审计只读 blocks，于是"用大白话
    正文写作"（本作品的主写作面）的章节会被整章当成空章——那不是作者没写，是没被看见。
    """
    prose = str(getattr(ch, "prose", None) or "").strip()
    if prose:
        return prose
    blocks = list(getattr(ch, "blocks", None) or [])
    return str(_blocks_to_plain(blocks, project.characters) or "").strip()


def _corpus(
    project: VnProject,
    *,
    chapter_texts: Optional[Dict[str, str]] = None,
    chapter_text_cap: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """有正文的章节序列（按章序），正文按上限截断。

    - `chapter_texts`（id → 正文）给的是服务端更新鲜的文本时优先使用；某章不在其中时
      回落到项目自身的正文，而不是把这一章跳过（旧审计会在这种情形下漏章）。
    - `chapter_text_cap` 为 None 时沿用旧审计的每章上限；<= 0 表示不截断。
    """
    if chapter_text_cap is None:
        limit = _CHAPTER_TEXT_CAP
    else:
        limit = int(chapter_text_cap)
    out: List[Dict[str, Any]] = []
    for ordinal, ch in enumerate(list(project.chapters or []), start=1):
        cid = str(getattr(ch, "id", "") or "")
        text = ""
        if chapter_texts:
            text = str(chapter_texts.get(cid) or "").strip()
        if not text:
            text = _chapter_source_text(ch, project)
        if not text:
            continue
        clipped = text if limit <= 0 else text[:limit]
        out.append(
            {
                "id": cid,
                "title": str(getattr(ch, "title", "") or ""),
                "ordinal": ordinal,
                "fullChars": len(text),
                "text": clipped,
            }
        )
    return out


def _plan_windows(
    entries: Sequence[Dict[str, Any]], *, size: int, overlap: int
) -> List[Dict[str, Any]]:
    """把章节序列切成互相重叠的窗口。

    步长取 size - overlap（保证相邻窗口无缝、无空洞），最后一个窗口从"能覆盖到末尾"
    的位置起算，所以任何 entry 都至少落在一个窗口里。
    """
    total = len(entries)
    if total <= 0:
        return []
    size = max(1, min(int(size), total))
    overlap = max(0, min(int(overlap), size - 1))
    stride = max(1, size - overlap)

    windows: List[Dict[str, Any]] = []
    start = 0
    while True:
        chunk = entries[start : start + size]
        windows.append(
            {
                "index": len(windows),
                "chapterIds": [str(e["id"]) for e in chunk],
                "chapterTitles": [str(e["title"]) for e in chunk],
                "chars": sum(int(e["fullChars"]) for e in chunk),
            }
        )
        if start + size >= total:
            break
        start += stride
    return windows


#: 分片窗口的**唯一真源**。
#:
#: 为什么单独抽成常量：默认值一度散在三处（这里、HTTP 路由签名、评测基准
#: `eval_longrange`），把默认值从 6/2 调到 12/4 时基准没跟上，"基准必须测线上真正跑的
#: 那套切窗逻辑"那条测试立刻红了——那正是分叉的代价。现在：
#: - 生产实现、HTTP 路由、评测基准都取这里；
#: - 前端 `src/api/projects.ts` 的 `CONSISTENCY_SCAN_DEFAULTS` 由
#:   `src/api/scanDefaults.test.ts` 读本文件比对，不会各自漂移。
#:
#: 数值本身是**测出来的**（`app/core/scan_exposure.py`，依据 ACL 2025 Findings 那篇
#: "相关片段之间的距离造成偏差"）：同窗距离上限恒等于 overlap，窗口预算（16）在长书上
#: 必被用满，所以窗口大小才是"能扫多少章"的杠杆（6/2 → 66 章；12/4 → 132 章，
#: 距离上限 2 → 4）。每窗文本更长是它的代价，所以取 12 而不是更大。
DEFAULT_WINDOW_SIZE = 12
DEFAULT_WINDOW_OVERLAP = 4


def plan_windows(
    project: VnProject,
    *,
    size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_WINDOW_OVERLAP,
) -> List[Dict[str, Any]]:
    """按章序把有正文的章节切成重叠窗口。

    默认值见 `DEFAULT_WINDOW_SIZE` / `DEFAULT_WINDOW_OVERLAP` 上方的说明。

    返回每窗的 `{"index", "chapterIds", "chapterTitles", "chars"}`；`chars` 是该窗
    章节的原文总字数（未计每章截断）。总章数 <= size 时只有一窗，此时行为与旧的
    一次性扫描等价。章节数多时每个有正文的章节都至少落在一窗里——这正是"不再漏章"。
    """
    return _plan_windows(_corpus(project), size=size, overlap=overlap)


def _apply_budget(
    windows: Sequence[Dict[str, Any]], max_windows: Optional[int]
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """按预算截断窗口，返回 (执行, 被砍掉)。max_windows 为 None 表示不设预算。

    注意：HTTP 入口**不会**传 None（见 `HTTP_DEFAULT_MAX_WINDOWS`），
    None 只留给离线/CLI 这类没有"请求超时"概念的调用方。
    """
    if max_windows is None:
        return list(windows), []
    limit = max(0, int(max_windows))
    return list(windows[:limit]), list(windows[limit:])


#: HTTP 入口在调用方没指定 `max_windows` 时使用的默认窗口上界。
#:
#: 为什么要有这个默认上界：窗口是并发发出的（`asyncio.gather`），但进程内只有
#: `llm_http._LLM_SEMAPHORE` 那 16 个并发额度，窗口数超过它就要排队，**墙钟时间成倍增长**；
#: 而 HTTP 调用方自带超时预算（前端 `TIMEOUTS.long` = 600s），等不到结果就等于
#: 白扫一遍、还照付 token 与配额。16 = 恰好一批。
#: 要扫更多就显式传 `max_windows`（接受更长等待），或用离线入口（CLI/eval）。
HTTP_DEFAULT_MAX_WINDOWS = 16


# ------------------------------------------------------------------------- 请求组装


def _build_window_messages(
    project: VnProject,
    window: Dict[str, Any],
    corpus_by_id: Dict[str, Dict[str, Any]],
    focus: str,
) -> List[Dict[str, str]]:
    """一个窗口的请求体：与旧审计同 prompt、同 authority，只有 chapters 换成该窗章节。"""
    authority = _build_authority(project)
    chapter_ids = [str(c) for c in window.get("chapterIds") or []]
    chapters = [
        {
            "id": cid,
            "title": str(corpus_by_id[cid]["title"]),
            "text": str(corpus_by_id[cid]["text"]),
        }
        for cid in chapter_ids
        if cid in corpus_by_id
    ]
    ordinals = [int(corpus_by_id[cid]["ordinal"]) for cid in chapter_ids if cid in corpus_by_id]
    first = min(ordinals) if ordinals else 0
    last = max(ordinals) if ordinals else 0

    user: Dict[str, Any] = {
        "authority": authority,
        "chapters": chapters,
        "focus": (focus or "").strip()[:300],
        # 让模型知道自己在看"全书的第几段"，否则它会把"窗外的事没提到"也当成冲突。
        "scope": (
            f"这是全书分段扫描中的第 {int(window.get('index') or 0) + 1} 段"
            f"（覆盖全书第 {first}-{last} 章）。只报告这些章节之间、以及这些章节与"
            "权威设定之间的冲突；未给出的章节不要臆测。"
        ),
        "output_schema": _OUTPUT_SCHEMA,
    }
    return [
        {"role": "system", "content": _SYSTEM_PROMPT.format(max_issues=_MAX_ISSUES)},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _http_completer(config: DeepSeekConfig, used_model: Dict[str, str]) -> Completer:
    """默认补全实现：与 `consistency_audit` 完全相同的调用形状（温度 0.2 + JSON 模式）。"""

    async def _call(messages: List[Dict[str, str]]) -> str:
        res = await chat_completions(
            config,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=llm_budget.WRITE,
        )
        content, model = content_from_response(res)
        used_model["model"] = model or (config.model or "")
        return content

    return _call


def _window_error(index: int, window: Dict[str, Any], message: str) -> Dict[str, Any]:
    return {
        "index": index,
        "chapterIds": [str(c) for c in window.get("chapterIds") or []],
        "issues": [],
        "rawIssueCount": 0,
        "summary": "",
        "error": message,
    }


async def _scan_one_window(
    window: Dict[str, Any],
    *,
    project: VnProject,
    focus: str,
    completer: Completer,
    sem: asyncio.Semaphore,
    corpus_by_id: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """扫一个窗口。任何异常都变成该窗的 error 字段，绝不向外抛。"""
    index = int(window.get("index") or 0)
    try:
        messages = _build_window_messages(project, window, corpus_by_id, focus)
    except Exception as exc:  # noqa: BLE001 — 组装失败也只是这一窗没结果
        return _window_error(index, window, f"第 {index + 1} 段请求组装失败：{exc}")
    async with sem:
        try:
            content = await completer(messages)
            data = _parse_json(content)
            raw_issues = data.get("issues")
            # 记下模型原样报了几条：_parse_issues 自身有每窗上限（复用旧审计的
            # _MAX_ISSUES），不加这一笔，被上限吃掉的部分就是新的静默截断。
            raw_count = len(raw_issues) if isinstance(raw_issues, list) else 0
            return {
                "index": index,
                "chapterIds": [str(c) for c in window.get("chapterIds") or []],
                "issues": _parse_issues(data),
                "rawIssueCount": raw_count,
                "summary": str(data.get("summary") or "").strip()[:400],
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 — 单窗失败不影响其它窗口
            return _window_error(index, window, f"第 {index + 1} 段扫描失败：{exc}")


# --------------------------------------------------------------------------- 合并


def _norm(text: Any) -> str:
    """去空白与标点、统一大小写。只用于判重，不改变展示给作者的原文。"""
    return _NON_WORD_RE.sub("", str(text or "")).casefold()


def _issue_key(issue: ConsistencyIssue) -> tuple:
    quote, desc = _norm(issue.quote), _norm(issue.description)
    if not quote and not desc:  # 两边都归一化成空时退回原文，避免把不同问题并成一条
        quote, desc = str(issue.quote), str(issue.description)
    return (issue.category, quote, desc)


def _as_issue(item: Any) -> Optional[ConsistencyIssue]:
    """接受 ConsistencyIssue 或等形 dict（后者方便调用方手搓合并输入）。"""
    if isinstance(item, ConsistencyIssue):
        return item
    if not isinstance(item, dict):
        return None
    ids = [str(c) for c in (item.get("chapterIds") or []) if str(c).strip()]
    return ConsistencyIssue(
        category=str(item.get("category") or "plot"),
        severity=str(item.get("severity") or "medium"),
        chapterIds=ids,
        quote=str(item.get("quote") or ""),
        description=str(item.get("description") or ""),
        suggestion=str(item.get("suggestion") or ""),
    )


def _max_severity(a: str, b: str) -> str:
    return a if _SEVERITY_ORDER.get(a, 1) <= _SEVERITY_ORDER.get(b, 1) else b


def merge_window_results(window_results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """跨窗合并去重，并把"被几个窗口独立报出"记成置信度。

    去重键是 (category, 归一化 quote, 归一化 description)：同一处冲突在不同窗口里
    往往只差标点或空格，不归一化就会被算成两条。合并后 chapterIds 取并集、
    severity 取最高、foundInWindows 记窗口数（同一窗口内重复只算一次）。
    排序仍是 severity 优先（与旧审计一致），同severity 时跨窗复发多的排在前面。
    """
    merged: Dict[tuple, Dict[str, Any]] = {}
    order: List[tuple] = []
    summaries: List[str] = []
    reported = 0

    for pos, raw in enumerate(list(window_results or [])):
        if not isinstance(raw, dict) or raw.get("error"):
            continue
        reported += 1
        widx = raw.get("index", pos)
        summary = str(raw.get("summary") or "").strip()
        if summary and summary not in summaries:
            summaries.append(summary)
        for item in raw.get("issues") or []:
            issue = _as_issue(item)
            if issue is None:
                continue
            key = _issue_key(issue)
            bucket = merged.get(key)
            if bucket is None:
                bucket = {
                    "category": issue.category,
                    "severity": issue.severity,
                    "chapterIds": list(issue.chapterIds),
                    "quote": issue.quote,
                    "description": issue.description,
                    "suggestion": issue.suggestion,
                    "windows": [],
                }
                merged[key] = bucket
                order.append(key)
            else:
                bucket["severity"] = _max_severity(bucket["severity"], issue.severity)
                for cid in issue.chapterIds:
                    if cid not in bucket["chapterIds"]:
                        bucket["chapterIds"].append(cid)
                if not bucket["suggestion"]:
                    bucket["suggestion"] = issue.suggestion
            if widx not in bucket["windows"]:
                bucket["windows"].append(widx)

    issues: List[Dict[str, Any]] = []
    for key in order:
        b = merged[key]
        found = len(b["windows"])
        issues.append(
            {
                "category": b["category"],
                "severity": b["severity"],
                "chapterIds": b["chapterIds"],
                "quote": b["quote"],
                "description": b["description"],
                "suggestion": b["suggestion"],
                "foundInWindows": found,
                # 跨窗复发 = 多组章节对照下都成立，比单窗出现更值得先看。
                "confidence": "high" if found >= 2 else "medium",
                "windowIndexes": b["windows"],
            }
        )
    issues.sort(
        key=lambda i: (
            _SEVERITY_ORDER.get(i["severity"], 1),
            -int(i["foundInWindows"]),
            str(i["category"]),
        )
    )
    truncated = max(0, len(issues) - _MAX_MERGED_ISSUES)
    return {
        "issues": issues[:_MAX_MERGED_ISSUES],
        "summary": " ".join(summaries)[:400],
        "windowsReported": reported,
        "issuesTruncated": truncated,
    }


# --------------------------------------------------------------------------- 报告


def _ceiling_note(
    coverage: Dict[str, Any], chapter_text_cap: int, dropped_by_cap: int = 0
) -> str:
    """给作者看的一句话：旧实现截断在哪，本次实际扫到哪。"""
    total = int(coverage["chaptersWithText"])
    scanned = int(coverage["chaptersScanned"])
    pct = f"（{float(coverage['coverageRatio']) * 100:.0f}%）" if total else ""
    parts = [
        f"旧实现只扫前 {_MAX_CHAPTER_TEXTS} 章 × 每章 {_CHAPTER_TEXT_CAP} 字，且不告知；",
        f"本次分 {coverage['windowsRun']} 个窗口扫了 {scanned}/{total} 章{pct}。",
    ]
    if coverage["windowsFailed"]:
        parts.append(f"其中 {coverage['windowsFailed']} 个窗口失败，那些章节本轮没有结论。")
    if coverage["maxWindowsHit"]:
        parts.append(f"受 max_windows 预算限制，仍有 {len(coverage['truncatedChapters'])} 章未扫。")
    trimmed = len(coverage["textTruncatedChapters"])
    if trimmed:
        parts.append(f"另有 {trimmed} 章正文超过每章 {chapter_text_cap} 字上限，截断后送审。")
    if dropped_by_cap:
        parts.append(f"另有 {dropped_by_cap} 条冲突超出单窗 {_MAX_ISSUES} 条上限，未纳入合并。")
    return "".join(parts)


def _chapter_ids_with_blocks(project: VnProject) -> set:
    """有 block 的章节 id：用来区分"这章没写"和"这章写了但没产出可送审文本"。"""
    return {cid for cid, _b in iter_project_blocks(project) if cid}


# ------------------------------------------------------------------------ 主入口


async def run_consistency_scan(
    config: Optional[DeepSeekConfig],
    project: VnProject,
    *,
    size: int = DEFAULT_WINDOW_SIZE,
    overlap: int = DEFAULT_WINDOW_OVERLAP,
    focus: str = "",
    max_windows: Optional[int] = None,
    chapter_texts: Optional[Dict[str, str]] = None,
    completer: Optional[Completer] = None,
    chapter_text_cap: Optional[int] = None,
) -> Dict[str, Any]:
    """分片扫完全部有正文的章节，再跨窗合并。

    - `completer`（async (messages) -> 原始输出文本）用于测试注入；None 时走真实
      `chat_completions`，调用形状与旧审计一致。
    - `max_windows` 是显式的预算上限（None = 不限）。真被用上时 `maxWindowsHit=True`，
      没扫到的章节列进 `truncatedChapters`——预算可以砍，但不许悄悄砍。
    - 任何失败都体现为 `error` / `windowErrors` / `coverage.windowsFailed`，不抛异常。
    """
    chapters = list(project.chapters or [])
    entries = _corpus(
        project, chapter_texts=chapter_texts, chapter_text_cap=chapter_text_cap
    )
    cap = _CHAPTER_TEXT_CAP if chapter_text_cap is None else int(chapter_text_cap)
    corpus_by_id = {str(e["id"]): e for e in entries}
    all_ids = [str(e["id"]) for e in entries]
    text_ids = set(all_ids)
    trimmed = [str(e["id"]) for e in entries if int(e["fullChars"]) > len(str(e["text"]))]

    planned = _plan_windows(entries, size=size, overlap=overlap)
    kept, dropped = _apply_budget(planned, max_windows)
    # 被单窗 _MAX_ISSUES 上限吃掉的条数（扫描结束后才填），必须报到报告里。
    cap_drops = {"n": 0}

    def _payload(
        *,
        error: Optional[str],
        summary: str,
        issues: List[Dict[str, Any]],
        model: str,
        window_errors: List[Dict[str, Any]],
        windows: List[Dict[str, Any]],
        scanned_ids: set,
        run_count: int,
        failed: int,
        issues_truncated: int = 0,
    ) -> Dict[str, Any]:
        coverage: Dict[str, Any] = {
            "chaptersTotal": len(chapters),
            "chaptersWithText": len(entries),
            "chaptersScanned": len(scanned_ids),
            "coverageRatio": (
                round(len(scanned_ids) / len(entries), 4) if entries else 0.0
            ),
            "windowsPlanned": len(planned),
            "windowsRun": run_count,
            "windowsFailed": failed,
            # 没有被任何"成功窗口"覆盖的章节：预算砍掉的、窗口失败的、以及整体没跑的。
            "truncatedChapters": [cid for cid in all_ids if cid not in scanned_ids],
            "maxWindowsHit": bool(dropped),
            # 以下两项是额外的如实补充：每章截断、以及有块但没产出文本的章节。
            "textTruncatedChapters": trimmed,
            "chaptersWithBlocksButNoText": len(_chapter_ids_with_blocks(project) - text_ids),
        }
        return {
            "issues": issues,
            "summary": summary,
            "model": model,
            "error": error,
            "coverage": coverage,
            "ceilingNote": _ceiling_note(coverage, cap, cap_drops["n"]),
            "windowErrors": window_errors,
            "windows": windows,
            "issuesTruncated": issues_truncated,
            "issuesDroppedByWindowCap": cap_drops["n"],
        }

    if not chapters:
        return _payload(
            error=None,
            summary="作品还没有章节。",
            issues=[],
            model="",
            window_errors=[],
            windows=[],
            scanned_ids=set(),
            run_count=0,
            failed=0,
        )

    if config is None or not config.apiKey or "your-key" in config.apiKey:
        return _payload(
            error="未配置 DEEPSEEK_API_KEY，已跳过一致性扫描",
            summary="",
            issues=[],
            model="",
            window_errors=[],
            windows=[],
            scanned_ids=set(),
            run_count=0,
            failed=0,
        )

    if not entries:
        return _payload(
            error=None,
            summary="作品还没有可扫描的正文（章节既没有 prose 正文，也没有脚本 block）。",
            issues=[],
            model="",
            window_errors=[],
            windows=[],
            scanned_ids=set(),
            run_count=0,
            failed=0,
        )

    if not kept:
        return _payload(
            error=None,
            summary="本轮扫描预算为 0（max_windows），没有扫描任何章节。",
            issues=[],
            model="",
            window_errors=[],
            windows=[],
            scanned_ids=set(),
            run_count=0,
            failed=0,
        )

    used_model: Dict[str, str] = {}
    call = completer if completer is not None else _http_completer(config, used_model)
    sem = asyncio.Semaphore(_MAX_CONCURRENT_WINDOWS)
    tasks = [
        _scan_one_window(
            w,
            project=project,
            focus=focus,
            completer=call,
            sem=sem,
            corpus_by_id=corpus_by_id,
        )
        for w in kept
    ]
    # return_exceptions=True 是第二道保险：_scan_one_window 已自行兜住异常，
    # 万一还有漏网的（连结果字典都没造出来），也不能让整轮扫描炸掉。
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    reports: List[Dict[str, Any]] = []
    for window, res in zip(kept, raw_results):
        if isinstance(res, BaseException):
            reports.append(
                _window_error(
                    int(window.get("index") or 0), window, f"扫描异常：{res}"
                )
            )
        else:
            reports.append(res)

    scanned_ids: set = set()
    for rep in reports:
        if not rep.get("error"):
            scanned_ids.update(str(c) for c in rep.get("chapterIds") or [])
    window_errors = [
        {
            "index": int(rep.get("index") or 0),
            "chapterIds": list(rep.get("chapterIds") or []),
            "error": str(rep.get("error")),
        }
        for rep in reports
        if rep.get("error")
    ]
    failed = len(window_errors)
    cap_drops["n"] = sum(
        max(0, int(rep.get("rawIssueCount") or 0) - len(rep.get("issues") or []))
        for rep in reports
    )

    merged = merge_window_results(reports)
    error: Optional[str] = None
    if failed and failed == len(reports):
        error = f"全部 {len(reports)} 个窗口都失败了，本轮没有可用结论。"

    windows_out = [
        {
            "index": int(rep.get("index") or 0),
            "chapterIds": list(rep.get("chapterIds") or []),
            "reported": not rep.get("error"),
            "issueCount": len(rep.get("issues") or []),
            "rawIssueCount": int(rep.get("rawIssueCount") or 0),
            "summary": str(rep.get("summary") or ""),
            "error": rep.get("error"),
        }
        for rep in reports
    ]

    return _payload(
        error=error,
        summary=str(merged["summary"]),
        issues=list(merged["issues"]),
        model=used_model.get("model", "") or (getattr(config, "model", "") or ""),
        window_errors=window_errors,
        windows=windows_out,
        scanned_ids=scanned_ids,
        run_count=len(reports),
        failed=failed,
        issues_truncated=int(merged["issuesTruncated"]),
    )
