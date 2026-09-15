"""本地化：文本提取、术语表、翻译进度、Ren'Py 导出。

设计要点（都在代码里体现了取舍）：

1. **键要稳**：条目标识用 `chapterId#blockIndex`，但**换源文本哈希匹配**——
   作者在前面插一段对白时，后面的翻译不该全部错位丢失。
2. **只收该翻的**：对白、旁白、菜单提示语、选项文本。指令（音乐/镜头/变量）与
   raw 代码不进翻译表。
3. **术语表真的有用**：能按术语表**预填**译文（人名/专有名词先替换掉），
   作者只需补剩下的句子；这也是"术语一致性"最实际的落点。
4. **导出用 Ren'Py 的字符串翻译**（`translate <lang> strings:` + old/new），
   这是官方推荐、对既有脚本零侵入的做法。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.domain.types import VnProject

# 语言代码安全化：只允许 a-z A-Z 0-9 _ -（会出现在导出的 Ren'Py 语句里）
_LOCALE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,15}$")
_WS_RE = re.compile(r"\s+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_hash(text: str) -> str:
    """源文本指纹：用于"键变了但内容没变"时把译文接回去。"""
    t = _WS_RE.sub(" ", (text or "").strip())
    h = 2166136261
    for ch in t:
        h = (h ^ ord(ch)) & 0xFFFFFFFF
        h = (h * 16777619) & 0xFFFFFFFF
    return f"{h:08x}"


def valid_locale(code: str) -> bool:
    return bool(_LOCALE_RE.match((code or "").strip()))


def _walk_units(blocks: List[Any]) -> Iterable[Tuple[int, Dict[str, Any]]]:
    """产出 (顶层块下标, 块)。只走顶层与菜单选项正文/if 分支里的文本块。"""
    for i, b in enumerate(blocks or []):
        if not isinstance(b, dict):
            continue
        yield i, b


def _collect_units(
    blocks: List[Any], chapter_id: str, prefix: str = ""
) -> List[Dict[str, Any]]:
    """递归收集可翻译单元：对白/旁白/菜单提示/选项文本。"""
    units: List[Dict[str, Any]] = []
    for i, b in _walk_units(blocks):
        btype = b.get("type")
        base = f"{chapter_id}#{prefix}{i}"
        if btype in ("dialogue", "narration"):
            text = str(b.get("text") or "").strip()
            if text:
                units.append({"key": base, "kind": btype, "text": text})
        elif btype == "menu":
            prompt = str(b.get("prompt") or "").strip()
            if prompt:
                units.append({"key": f"{base}.prompt", "kind": "prompt", "text": prompt})
            for ci, choice in enumerate(b.get("choices") or []):
                if not isinstance(choice, dict):
                    continue
                ctext = str(choice.get("text") or "").strip()
                if ctext:
                    units.append(
                        {"key": f"{base}.c{ci}", "kind": "choice", "text": ctext}
                    )
                units.extend(
                    _collect_units(
                        choice.get("blocks") or [],
                        chapter_id,
                        # 注意：prefix 里**不要**再带 chapterId（base 已经带过）
                        prefix=f"{prefix}{i}.c{ci}.",
                    )
                )
        elif btype == "if":
            for bi, branch in enumerate(b.get("branches") or []):
                if not isinstance(branch, dict):
                    continue
                units.extend(
                    _collect_units(
                        branch.get("blocks") or [],
                        chapter_id,
                        prefix=f"{prefix}{i}.b{bi}.",
                    )
                )
    return units


def extract_entries(project: VnProject, existing: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """按当前剧本提取条目，并尽量保留已有译文。

    保留策略：先按键匹配；键找不到时，用 (chapterId, sourceHash) 匹配——
    这样在段落前后插入内容后，译文还能自动接回去。
    """
    prev = (existing or {}).get("entries") or []
    by_key = {e.get("key"): e for e in prev if isinstance(e, dict) and e.get("key")}
    by_hash: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for e in prev:
        if isinstance(e, dict) and e.get("chapterId") and e.get("sourceHash"):
            by_hash.setdefault((e["chapterId"], e["sourceHash"]), e)

    out: List[Dict[str, Any]] = []
    for ch in project.chapters or []:
        for unit in _collect_units(ch.blocks or [], ch.id):
            h = source_hash(unit["text"])
            # 键命中且**内容指纹也一致**才认这份译文；否则按指纹在整章里找。
            # 反过来做的后果很严重：同一位置的文本被改写后，旧译文会被贴到新句子上。
            old: Optional[Dict[str, Any]] = None
            candidate = by_key.get(unit["key"])
            if isinstance(candidate, dict) and candidate.get("sourceHash") == h:
                old = candidate
            if old is None:
                old = by_hash.get((ch.id, h))
            targets = dict(old.get("targets") or {}) if isinstance(old, dict) else {}
            status = dict(old.get("status") or {}) if isinstance(old, dict) else {}
            out.append(
                {
                    "key": unit["key"],
                    "chapterId": ch.id,
                    "kind": unit["kind"],
                    "source": unit["text"],
                    "sourceHash": h,
                    "targets": targets,
                    "status": status,
                    "note": (old.get("note") if isinstance(old, dict) else "") or "",
                }
            )
    return out


def apply_glossary(text: str, glossary: List[Dict[str, Any]], locale: str) -> str:
    """按术语表做一次替换，用于预填译文。长术语优先，避免"林"先被替换掉。"""
    out = text
    terms = [
        (str(g.get("term") or ""), ((g.get("targets") or {}) or {}).get(locale) or "")
        for g in glossary or []
    ]
    for term, target in sorted(terms, key=lambda kv: -len(kv[0])):
        if term and target:
            out = out.replace(term, str(target))
    return out


def localization_stats(project: VnProject) -> Dict[str, Any]:
    """每个语言的进度：翻译完成数 / 条目总数。"""
    loc = getattr(project, "localization", None) or {}
    entries = [e for e in (loc.get("entries") or []) if isinstance(e, dict)]
    locales = [l for l in (loc.get("locales") or []) if isinstance(l, dict)]
    stats = []
    for l in locales:
        code = str(l.get("code") or "")
        done = sum(
            1
            for e in entries
            if str((e.get("targets") or {}).get(code) or "").strip()
        )
        total = len(entries)
        stats.append(
            {
                "code": code,
                "name": l.get("name") or code,
                "status": l.get("status") or "draft",
                "translated": done,
                "total": total,
                "ratio": round(done / total, 3) if total else 0.0,
            }
        )
    return {
        "locales": stats,
        "entries": len(entries),
        "glossary": len([g for g in (loc.get("glossary") or []) if isinstance(g, dict)]),
        "updatedAt": loc.get("updatedAt"),
    }


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def export_localization_renpy(project: VnProject) -> Dict[str, str]:
    """每个语言一个 .rpy：`translate <lang> strings:` + old/new。

    返回 {文件名: 内容}；没有译文时不生成该语言的文件。
    """
    loc = getattr(project, "localization", None) or {}
    entries = [e for e in (loc.get("entries") or []) if isinstance(e, dict)]
    locales = [
        l for l in (loc.get("locales") or []) if isinstance(l, dict) and valid_locale(str(l.get("code") or ""))
    ]
    files: Dict[str, str] = {}
    for l in locales:
        code = str(l["code"])
        pairs = []
        for e in entries:
            target = str((e.get("targets") or {}).get(code) or "").strip()
            src = str(e.get("source") or "").strip()
            if not target or not src or target == src:
                continue
            pairs.append((src, target))
        if not pairs:
            continue
        lines = [
            f"# {l.get('name') or code} 翻译 — generated by VN Script Studio",
            f"# 共 {len(pairs)} 条（未翻译的条目在引擎里回落到原文）",
            "",
            f"translate {code} strings:",
            "",
        ]
        for src, target in pairs:
            lines.append(f'    old "{_escape(src)}"')
            lines.append(f'    new "{_escape(target)}"')
            lines.append("")
        files[f"tl/{code}/strings.rpy"] = "\n".join(lines)
    return files


def merge_save(project: VnProject, payload: Dict[str, Any]) -> VnProject:
    """保存本地化数据（locales / entries / glossary），并刷新提取结果。

    对账口径很重要：**指纹以服务端已存条目为准**，客户端只提供译文/状态。
    这样既能在段落增删后把译文接回去，又能在"同一位置的文本被改写"时果断丢掉旧译文
    （否则会把上一句的翻译贴到新句子上——比丢译文严重得多）。
    """
    incoming = [
        e for e in (payload.get("entries") or []) if isinstance(e, dict) and e.get("key")
    ]
    by_key = {e["key"]: e for e in incoming}

    locales = []
    for l in payload.get("locales") or []:
        if not isinstance(l, dict):
            continue
        code = str(l.get("code") or "").strip()
        if not valid_locale(code):
            continue
        locales.append(
            {
                "code": code,
                "name": str(l.get("name") or code)[:40],
                "status": str(l.get("status") or "draft")[:16],
            }
        )
    glossary = []
    for g in payload.get("glossary") or []:
        if not isinstance(g, dict):
            continue
        term = str(g.get("term") or "").strip()
        if not term:
            continue
        targets = {
            str(k): str(v)
            for k, v in (g.get("targets") or {}).items()
            if isinstance(v, str) and v.strip()
        }
        glossary.append(
            {
                "term": term[:60],
                "targets": targets,
                "note": str(g.get("note") or "")[:120],
            }
        )

    base = getattr(project, "localization", None) or {}
    base_entries = [e for e in (base.get("entries") or []) if isinstance(e, dict)]

    # 服务端条目（带指纹）+ 客户端这次的译文/状态
    enriched: List[Dict[str, Any]] = []
    seen: set = set()
    for e in base_entries:
        key = e.get("key")
        patch = by_key.get(key)
        row = dict(e)
        if isinstance(patch, dict):
            if patch.get("targets") is not None:
                row["targets"] = patch["targets"]
            if patch.get("status") is not None:
                row["status"] = patch["status"]
            if patch.get("note") is not None:
                row["note"] = patch["note"]
            # 客户端从 GET 拿到的 sourceHash 会原样回传；优先信它（它就是服务端算的）
            if patch.get("sourceHash"):
                row["sourceHash"] = patch["sourceHash"]
        enriched.append(row)
        seen.add(key)
    # 客户端提交了但服务端没有的键（例如前端在两次保存之间点了"重新提取"）：
    # 只要带了 sourceHash 就认，没带就当成新条目（宁可重填，也不把译文贴错句子）
    for key, patch in by_key.items():
        if key not in seen:
            enriched.append(
                {
                    "key": key,
                    **{
                        k: patch[k]
                        for k in ("targets", "status", "note", "sourceHash")
                        if k in patch
                    },
                }
            )

    data = project.model_dump()
    data["localization"] = {
        "locales": locales,
        "entries": extract_entries(project, {"entries": enriched}),
        "glossary": glossary,
        "updatedAt": _now(),
    }
    return VnProject.model_validate(data)


def suggest_prefill(project: VnProject, locale: str) -> int:
    """用术语表预填空译文，返回填了几条。仅供 API 的"一键预填"使用。"""
    loc = getattr(project, "localization", None) or {}
    glossary = loc.get("glossary") or []
    filled = 0
    for e in loc.get("entries") or []:
        if not isinstance(e, dict):
            continue
        targets = e.setdefault("targets", {})
        if str(targets.get(locale) or "").strip():
            continue
        candidate = apply_glossary(str(e.get("source") or ""), glossary, locale)
        if candidate and candidate != e.get("source"):
            targets[locale] = candidate
            filled += 1
    return filled
