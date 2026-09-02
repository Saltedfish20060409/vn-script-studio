"""Apply pipeline / harness draft text onto a chapter as script blocks."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.domain.types import Character, ScriptBlock, VnProject

_SPEAKER_COLON = re.compile(r"^([^\s:：\[\]「」\"']{1,24})\s*[:：]\s*(.*)$")
_SPEAKER_QUOTE = re.compile(r'^([A-Za-z_]\w{0,31})\s+"([^"]*)"\s*$')
_SPEAKER_CN_QUOTE = re.compile(r"^([^\s:：\[\]「」]{1,24})\s*[「『]([^」』]*)[」』]\s*$")
_NARRATOR = re.compile(r"^(旁白|narration|nv)$", re.I)
_SCENE = re.compile(r"^scene\s+(\S+)", re.I)
_LABEL = re.compile(r"^label\s+(\w+)\s*:", re.I)
_JUMP = re.compile(r"^jump\s+(\w+)\s*$", re.I)
_RETURN = re.compile(r"^return\s*$", re.I)
_MENU_HEAD = re.compile(r"^menu(?:\s+(\w+))?\s*:\s*$", re.I)
_MENU_CHOICE = re.compile(r'^"([^"]+)"\s*:\s*$')
_MENU_CHOICE_CN = re.compile(r"^[「『]([^」』]+)[」』]\s*[:：]\s*$")
_OPTIONS_LINE = re.compile(r"^选项\s*[:：]\s*(.+)$")
_BARE_QUOTE = re.compile(r'^[「"「](.+)[」"」]$')
_INDENT = re.compile(r"^(\s*)")


def plain_text_to_raw_blocks(text: str) -> List[ScriptBlock]:
    """One non-empty line → one raw Ren'Py-ish block (legacy fallback)."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    blocks: List[ScriptBlock] = []
    for line in lines:
        t = line.rstrip()
        if not t.strip():
            continue
        blocks.append({"type": "raw", "code": t})
    return blocks


def _char_id_for_name(
    name: str, characters: Sequence[Character] | None
) -> Optional[str]:
    if not characters or not name:
        return None
    n = name.strip()
    for c in characters:
        if c.displayName == n or c.defineName == n:
            return c.id
    # defineName case-insensitive
    low = n.lower()
    for c in characters:
        if (c.defineName or "").lower() == low:
            return c.id
    return None


def _strip_wrapping_quotes(text: str) -> str:
    t = (text or "").strip()
    if len(t) >= 2:
        pairs = [('"', '"'), ("「", "」"), ("『", "』"), ("'", "'")]
        for a, b in pairs:
            if t.startswith(a) and t.endswith(b):
                return t[1:-1].strip()
    return t


def _indent_of(line: str) -> int:
    m = _INDENT.match(line)
    return len(m.group(1)) if m else 0


def _parse_single_line_block(
    raw: str,
    characters: Sequence[Character] | None = None,
) -> Optional[ScriptBlock]:
    """Parse one non-empty line into a block; None if blank."""
    s = raw.strip()
    if not s:
        return None
    if s in ("pass", "pass:"):
        return None
    m_jump = _JUMP.match(s)
    if m_jump:
        return {"type": "jump", "target": m_jump.group(1)}
    if _RETURN.match(s):
        return {"type": "return"}
    m_scene = _SCENE.match(s)
    if m_scene:
        return {"type": "scene", "image": m_scene.group(1)}
    m_label = _LABEL.match(s)
    if m_label:
        return {
            "type": "label",
            "id": m_label.group(1),
            "name": m_label.group(1),
        }
    if s.startswith("#"):
        return {"type": "comment", "text": s.lstrip("#").strip()}
    m = _SPEAKER_COLON.match(s) or _SPEAKER_QUOTE.match(s) or _SPEAKER_CN_QUOTE.match(
        s
    )
    if m:
        speaker = m.group(1).strip()
        spoken = _strip_wrapping_quotes(m.group(2) or "")
        if _NARRATOR.match(speaker):
            return {"type": "narration", "text": spoken}
        cid = _char_id_for_name(speaker, characters)
        if cid:
            return {"type": "dialogue", "characterId": cid, "text": spoken}
        return {
            "type": "raw",
            "code": f'{speaker} "{spoken}"' if spoken else raw.rstrip(),
        }
    m_bare = _BARE_QUOTE.match(s)
    if m_bare:
        t = m_bare.group(1).strip()
        # Free models often bake the "旁白" label into quoted narration
        # (e.g. "旁白 雨下大了。") — strip it so the line plays as plain text.
        t = re.sub(r"^旁白[:：]?\s*", "", t)
        return {"type": "narration", "text": t}
    if s.startswith(("$", "define ", "image ")):
        return {"type": "raw", "code": raw.rstrip()}
    if ":" not in s and "：" not in s and not s.startswith("["):
        return {"type": "narration", "text": s}
    return {"type": "raw", "code": raw.rstrip()}


def _parse_menu_block(
    lines: List[str],
    start: int,
    characters: Sequence[Character] | None = None,
) -> tuple[ScriptBlock, int]:
    """
    Parse Ren'Py-ish menu starting at lines[start] (`menu:` / `menu id:`).
    Choice bodies may include nested dialogue / narration / jump / scene.
    Returns (block, next_index).
    """
    head = lines[start].strip()
    m_head = _MENU_HEAD.match(head)
    menu_id = (m_head.group(1) if m_head and m_head.group(1) else None) or "menu"
    choices: List[Dict[str, Any]] = []
    i = start + 1
    prompt: Optional[str] = None
    while i < len(lines):
        raw = lines[i]
        if not raw.strip():
            i += 1
            continue
        ind = _indent_of(raw)
        s = raw.strip()
        if ind == 0 and (
            _MENU_HEAD.match(s)
            or _LABEL.match(s)
            or _SCENE.match(s)
            or _JUMP.match(s)
            or _RETURN.match(s)
            or _SPEAKER_COLON.match(s)
            or _SPEAKER_QUOTE.match(s)
        ):
            break
        m_ch = _MENU_CHOICE.match(s) or _MENU_CHOICE_CN.match(s)
        if m_ch and ind >= 1:
            choice_text = m_ch.group(1).strip()
            nested: List[ScriptBlock] = []
            j = i + 1
            while j < len(lines):
                raw2 = lines[j]
                if not raw2.strip():
                    j += 1
                    continue
                ind2 = _indent_of(raw2)
                s2 = raw2.strip()
                if ind2 <= ind and (
                    _MENU_CHOICE.match(s2)
                    or _MENU_CHOICE_CN.match(s2)
                    or ind2 == 0
                ):
                    break
                if ind2 > ind:
                    blk = _parse_single_line_block(raw2, characters)
                    if blk:
                        nested.append(blk)
                    j += 1
                    continue
                break
            choice: Dict[str, Any] = {"text": choice_text}
            if (
                len(nested) == 1
                and nested[0].get("type") == "jump"
                and nested[0].get("target")
            ):
                choice["jump"] = nested[0]["target"]
            elif nested:
                choice["blocks"] = nested
            choices.append(choice)
            i = j
            continue
        if ind >= 1 and not choices and _BARE_QUOTE.match(s):
            prompt = _BARE_QUOTE.match(s).group(1).strip()
            i += 1
            continue
        break
    block: ScriptBlock = {"type": "menu", "id": menu_id, "choices": choices}
    if prompt:
        block["prompt"] = prompt
    return block, max(i, start + 1)


def plain_text_to_script_blocks(
    text: str,
    characters: Sequence[Character] | None = None,
) -> List[ScriptBlock]:
    """
    Parse draft lines into structured blocks when possible:
    dialogue / narration / scene / label / jump / return / menu;
    unknown lines stay raw.
    """
    lines = (text or "").replace("\r\n", "\n").split("\n")
    blocks: List[ScriptBlock] = []
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip()
        s = raw.strip()
        if not s:
            i += 1
            continue

        if _MENU_HEAD.match(s):
            block, nxt = _parse_menu_block(lines, i, characters)
            if block.get("choices"):
                blocks.append(block)
            else:
                blocks.append({"type": "raw", "code": raw})
            i = nxt
            continue

        m_opt = _OPTIONS_LINE.match(s)
        if m_opt:
            parts = [p.strip() for p in re.split(r"[/｜|]", m_opt.group(1)) if p.strip()]
            if parts:
                blocks.append(
                    {
                        "type": "menu",
                        "id": "menu",
                        "choices": [{"text": p} for p in parts],
                    }
                )
            i += 1
            continue

        m_jump = _JUMP.match(s)
        if m_jump:
            blocks.append({"type": "jump", "target": m_jump.group(1)})
            i += 1
            continue
        if _RETURN.match(s):
            blocks.append({"type": "return"})
            i += 1
            continue

        m_scene = _SCENE.match(s)
        if m_scene:
            blocks.append({"type": "scene", "image": m_scene.group(1)})
            i += 1
            continue
        m_label = _LABEL.match(s)
        if m_label:
            blocks.append(
                {"type": "label", "id": m_label.group(1), "name": m_label.group(1)}
            )
            i += 1
            continue

        m = _SPEAKER_COLON.match(s) or _SPEAKER_QUOTE.match(s) or _SPEAKER_CN_QUOTE.match(
            s
        )
        if m:
            speaker = m.group(1).strip()
            spoken = _strip_wrapping_quotes(m.group(2) or "")
            if _NARRATOR.match(speaker):
                blocks.append({"type": "narration", "text": spoken})
            else:
                cid = _char_id_for_name(speaker, characters)
                if cid:
                    blocks.append(
                        {"type": "dialogue", "characterId": cid, "text": spoken}
                    )
                else:
                    blocks.append(
                        {
                            "type": "raw",
                            "code": f'{speaker} "{spoken}"' if spoken else raw,
                        }
                    )
            i += 1
            continue

        m_bare = _BARE_QUOTE.match(s)
        if m_bare:
            t = m_bare.group(1).strip()
            t = re.sub(r"^旁白[:：]?\s*", "", t)
            blocks.append({"type": "narration", "text": t})
            i += 1
            continue

        # Plain prose without speaker → narration
        if not s.startswith(("$", "define ", "image ")):
            if ":" not in s and "：" not in s and not s.startswith("["):
                blocks.append({"type": "narration", "text": s})
                i += 1
                continue

        blocks.append({"type": "raw", "code": raw})
        i += 1
    return blocks


def extract_script_body(llm_text: str) -> str:
    """
    Prefer fenced code body or content after the last ##/### header
    so Editor 'notes + draft' replies still yield playable text.
    """
    raw = (llm_text or "").strip()
    if not raw:
        return ""
    fence = re_search_fence(raw)
    if fence:
        return fence.strip()
    lines = raw.split("\n")
    start = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith("-") or s.startswith("*"):
            continue
        if s.startswith("仍须") or s.startswith("注意"):
            continue
        start = i
        break
    body = "\n".join(lines[start:]).strip()
    return body or raw


def re_search_fence(text: str) -> Optional[str]:
    blocks = re.findall(r"```(?:renpy|rpy|text)?\s*\n([\s\S]*?)```", text, flags=re.I)
    if blocks:
        return blocks[-1]
    return None


def apply_draft_to_chapter(
    project: VnProject,
    chapter_id: str,
    draft: str,
    *,
    mode: str = "replace",
    structured: bool = True,
) -> VnProject:
    """
    Write draft into chapter.blocks.
    mode=replace: overwrite blocks; mode=append: extend after existing.
    structured=True: prefer dialogue/narration/scene/label parsing.
    """
    ch = next((c for c in project.chapters if c.id == chapter_id), None)
    if not ch:
        raise ValueError("章节不存在")
    body = extract_script_body(draft)
    if structured:
        new_blocks = plain_text_to_script_blocks(body, project.characters)
    else:
        new_blocks = plain_text_to_raw_blocks(body)
    if not new_blocks:
        raise ValueError("无可写入的正文")

    data = project.model_dump()
    chapters: List[Dict[str, Any]] = []
    for c in data.get("chapters") or []:
        if c.get("id") == chapter_id:
            if mode == "append":
                prev = list(c.get("blocks") or [])
                c = {**c, "blocks": prev + new_blocks}
            else:
                c = {**c, "blocks": new_blocks}
        chapters.append(c)
    data["chapters"] = chapters
    return VnProject.model_validate(data)
