"""Project-scoped tools for the multi-step editor agent loop.

No shell / filesystem — only in-memory VnProject data.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.core.agent_context import chapter_plain
from app.core.character_voice.corpus import format_corpus_for_prompt
from app.core.harness.audit_full import full_audit_draft
from app.core.pipeline.ledger import format_ledger_for_agent, get_ledger
from app.domain.types import Character, VnProject

TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "get_chapter",
        "description": "读取一章或多章正文（可截断）。不传 chapterRef 则用当前焦点章；"
        "传 chapterRefs（逗号分隔多个 id/标题）可一次读多章做跨章对照。"
        "正文与脚本块都读得到（正文优先）。",
        "parameters": {
            "chapterRef": "章节 id 或标题，可选",
            "chapterRefs": "多个章节 id/标题，逗号分隔，可选（与 chapterRef 二选一）",
            "maxChars": "每章最大字符，默认 12000（读到一半发现不够可再调大）",
        },
    },
    {
        "name": "search_script",
        "description": "在各章正文中按关键词检索命中片段。",
        "parameters": {
            "query": "关键词或短语，必填",
            "limit": "最多命中条数，默认 8",
        },
    },
    {
        "name": "list_characters",
        "description": "列出角色 id / 显示名 / defineName 一览。",
        "parameters": {},
    },
    {
        "name": "get_character",
        "description": "读取角色卡与口吻语料摘要。",
        "parameters": {
            "ref": "角色 id、defineName 或显示名",
        },
    },
    {
        "name": "get_bible",
        "description": "读取故事设定（bible）字段摘要。",
        "parameters": {
            "section": "可选 world/background/outline/themes/notes；空=全量摘要",
        },
    },
    {
        "name": "search_bible",
        "description": "在设定文本中检索关键词。",
        "parameters": {"query": "关键词，必填"},
    },
    {
        "name": "get_locations",
        "description": "列出地点与关系链接摘要。",
        "parameters": {"query": "可选过滤词"},
    },
    {
        "name": "search_lore",
        "description": "在「设定条目」里按关键词检索并取回正文。开场上下文只会自动带上相关的那几条，"
        "没带上的条目你要用这个工具自己取；query 留空则返回全部条目标题索引。",
        "parameters": {
            "query": "关键词、名字或说法（留空 = 列出所有条目标题）",
            "limit": "最多取几条正文，默认 4",
        },
    },
    {
        "name": "get_lore_entry",
        "description": "按标题/别名/id 精确取一条设定条目的完整正文（已知条目叫什么时用它）。",
        "parameters": {"ref": "条目标题、别名或 id"},
    },
    {
        "name": "lint_draft",
        "description": "对候选正文或当前章跑叙事/AI 腔体检，返回问题列表。",
        "parameters": {
            "text": "要检查的正文；空则检查当前章",
            "chapterRef": "当 text 为空时指定章节",
        },
    },
    {
        "name": "ledger_digest",
        "description": "读取写作账本（事实/角色状态/伏笔）摘要。",
        "parameters": {},
    },
    {
        "name": "polish_prose",
        "description": (
            "让责编对一段正文做**最小改动**润色：先跑确定性体检，再按体检问题改写；"
            "体检全过时不调用模型（省 token）。返回改写后的正文与仍须注意的点——"
            "**由你判断要不要采纳**，不要把工具结果原样回显给作者。"
        ),
        "parameters": {
            "text": "要润色的正文；不传则取当前章",
            "chapterRef": "text 为空时用来指定章节（id 或标题）",
            "flavor": "prose / vn / auto；默认 auto（按稿子里有无剧本标记判断）",
        },
    },
    {
        "name": "novel_audit",
        "description": (
            "稿件体检（**不调用模型**，纯文本统计，随时可跑）："
            "consistency = 表记/引号配对/省略号/人名变体/视角偏移/称呼漂移；"
            "craft = 注音写法、拟声与感叹密度、章末钩子分数、对白占比与长段落。"
            "返回的是**线索**（带「第几章第几行 + 原样片段」），语义判断仍要你自己做，"
            "不要把线索当成结论回显给作者。"
        ),
        "parameters": {
            "scope": "consistency / craft / all，默认 all",
            "chapterRef": "只体检这一章（craft 支持；consistency 请改用 focus）",
            "focus": "只检查章标题或 id 含该子串的章节（可选）",
        },
    },
]

#: 需要调用模型的工具：必须是协程，不能走同步的 run_agent_tool。
#: agent_loop 见到这些名字会改走 run_agent_tool_async（见 app/core/agent_loop.py）。
ASYNC_TOOL_NAMES = frozenset({"polish_prose"})


def tool_catalog_for_prompt() -> str:
    lines = ["可用工具（仅项目数据；禁止声称使用 shell/文件系统）："]
    for t in TOOL_SPECS:
        params = t.get("parameters") or {}
        pbits = ", ".join(f"{k}" for k in params) if params else "（无参）"
        lines.append(f"- {t['name']}({pbits}): {t['description']}")
    return "\n".join(lines)


def _find_chapter(project: VnProject, ref: Optional[str], default_id: Optional[str] = None):
    chapters = list(project.chapters or [])
    if not chapters:
        return None
    key = (ref or default_id or "").strip()
    if not key:
        return chapters[0]
    for ch in chapters:
        if ch.id == key or (ch.title or "") == key:
            return ch
    low = key.lower()
    for ch in chapters:
        if low in (ch.title or "").lower() or low in ch.id.lower():
            return ch
    return None


def _find_character(project: VnProject, ref: str) -> Optional[Character]:
    key = (ref or "").strip()
    if not key:
        return None
    for c in project.characters or []:
        if c.id == key or c.defineName == key or c.displayName == key:
            return c
    low = key.lower()
    for c in project.characters or []:
        if (
            low in (c.displayName or "").lower()
            or low in (c.defineName or "").lower()
            or low in c.id.lower()
        ):
            return c
    return None


def _clip(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 12] + "\n…(截断)"


def _entry_keywords_of(entry: Any) -> List[str]:
    raw = getattr(entry, "keywords", None)
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(k).strip() for k in raw if str(k).strip()]


def _find_lore_entry(project: VnProject, ref: str) -> Optional[Any]:
    """按标题 / 别名 / id 找一条设定条目（精确优先，其次包含）。"""
    key = (ref or "").strip()
    if not key:
        return None
    entries = [e for e in (getattr(project, "loreEntries", None) or []) if e]
    for e in entries:
        if str(getattr(e, "id", "")) == key:
            return e
    low = key.lower()
    for e in entries:
        if str(getattr(e, "title", "") or "").strip().lower() == low:
            return e
    for e in entries:
        if low in [k.lower() for k in _entry_keywords_of(e)]:
            return e
    for e in entries:
        if low in str(getattr(e, "title", "") or "").lower():
            return e
    return None


def _bible_blob(project: VnProject) -> Dict[str, str]:
    b = project.bible
    if not b:
        return {}
    data = b.model_dump(mode="json") if hasattr(b, "model_dump") else dict(b)  # type: ignore[arg-type]
    out: Dict[str, str] = {}
    for k in ("world", "background", "outline", "themes", "notes"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
        elif isinstance(v, list):
            out[k] = "；".join(str(x) for x in v if x)
    return out


def run_agent_tool(
    name: str,
    arguments: Optional[Dict[str, Any]],
    *,
    project: VnProject,
    chapter_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Execute one tool. Returns (ok, preview_text)."""
    args = arguments if isinstance(arguments, dict) else {}
    try:
        if name == "get_chapter":
            # 默认上限从 4000 提到 12000：这个工具是"模型发现上下文里缺材料"时的
            # 唯一补救手段，4000 字符连一章的中等长度都读不完——补不回来的检索
            # 等于没有检索（上下文预算放大后更是如此）。
            max_c = int(args.get("maxChars") or 12000)
            refs = [
                r.strip()
                for r in str(args.get("chapterRefs") or "").split(",")
                if r.strip()
            ]
            if refs:
                # 多章模式：逐章读取，带标题分隔；缺省章容错。
                parts = []
                missing = []
                for ref in refs:
                    ch = _find_chapter(project, ref, chapter_id)
                    if not ch:
                        missing.append(ref)
                        continue
                    plain = chapter_plain(ch, project.characters)
                    parts.append(f"### {ch.title or ch.id}\n{_clip(plain, max_c)}")
                if missing:
                    parts.append(f"（未找到章节：{', '.join(missing)}）")
                if not parts:
                    return False, "未找到任何指定章节"
                return True, "\n\n".join(parts)
            ch = _find_chapter(project, args.get("chapterRef"), chapter_id)
            if not ch:
                return False, "未找到章节"
            plain = chapter_plain(ch, project.characters)
            return True, f"#{ch.title or ch.id}\n{_clip(plain, max_c)}"

        if name == "search_script":
            q = str(args.get("query") or "").strip()
            if not q:
                return False, "query 必填"
            limit = max(1, min(20, int(args.get("limit") or 8)))
            from app.core.retrieval import rank_texts

            candidates = [
                (
                    ch.title or ch.id,
                    chapter_plain(ch, project.characters),
                )
                for ch in project.chapters or []
            ]
            hits = rank_texts(q, candidates, limit=limit, min_score=0.5)
            if not hits:
                return True, f"无命中：{q}"
            return True, "\n".join(f"[{label}] …{snippet}…" for label, snippet, _ in hits)

        if name == "list_characters":
            rows = [
                f"- {c.displayName}（{c.defineName}） id={c.id}"
                for c in (project.characters or [])
            ]
            return True, "\n".join(rows) if rows else "（无角色）"

        if name == "get_character":
            ref = str(args.get("ref") or args.get("id") or "").strip()
            c = _find_character(project, ref)
            if not c:
                return False, f"未找到角色：{ref}"
            corpus = format_corpus_for_prompt(c, max_samples=4, max_chars=800)
            parts = [
                f"{c.displayName}（{c.defineName}） id={c.id}",
                f"语气：{c.voice or '（空）'}",
                f"简介：{c.bio or '（空）'}",
                f"关系：{c.relationships or '（空）'}",
                corpus or "",
            ]
            return True, "\n".join(p for p in parts if p)

        if name == "get_bible":
            blob = _bible_blob(project)
            if not blob:
                return True, "（设定为空）"
            section = str(args.get("section") or "").strip()
            if section and section in blob:
                return True, f"[{section}]\n{_clip(blob[section], 4000)}"
            parts = [f"[{k}]\n{_clip(v, 1200)}" for k, v in blob.items()]
            return True, "\n\n".join(parts)

        if name == "search_bible":
            q = str(args.get("query") or "").strip()
            if not q:
                return False, "query 必填"
            from app.core.retrieval import rank_texts

            blob = _bible_blob(project)
            hits = rank_texts(q, list(blob.items()), limit=8, min_score=0.4)
            if not hits:
                return True, f"设定中无命中：{q}"
            return True, "\n".join(f"[{k}] …{snippet}…" for k, snippet, _ in hits)

        if name == "get_locations":
            q = str(args.get("query") or "").strip().lower()
            locs = list(project.locations or [])
            lines = []
            for loc in locs:
                name_l = loc.name or loc.id
                desc = (loc.description or "").strip()
                row = f"- {name_l}: {desc}" if desc else f"- {name_l}"
                if q and q not in row.lower():
                    continue
                lines.append(_clip(row, 200))
            links = list(project.locationLinks or [])
            if links:
                lines.append("链接：")
                for lk in links[:30]:
                    lines.append(
                        f"  · {getattr(lk, 'fromId', '')} → {getattr(lk, 'toId', '')}"
                        f" {getattr(lk, 'relation', '') or ''}".rstrip()
                    )
            return True, "\n".join(lines) if lines else "（无地点）"

        if name == "search_lore":
            from app.core.agent_context import lore_entry_index, rank_lore_entries

            entries = [e for e in (getattr(project, "loreEntries", None) or []) if e]
            if not entries:
                return True, "（这部作品还没有设定条目）"
            q = str(args.get("query") or "").strip()
            if not q:
                # 留空 = 索引模式：模型先看有哪些条目，再决定取哪条
                return True, f"设定条目索引（共 {len(entries)} 条）：\n{lore_entry_index(entries)}"
            limit = max(1, min(12, int(args.get("limit") or 4)))
            hits = rank_lore_entries(entries, q, limit=limit)
            if not hits:
                # 没命中就把索引给它：别让模型干等，也别让它编一条设定出来
                return True, (
                    f"「{q}」没有命中设定条目。现有条目标题（可换个说法再查，或点名取全文）：\n"
                    f"{lore_entry_index(entries)}"
                )
            parts = []
            pin_titles = [
                str(getattr(e, "title", "") or "")
                for e in entries
                if bool(getattr(e, "pinned", None))
            ]
            for e, score in hits:
                title = str(getattr(e, "title", "") or "（无标题）")
                keys = _entry_keywords_of(e)
                body = str(getattr(e, "body", "") or "")
                head = f"### {title}" + (f"　[{'/'.join(keys)}]" if keys else "")
                parts.append(f"{head}\n{_clip(body, 1500) if body else '（这条没有正文）'}")
            note = ""
            if pin_titles:
                note = f"\n（另有钉住条目每轮都会自动带上：{'、'.join(pin_titles[:6])}）"
            return True, "\n\n".join(parts) + note

        if name == "get_lore_entry":
            ref = str(args.get("ref") or args.get("title") or args.get("id") or "").strip()
            if not ref:
                return False, "ref 必填"
            entry = _find_lore_entry(project, ref)
            if entry is None:
                from app.core.agent_context import lore_entry_index

                return False, (
                    f"未找到设定条目：{ref}\n现有条目标题：\n"
                    f"{lore_entry_index(getattr(project, 'loreEntries', None) or [])}"
                )
            title = str(getattr(entry, "title", "") or "（无标题）")
            keys = _entry_keywords_of(entry)
            body = str(getattr(entry, "body", "") or "")
            head = f"### {title}" + (f"　[{'/'.join(keys)}]" if keys else "")
            return True, f"{head}\n{_clip(body, 6000) if body else '（这条没有正文）'}"

        if name == "lint_draft":
            text = str(args.get("text") or "").strip()
            if not text:
                ch = _find_chapter(project, args.get("chapterRef"), chapter_id)
                if not ch:
                    return False, "无正文可检"
                text = chapter_plain(ch, project.characters)
            audit = full_audit_draft(text)
            issues = audit.get("issues") or []
            if not issues:
                return True, "体检通过：未发现明显问题。"
            head = (
                f"error {audit.get('errorCount', 0)} / "
                f"warn {audit.get('warnCount', 0)} / "
                f"info {audit.get('infoCount', 0)}"
            )
            lines = [head]
            for iss in issues[:24]:
                if isinstance(iss, dict):
                    lines.append(
                        f"- [{iss.get('severity')}] {iss.get('message')}"
                    )
            return True, "\n".join(lines)

        if name == "ledger_digest":
            block = format_ledger_for_agent(get_ledger(project), chapters=project.chapters)
            return True, block.strip() or "（账本为空）"

        if name == "novel_audit":
            scope = str(args.get("scope") or "all").strip().lower()
            if scope not in ("consistency", "craft", "all"):
                scope = "all"
            focus = str(args.get("focus") or "").strip()
            ch = _find_chapter(project, args.get("chapterRef"), chapter_id)
            lines: List[str] = []
            if scope in ("consistency", "all"):
                from app.core.novel_consistency import analyze_novel_consistency

                rep = analyze_novel_consistency(project, focus=focus, max_issues=60)
                counts = rep.get("counts") or {}
                lines.append(
                    "【表记/视角】"
                    f"错误 {counts.get('error', 0)} · 提醒 {counts.get('warn', 0)} · "
                    f"提示 {counts.get('info', 0)}"
                )
                for iss in (rep.get("issues") or [])[:18]:
                    if not isinstance(iss, dict):
                        continue
                    where = f"第{iss.get('chapterOrdinal')}章「{iss.get('chapterTitle')}」"
                    line_no = iss.get("line")
                    if isinstance(line_no, int) and line_no > 0:
                        where += f" 第{line_no}行"
                    lines.append(
                        f"- [{iss.get('severity')}] {where} {iss.get('message')}"
                        f"（片段：{iss.get('quote')}）"
                    )
                cov = rep.get("coverage") or {}
                lines.append(
                    f"（扫描 {cov.get('chaptersScanned', 0)}/{cov.get('chaptersTotal', 0)} 章，"
                    f"覆盖率 {cov.get('coverageRatio', 0)}）"
                )
            if scope in ("craft", "all"):
                from app.core.novel_craft import analyze_novel_craft

                rep2 = analyze_novel_craft(
                    project, chapter_id=(ch.id if ch is not None else None)
                )
                hooks = rep2.get("hookScores") or []
                weak = [h for h in hooks if isinstance(h, dict) and h.get("level") == "weak"]
                lines.append(
                    f"【文面统计】注音问题 {len(rep2.get('rubyIssues') or [])} 处 · "
                    f"章末钩子偏弱 {len(weak)}/{len(hooks)} 章"
                )
                for h in weak[:8]:
                    lines.append(
                        f"- 第{h.get('chapterOrdinal')}章「{h.get('chapterTitle')}」"
                        f"钩子分 {h.get('score')}（{h.get('level')}）"
                    )
            return True, "\n".join(lines) if lines else "体检没有跑出任何结果。"

        if name in ASYNC_TOOL_NAMES:
            # 明确报错而不是伪装成"未知工具"：模型看到这句就会知道该换工具/收工，
            # 而调试时也能一眼看出是分发通道走错了。
            return False, f"{name} 是异步工具（需要调模型），应走 run_agent_tool_async"

        return False, f"未知工具：{name}"
    except Exception as exc:  # noqa: BLE001 — surface to model
        return False, f"工具错误：{exc}"


#: `_blocks_to_plain` 会把结构标记写成 `[label start]` 这种形式
_MARKER_RE = re.compile(r"\[[^\]]*\]")


def _has_real_prose(text: str) -> bool:
    """稿子里有没有**真正的正文**（而不只是 `[label start]` 这类结构标记）。

    为什么需要：`normalize_project` 会给空工程自动补一章，`_blocks_to_plain` 对空章产出的
    是 `[label start]`——它有内容、能过 `if not text`，但它不是正文。拿它去"润色"等于白跑
    一次（体检还会"通过"），作者会以为工具坏了。与账本里 `_hook_has_prose` 同一个道理。
    """
    return len(_MARKER_RE.sub("", text or "").strip()) > 4


async def run_agent_tool_async(
    name: str,
    arguments: Optional[Dict[str, Any]],
    *,
    project: VnProject,
    chapter_id: Optional[str] = None,
    config: Any = None,
) -> Tuple[bool, str]:
    """需要调用模型的工具（`run_agent_tool` 是纯同步的，所以单开一条 async 通道）。

    目前只有 `polish_prose`（原 `/harness/run` 的 editor 角色）。它复用
    `harness_editor_pass`：**先跑确定性体检，体检全过时不调模型**——这样"润色"在
    稿子本来就干净时是零成本的。
    """
    args = arguments if isinstance(arguments, dict) else {}
    if name not in ASYNC_TOOL_NAMES:
        return False, f"未知的异步工具：{name}"
    if name == "polish_prose":
        if config is None:
            return False, "润色需要模型配置，但当前上下文里没有拿到，请作者先在设置里配置模型。"
        text = str(args.get("text") or "").strip()
        if not text:
            ch = _find_chapter(project, args.get("chapterRef"), chapter_id)
            if ch is None:
                return False, "没有可润色的正文：请传入 text，或指定一章（chapterRef）。"
            text = chapter_plain(ch, project.characters)
        if not text.strip():
            return False, "这段/这一章没有正文可润色。"
        if not _has_real_prose(text):
            return False, "这一章目前只有结构标记（还没写正文），先写点内容再来润色。"
        flavor = str(args.get("flavor") or "auto").strip().lower()
        if flavor not in ("auto", "prose", "vn"):
            flavor = "auto"
        from app.core.harness.pipeline import harness_editor_pass

        try:
            out = await harness_editor_pass(
                config, text[:12000], project=project, flavor=flavor
            )
        except Exception as exc:  # noqa: BLE001 — surface to model
            return False, f"润色失败：{exc}"
        issues = [i for i in (out.get("issues") or []) if isinstance(i, dict)]
        notes = "\n".join(
            f"- [{i.get('severity')}] {i.get('message')}" for i in issues[:12]
        )
        if out.get("skippedLlm"):
            return True, "确定性体检通过，未调用模型改写。" + (
                f"\n仍可留意的点：\n{notes}" if notes else ""
            )
        body = str(out.get("content") or "").strip() or "（模型未返回内容）"
        head = f"润色后的正文（{out.get('flavor') or 'auto'} 口径）：\n{body}"
        return True, head + (f"\n\n仍须注意的点：\n{notes}" if notes else "")
    return False, f"未实现的异步工具：{name}"


def format_tool_result_message(name: str, ok: bool, preview: str) -> str:
    status = "ok" if ok else "error"
    body = _clip(preview, 6000)
    return f"[tool_result name={name} status={status}]\n{body}"
