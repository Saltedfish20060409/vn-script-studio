"""Ported from packages/core/src/renpy.ts"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from app.domain.types import Character, ScriptBlock, VnProject


def _escape_renpy_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


# SECURITY (M-7): Ren'Py is Python-based — `$` lines and structured identifiers
# (label / image / jump target / menu id / color) are code positions, not text.
# A prompt-injected or malicious collaborator value there becomes executable
# statements in the exported .rpy. Sanitize everything that lands in a code
# position.
_IDENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")
# Image names legitimately contain spaces in Ren'Py (e.g. `bg overpass_rain`,
# `linxia neutral`) — they are an image lookup, not Python. Still reject
# quotes / newlines / brackets / $ so a value can never escape into code.
_IMAGE_IDENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./ -]*$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _safe_ident(value: Optional[str], fallback: str = "unnamed") -> str:
    """Whitelist identifiers used in code positions (label/jump/menu/at)."""
    v = (value or "").strip()
    if v and _IDENT_RE.match(v):
        return v
    # Reject code-like payloads outright: newlines, quotes, brackets, $, etc.
    if v and not _IDENT_RE.match(v):
        # still return the sanitized fallback but never echo the raw value
        return fallback
    return fallback


def _safe_image(value: Optional[str]) -> str:
    """Whitelist an image name used by scene/show/hide (may contain spaces)."""
    v = (value or "").strip()
    if v and _IMAGE_IDENT_RE.match(v):
        return v
    return "unnamed"


def _safe_color(value: Optional[str]) -> str:
    v = (value or "").strip()
    if _COLOR_RE.match(v):
        return v
    return "#ffffff"


def _char_lookup(characters: List[Character]) -> Dict[str, Character]:
    lookup: Dict[str, Character] = {}
    for c in characters:
        lookup[c.id] = c
        lookup[c.defineName] = c
    return lookup


def _emit_block(
    block: ScriptBlock, chars: Dict[str, Character], indent: str = ""
) -> List[str]:
    lines: List[str] = []
    btype = block.get("type")
    if btype == "label":
        lines.append(f"{indent}label {_safe_ident(block.get('name'))}:")
    elif btype == "scene":
        transition = block.get("transition")
        lines.append(
            f"{indent}scene {_safe_image(block.get('image'))}"
            + (f" with {_safe_ident(transition)}" if transition else "")
        )
    elif btype == "show":
        at = block.get("at")
        lines.append(
            f"{indent}show {_safe_image(block.get('image'))}"
            + (f" at {_safe_ident(at)}" if at else "")
        )
    elif btype == "hide":
        lines.append(f"{indent}hide {_safe_image(block.get('image'))}")
    elif btype == "narration":
        lines.append(f'{indent}"{_escape_renpy_string(block["text"])}"')
    elif btype == "dialogue":
        ch = chars.get(block.get("characterId"))
        who = ch.defineName if ch else "narrator"
        lines.append(f'{indent}{who} "{_escape_renpy_string(block["text"])}"')
    elif btype == "menu":
        menu_id = block.get("id")
        # `menu menu:` is broken output: when no explicit id was given, parsers
        # store the sentinel "menu" — never re-emit it as a second keyword.
        label = f" {_safe_ident(menu_id)}" if menu_id and menu_id != "menu" else ""
        lines.append(f"{indent}menu{label}:")
        prompt = block.get("prompt")
        if prompt:
            lines.append(f'{indent}    "{_escape_renpy_string(prompt)}"')
        for choice in block.get("choices", []) or []:
            lines.append(f'{indent}    "{_escape_renpy_string(choice["text"])}":')
            jump = choice.get("jump")
            child_blocks = choice.get("blocks")
            if jump:
                lines.append(f"{indent}        jump {_safe_ident(jump)}")
            elif child_blocks:
                for child in child_blocks:
                    lines.extend(_emit_block(child, chars, indent + "        "))
            else:
                lines.append(f"{indent}        pass")
    elif btype == "jump":
        lines.append(f"{indent}jump {_safe_ident(block.get('target'))}")
    elif btype == "return":
        lines.append(f"{indent}return")
    elif btype == "comment":
        lines.append(f"{indent}# {block['text']}")
    elif btype == "raw":
        # Raw blocks are author-written Ren'Py by design. To keep prompt-
        # injected `$ os.system(...)` from silently shipping, rewrite any line
        # that starts with `$` into an inert comment (the author must re-add
        # it manually with full awareness).
        for raw_line in block.get("code", "").split("\n"):
            stripped = raw_line.lstrip()
            if stripped.startswith("$"):
                lines.append(f"{indent}# [VNSS] 已跳过 Python 执行行: {raw_line.strip()}")
            else:
                lines.append(f"{indent}{raw_line}")
    return lines


def export_character_defines(project: VnProject) -> str:
    """Export character define lines for script.rpy header"""
    lines = ["# Characters — generated by VN Script Studio", ""]
    for c in project.characters:
        color = _safe_color(c.color)
        lines.append(
            f'define {_safe_ident(c.defineName, "character")} = Character("{_escape_renpy_string(c.displayName)}", color="{color}")'
        )
    return "\n".join(lines) + "\n"


def export_to_renpy(project: VnProject) -> str:
    """Export full project to a single .rpy string"""
    chars = _char_lookup(project.characters)
    parts: List[str] = [
        p
        for p in [
            f"# {project.title}",
            "# Generated by VN Script Studio",
            f"# Logline: {project.logline}" if project.logline else None,
            "",
            export_character_defines(project).rstrip("\n"),
            "",
        ]
        if p is not None
    ]

    for chapter in project.chapters:
        parts.append(f"# --- {chapter.title} ---")
        if chapter.synopsis:
            parts.append(f"# {chapter.synopsis}")
        in_label = False
        for block in chapter.blocks:
            if block.get("type") == "label":
                in_label = True
                parts.extend(_emit_block(block, chars, ""))
            else:
                parts.extend(_emit_block(block, chars, "    " if in_label else ""))
        parts.append("")

    return re.sub(r"\n{3,}", "\n\n", "\n".join(parts))


def _first_chapter_label(project: VnProject) -> Optional[str]:
    """First label name across chapters (entry point), if any."""
    for chapter in project.chapters:
        for block in chapter.blocks:
            if block.get("type") == "label":
                name = block.get("name")
                if name and name != "start":
                    return str(name)
    return None


def _slug_title(title: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (title or "vn").strip(), flags=re.UNICODE)
    slug = re.sub(r"^_+|_+$", "", slug)
    return slug[:48] or "vn"


def export_options_rpy(project: VnProject) -> str:
    """Minimal options.rpy — window name, resolution, save directory."""
    return f'''## options.rpy — generated by VN Script Studio

define config.name = _("{_escape_renpy_string(project.title or 'VN Script Studio')}")
define config.version = "0.1"
define gui.init(1280, 720)

define config.save_directory = "vnsstudio-{_slug_title(project.title)}"
define config.window_title = _("{_escape_renpy_string(project.title or 'VN Script Studio')}")
'''


def export_gui_rpy(project: VnProject) -> str:
    """Minimal generated gui.rpy — accent color from project or brand default."""
    accent = "#002fa7"
    for c in project.characters:
        if c.color:
            accent = _safe_color(c.color)
            break
    return f'''## gui.rpy — minimal UI theme (generated by VN Script Studio)
## Swap in a full Ren'Py template gui.rpy for complete customization.

define gui.text_size = 22
define gui.name_text_size = 24
define gui.interface_text_size = 22
define gui.accent_color = "{accent}"
define gui.idle_color = "#888888"
define gui.hover_color = "{accent}"
define gui.selected_color = "{accent}"
define gui.insensitive_color = "#88888888"
'''


def export_script_rpy(project: VnProject) -> str:
    """script.rpy — story + a start label bridging to the first chapter."""
    body = export_to_renpy(project)
    # Only inject a `start → first-label` bridge when the project does NOT
    # already define `start` itself (otherwise we'd emit a duplicate label
    # and Ren'Py would refuse to load the script).
    has_start = any(
        b.get("type") == "label" and (b.get("name") == "start")
        for ch in project.chapters
        for b in (ch.blocks or [])
    )
    if has_start:
        return body
    first = _first_chapter_label(project)
    if first:
        body = (
            "label start:\n"
            f"    jump {_safe_ident(first)}\n\n"
            "# The actual story chapters follow below.\n\n"
            f"{body}"
        )
    else:
        # No label at all in the story → give it a start that says so
        # (and let the real chapters follow; none of them define start).
        body = "label start:\n    \"（空项目——请先在 VN Script Studio 中写开场。）\"\n\n" + body
    return body


def export_project_bundle(project: VnProject) -> Dict[str, str]:
    """Full Ren'Py project skeleton: script.rpy + options.rpy + gui.rpy + README.

    Drop the contents into a Ren'Py project's game/ folder to run.
    """
    return {
        "script.rpy": export_script_rpy(project),
        "options.rpy": export_options_rpy(project),
        "gui.rpy": export_gui_rpy(project),
        "README.txt": (
            "VN Script Studio — Ren'Py 项目骨架\n"
            "===================================\n\n"
            "把本目录（game/ 内的 4 个文件）复制到 Ren'Py 项目（或新建项目）的 "
            "game/ 目录，启动引擎即可运行。\n\n"
            "文件说明：\n"
            "- script.rpy  剧本（含 label start 入口）\n"
            "- options.rpy 窗口名 / 分辨率 / 存档目录\n"
            "- gui.rpy     极简 UI 主题（可换官方模板 gui.rpy）\n\n"
            "提示：\n"
            "- 角色立绘 / 背景图需自行放入 game/images 并保证文件名与 script 中一致。\n"
            "- 分支 menu 已保留；jump 目标为 label 名。\n"
            "- 由 VN Script Studio 生成；AI 内容请人工审稿后再发行。\n"
        ),
    }


def project_to_context(project: VnProject, max_chars: int = 12000) -> str:
    """Compact text dump for AI context (not full .rpy)"""
    chars_lines = []
    for c in project.characters:
        line = f"- {c.displayName} ({c.defineName})"
        if c.voice:
            line += f": {c.voice}"
        if c.bio:
            line += f" | {c.bio}"
        if c.relationships:
            line += f" | 关系: {c.relationships}"
        chars_lines.append(line)
        mind = (getattr(c, "voiceMind", None) or "").strip()
        if mind:
            snippet = mind if len(mind) <= 600 else mind[:588] + "…"
            chars_lines.append(f"  思维卡:\n{snippet}")
        corpus = getattr(c, "voiceCorpus", None) or []
        if corpus:
            from app.core.character_voice.corpus import format_corpus_for_prompt

            bit = format_corpus_for_prompt(c, max_samples=4, max_chars=700)
            if bit:
                chars_lines.append(bit)
    chars = "\n".join(chars_lines)

    bible = project.bible
    body = f"# Project: {project.title}\n"
    if project.logline:
        body += f"Logline: {project.logline}\n"
    if project.genre:
        body += f"Genre: {project.genre}\n"
    if (bible and bible.world) or project.lore:
        body += f"\n世界观:\n{(bible.world if bible else None) or project.lore}\n"
    if bible and bible.background:
        body += f"\n故事背景:\n{bible.background}\n"
    if bible and bible.outline:
        body += f"\n大纲:\n{bible.outline}\n"
    if bible and bible.themes:
        body += f"\n主题/基调:\n{bible.themes}\n"
    if bible and bible.notes:
        body += f"\n备忘:\n{bible.notes}\n"

    body += f"\nCharacters:\n{chars or '(无)'}\n"

    locs = project.locations or []
    if locs:
        body += "\nLocations:\n"
        for l in locs:
            body += f"- {l.name}" + (f" [{l.imageTag}]" if l.imageTag else "") + (
                f": {l.description}" if l.description else ""
            ) + "\n"

    links = project.locationLinks or []
    if links:
        by_id = {l.id: l.name for l in locs}
        body += "Location links:\n"
        for link in links:
            body += (
                f"- {by_id.get(link.fromId, link.fromId)} --{link.relation}--> "
                f"{by_id.get(link.toId, link.toId)}"
                + (f" ({link.note})" if link.note else "")
                + "\n"
            )

    variables = project.variables or []
    if variables:
        body += "\nVariables / 状态机:\n"
        for v in variables:
            body += (
                f"- {v.name} ({v.key}: {v.type}) = {json.dumps(v.value, ensure_ascii=False)}"
                + (f" [char:{v.bindCharacterId}]" if v.bindCharacterId else "")
                + (f" // {v.note}" if v.note else "")
                + "\n"
            )

    sprites = project.sprites or []
    if sprites:
        body += "\nSprites / 立绘:\n"
        for s in sprites:
            ex = ", ".join(e.tag for e in s.expressions)
            body += (
                f"- {s.name} image={s.imageTag}"
                + (f" char={s.characterId}" if s.characterId else "")
                + f" exprs=[{ex}]\n"
            )

    body += "\n"
    for ch in project.chapters:
        body += f"## {ch.title}\n"
        if ch.synopsis:
            body += f"{ch.synopsis}\n"
        body += _export_chapter_plain(ch.blocks, project.characters) + "\n"

    if len(body) > max_chars:
        return body[len(body) - max_chars :]
    return body


def _export_chapter_plain(blocks: List[ScriptBlock], characters: List[Character]) -> str:
    char_map = _char_lookup(characters)
    lines: List[str] = []
    for b in blocks:
        btype = b.get("type")
        if btype == "label":
            line: Optional[str] = f"[label {b['name']}]"
        elif btype == "scene":
            line = f"[scene {b['image']}]"
        elif btype == "show":
            line = f"[show {b['image']}]"
        elif btype == "hide":
            line = f"[hide {b['image']}]"
        elif btype == "narration":
            line = f"旁白: {b['text']}"
        elif btype == "dialogue":
            ch = char_map.get(b.get("characterId"))
            name = ch.displayName if ch else b.get("characterId")
            line = f"{name}: {b['text']}"
        elif btype == "menu":
            line = f"选项: {' / '.join(c['text'] for c in b.get('choices', []))}"
        elif btype == "jump":
            line = f"[jump {b['target']}]"
        elif btype == "comment":
            line = f"# {b['text']}"
        elif btype == "raw":
            line = b.get("code", "")
        else:
            line = ""
        if line:
            lines.append(line)
    return "\n".join(lines)
