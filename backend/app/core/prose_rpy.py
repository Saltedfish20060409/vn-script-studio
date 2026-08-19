"""Natural-language manuscript ↔ Ren'Py generation helpers."""
from __future__ import annotations

import hashlib
from typing import List, Optional, Sequence

from app.core.pipeline.apply_draft import extract_script_body, plain_text_to_script_blocks
from app.core.renpy import _char_lookup, _emit_block
from app.domain.types import Character, ScriptBlock, VnProject


def prose_fingerprint(text: str) -> str:
    s = (text or "").replace("\r\n", "\n").strip().encode("utf-8")
    return hashlib.sha1(s).hexdigest()[:12]


def blocks_to_prose(
    blocks: Sequence[ScriptBlock],
    characters: Sequence[Character] | None = None,
) -> str:
    names = {}
    for c in characters or []:
        names[c.id] = c.displayName or c.defineName or c.id
    lines: List[str] = []
    _walk(list(blocks or []), names, lines)
    return "\n\n".join(lines)


def _walk(blocks: List[ScriptBlock], names: dict, lines: List[str]) -> None:
    for b in blocks:
        btype = b.get("type")
        if btype == "scene":
            lines.append(f"[场景：{b.get('image') or ''}]")
        elif btype == "show":
            lines.append(f"[出现：{b.get('image') or ''}]")
        elif btype == "hide":
            lines.append(f"[消失：{b.get('image') or ''}]")
        elif btype == "narration":
            t = str(b.get("text") or "").strip()
            if t:
                lines.append(t)
        elif btype == "dialogue":
            t = str(b.get("text") or "").strip()
            if t:
                who = names.get(str(b.get("characterId") or "")) or "——"
                lines.append(f"{who}：{t}")
        elif btype == "menu":
            prompt = str(b.get("prompt") or "").strip()
            if prompt:
                lines.append(f"选项：{prompt}")
            for choice in b.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                ct = str(choice.get("text") or "").strip()
                if ct:
                    lines.append(f"- {ct}")
                child = choice.get("blocks") or []
                if child:
                    _walk(list(child), names, lines)
        elif btype == "raw":
            code = str(b.get("code") or "").strip()
            if code:
                lines.append(code)


def blocks_to_rpy_text(
    blocks: Sequence[ScriptBlock],
    characters: Sequence[Character],
    *,
    title: str = "",
) -> str:
    chars = _char_lookup(list(characters or []))
    parts: List[str] = []
    if title:
        parts.append(f"# --- {title} ---")
    in_label = False
    for block in blocks:
        if block.get("type") == "label":
            in_label = True
            parts.extend(_emit_block(block, chars, ""))
        else:
            parts.extend(_emit_block(block, chars, "    " if in_label else ""))
    return "\n".join(parts).strip() + "\n"


def parse_prose_to_blocks(
    prose: str,
    characters: Sequence[Character] | None = None,
) -> List[ScriptBlock]:
    """Deterministic fallback: treat manuscript lines as script draft."""
    body = extract_script_body(prose)
    blocks = plain_text_to_script_blocks(body, characters)
    if blocks and not any(b.get("type") == "label" for b in blocks):
        return [{"type": "label", "id": "start", "name": "start"}, *blocks]
    return blocks


async def llm_prose_to_rpy(
    project: VnProject,
    prose: str,
    config,
) -> str:
    from app.core.llm_http import chat_completions, content_from_response

    roster = "、".join(
        f"{c.displayName}({c.defineName})" for c in (project.characters or [])
    ) or "（尚未建立角色卡）"
    res = await chat_completions(
        config,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是视觉小说编剧。把自然语言剧本改写成可上演的 Ren'Py 脚本。"
                    "只输出脚本，不要解释。约定：\n"
                    "- label start: 作为本章入口（若已有其他 label 可保留）\n"
                    '- 旁白：一行 "旁白"\n'
                    '- 对白：define名 "台词"（define 名用英文小写）\n'
                    "- 场景：scene bg_xxx / show / hide\n"
                    "- 分支：menu / jump\n"
                    f"已有角色：{roster}"
                ),
            },
            {
                "role": "user",
                "content": f"作品：{project.title}\n\n自然语言剧本：\n{prose.strip()}",
            },
        ],
        temperature=0.4,
        timeout=120,
    )
    content, _ = content_from_response(res)
    return extract_script_body(content)


async def generate_rpy_from_prose(
    project: VnProject,
    prose: str,
    config: Optional[object] = None,
    *,
    use_llm: bool = True,
) -> tuple[str, List[ScriptBlock]]:
    text = (prose or "").strip()
    if not text:
        raise ValueError("剧本还是空的，先写自然语言稿再生成")
    if use_llm and config is not None and getattr(config, "apiKey", ""):
        rpy = await llm_prose_to_rpy(project, text, config)
        blocks = parse_prose_to_blocks(rpy, project.characters)
        if not blocks:
            raise ValueError("模型没有产出可用脚本，请重试")
        return (rpy if rpy.endswith("\n") else rpy + "\n"), blocks
    blocks = parse_prose_to_blocks(text, project.characters)
    if not blocks:
        raise ValueError("无法从剧本文稿解析出脚本")
    return blocks_to_rpy_text(blocks, project.characters), blocks
