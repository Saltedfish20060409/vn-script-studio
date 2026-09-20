"""卷首「前情提要」：把已经写过的章节压成一段可读的回述。

为什么单独做：轻小说/网文**每卷开头都要回顾前情**，这是编辑流程里的固定动作，
而现有功能里没有——`chapter_revise` 是重写某一章，`novel_memory` 是给 AI 用的要点归档，
都不是"给读者看的一段回述"。

数据来源只挑**已经提炼过的东西**（章节摘要/记忆归档/未回收伏笔）+ 上一章结尾原文，
不把整本书塞进提示词——既省成本，也避免模型把细节编歪。

失败一律降级为 error 字符串。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.core.ai import DeepSeekConfig
from app.core.llm_http import chat_completions, content_from_response
from app.domain.types import VnProject

# 输入上限：控制成本，也避免"要回述的东西太多"导致模型开始编
_MAX_CHAPTERS = 60
_MAX_ARCHIVES = 8
_DIGEST_CAP = 220
_ARCHIVE_CAP = 420
_TAIL_CAP = 260
_TEXT_CAP = 2000

_SYSTEM = """你是中文小说编辑。作者要为自己的作品写一段「前情提要」（放在新一卷开头，给读者看）。

只根据下面给的材料写，不要新增任何没出现过的人物、事件或设定。

要求：
1. 300–500 字，第三人称，按时间顺序讲清主线推进与关键转折。
2. 只写已经发生的事，不猜测、不评价、不预告。
3. 人名、地名、专有名词**原样保留**，不要改写或替换。
4. 次要细节可以略过；但影响后续的转折（谁知道了什么、谁离开了、什么被夺走）要写。
5. 最后单独一行，以「尚未收回的线索：」开头列出未了结的伏笔（没有就写「尚未收回的线索：无」）。
6. 不要用「上回说到」「前情提要：」这类套话开头，直接进入事件；不要小标题、不要分点编号。

只输出这段前情提要本身。"""

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


@dataclass
class RecapResult:
    text: str = ""
    model: str = ""
    chapters_used: int = 0
    archives_used: int = 0
    included: List[str] = field(default_factory=list)
    error: Optional[str] = None


def _clip(text: str, cap: int) -> str:
    value = " ".join(str(text or "").split())
    return value[:cap]


def build_recap_messages(
    *,
    target_label: str,
    chapter_notes: List[Dict[str, str]],
    archive_notes: Optional[List[str]] = None,
    foreshadows: Optional[List[str]] = None,
    ending_tail: str = "",
) -> List[Dict[str, str]]:
    """拼提示词（纯函数，便于测试）。"""
    parts: List[str] = [f"【要回述的范围】{target_label or '（全书）'}"]

    if archive_notes:
        lines = [f"- {_clip(a, _ARCHIVE_CAP)}" for a in archive_notes[:_MAX_ARCHIVES] if str(a).strip()]
        if lines:
            parts.append("【此前归档的要点】\n" + "\n".join(lines))

    if chapter_notes:
        lines = []
        for note in chapter_notes[:_MAX_CHAPTERS]:
            title = _clip(note.get("title") or "", 40)
            body = _clip(note.get("summary") or "", _DIGEST_CAP)
            hook = _clip(note.get("closeHook") or "", 80)
            line = f"- {title}：{body}"
            if hook:
                line += f"（本章收束在：{hook}）"
            lines.append(line)
        if lines:
            parts.append("【逐章要点】\n" + "\n".join(lines))

    if foreshadows:
        lines = [f"- {_clip(f, 120)}" for f in foreshadows if str(f).strip()]
        if lines:
            parts.append("【台账里尚未回收的伏笔】\n" + "\n".join(lines[:20]))

    if ending_tail.strip():
        parts.append(f"【已写到的最后一段原文（供衔接语气，不要照抄）】\n…{_clip(ending_tail, _TAIL_CAP)}")

    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def clean_recap_text(raw: str) -> str:
    """清掉模型爱加的包装（代码围栏、开头的「前情提要：」标签）。"""
    text = _FENCE_RE.sub("", (raw or "").strip()).strip()
    text = re.sub(r"^\s*前情提要\s*[:：]\s*", "", text)
    return text[:_TEXT_CAP].strip()


def _foreshadow_lines(project: VnProject) -> List[str]:
    ledger = project.writingLedger or {}
    items = ledger.get("foreshadows") if isinstance(ledger, dict) else None
    out: List[str] = []
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        if item.get("resolved") or item.get("status") == "resolved":
            continue
        text = str(item.get("text") or item.get("note") or "").strip()
        if text:
            out.append(text)
    return out


def _ending_tail(project: VnProject, chapter_ids: List[str]) -> str:
    """回述范围里最后一章的结尾原文（用正文；没有正文就用最后一句话的块）。"""
    if not chapter_ids:
        return ""
    last_id = chapter_ids[-1]
    chapter = next((c for c in project.chapters or [] if c.id == last_id), None)
    if chapter is None:
        return ""
    prose = str(getattr(chapter, "prose", None) or "").strip()
    if prose:
        return prose[-_TAIL_CAP:]
    texts = [
        str(b.get("text") or "")
        for b in list(chapter.blocks or [])
        if (b or {}).get("type") in ("narration", "dialogue")
    ]
    return "".join(texts)[-_TAIL_CAP:]


async def run_recap(
    config: Optional[DeepSeekConfig],
    *,
    project: VnProject,
    chapter_ids: List[str],
    target_label: str,
    archives: Optional[List[str]] = None,
) -> RecapResult:
    """把指定章节压成一段前情提要。"""
    if config is None or not config.apiKey or "your-key" in config.apiKey:
        return RecapResult(error="未配置模型密钥：请在「设置 → 模型」填入自己的 Key，或使用站内免费档。")

    from app.core.chapter_digest import digest_all_chapters

    digests = {d.chapterId: d for d in digest_all_chapters(project)}
    chapter_notes: List[Dict[str, str]] = []
    for cid in chapter_ids[:_MAX_CHAPTERS]:
        chapter = next((c for c in project.chapters or [] if c.id == cid), None)
        digest = digests.get(cid)
        chapter_notes.append(
            {
                "title": (digest.title if digest else (chapter.title if chapter else cid)) or cid,
                "summary": (digest.beatSummary if digest else "") or "",
                "closeHook": (digest.closeHook if digest else "") or "",
            }
        )
    # 摘要为空时退化成章节梗概（作者手写的 synopsis 也是有效材料）
    for note, cid in zip(chapter_notes, chapter_ids[:_MAX_CHAPTERS]):
        if not note["summary"]:
            chapter = next((c for c in project.chapters or [] if c.id == cid), None)
            note["summary"] = str(getattr(chapter, "synopsis", None) or "") if chapter else ""

    if not any(n["summary"] for n in chapter_notes):
        return RecapResult(error="这些章节还没有摘要或梗概可依据：先写点内容，或给章节补一句梗概。")

    messages = build_recap_messages(
        target_label=target_label,
        chapter_notes=chapter_notes,
        archive_notes=list(archives or []),
        foreshadows=_foreshadow_lines(project),
        ending_tail=_ending_tail(project, chapter_ids),
    )
    try:
        res = await chat_completions(
            config,
            messages=messages,
            temperature=0.4,
            timeout=180,
        )
        content, used_model = content_from_response(res)
        text = clean_recap_text(content)
        if not text:
            return RecapResult(error="模型没有返回内容，请重试或换一个模型")
        return RecapResult(
            text=text,
            model=used_model or (config.model or ""),
            chapters_used=min(len(chapter_ids), _MAX_CHAPTERS),
            archives_used=len(list(archives or [])[:_MAX_ARCHIVES]),
            included=[
                f"章节×{min(len(chapter_ids), _MAX_CHAPTERS)}",
                f"归档×{len(list(archives or [])[:_MAX_ARCHIVES])}",
            ],
        )
    except Exception as exc:  # noqa: BLE001 — 生成失败不该影响其它功能
        return RecapResult(error=f"生成失败：{exc}")


def resolve_recap_targets(
    project: VnProject,
    *,
    volume_id: Optional[str],
    mode: str,
    up_to_chapter_id: Optional[str],
) -> tuple[List[str], str, Optional[str]]:
    """算出"要回述哪些章"，返回 (chapter_ids, 范围标签, 错误)。

    语义：
    - mode="volume" + volume_id：这一卷的章节（卷末回顾）
    - mode="before" + volume_id：这一卷**之前**的所有章节（卷首前情，最常用）
    - mode="before" 无 volume_id：写到 up_to_chapter_id 之前（缺省=全书），
      给不分卷的作品也能用（"写到现在的前情提要"）
    """
    chapters = list(project.chapters or [])
    volumes = list(project.volumes or [])

    if mode not in ("before", "volume"):
        return [], "", "mode 只能是 before 或 volume"

    if volume_id is not None and volume_id != "":
        volume = next((v for v in volumes if v.id == volume_id), None)
        if volume is None:
            return [], "", "这一卷不存在（可能已被删除）"
        ids = [c.id for c in chapters if (getattr(c, "volumeId", None) or "") == volume_id]
        if mode == "volume":
            if not ids:
                return [], "", f"「{volume.title}」还没有章节"
            return ids, f"「{volume.title}」全卷（{len(ids)} 章）", None
        first_index = chapters.index(next(c for c in chapters if c.id == ids[0])) if ids else len(chapters)
        before = [c.id for c in chapters[:first_index]]
        if not before:
            return [], "", f"「{volume.title}」是第一卷，前面还没有内容可以回顾"
        return before, f"「{volume.title}」之前的 {len(before)} 章", None

    if mode == "volume":
        return [], "", "按卷回顾需要指定 volume_id"

    if up_to_chapter_id:
        index = next((i for i, c in enumerate(chapters) if c.id == up_to_chapter_id), -1)
        if index < 0:
            return [], "", "指定的章节不存在"
        ids = [c.id for c in chapters[:index]]
        if not ids:
            return [], "", "这一章之前还没有内容可以回顾"
        return ids, f"写到「{chapters[index].title}」之前的 {len(ids)} 章", None

    if len(chapters) < 2:
        return [], "", "还没有足够的内容可以回顾（至少写完一章以上）"
    ids = [c.id for c in chapters[:-1]]
    return ids, f"写到当前最后一章之前的 {len(ids)} 章", None
