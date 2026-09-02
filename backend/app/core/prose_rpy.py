"""Natural-language manuscript ↔ Ren'Py generation helpers."""
from __future__ import annotations

import hashlib
import re
from typing import List, Optional, Sequence

from app.core.pipeline.apply_draft import extract_script_body, plain_text_to_script_blocks
from app.core.renpy import _char_lookup, _emit_block
from app.domain.types import Character, ScriptBlock, VnProject

# SECURITY/QUALITY: prompts + free models routinely emit structurally broken
# Ren'Py (scene without image, define inside label, stray "旁白" prefixes,
# menu with a single jump-to-start self-loop, duplicated keywords). We reject
# such output instead of shipping it to the player / exporter.
_LOOSE_SCENE = re.compile(r"^\s*scene\s*$", re.I)
_LOOSE_SCENE_NO_IMG = re.compile(r"^\s*scene\s+(with\s+\w+|bg|bg\s|img\s|image\s)?\s*$", re.I)
_NARRATOR_PREFIX = re.compile(r'^"旁白[:：]?\s*(.+)"$')
_DEFINE_INSIDE = re.compile(r"^\s*define\s+\w+", re.I)
# A usable character define is `define name = Character("显示名", ...)`.
# Free models emit `define linxia "林夏"` (missing `=`) or
# `define linxia = "林夏"` (string RHS, not a Character) — both crash Ren'Py
# the moment that name speaks, so treat them as structural flaws anywhere.
_DEFINE_CHAR = re.compile(
    r'^\s*define\s+[A-Za-z_]\w*\s*=\s*Character\s*\(', re.I
)
_SELF_LOOP = re.compile(r"^\s*jump\s+start\s*$", re.I)
# `menu menu:` — model doubles the keyword when it meant a bare `menu:`.
_MENU_MENU = re.compile(r"^\s*menu\s+menu\s*:", re.I)
_LABEL_HEAD = re.compile(r"^\s*label\s+([A-Za-z_]\w*)\s*:", re.I)


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
                    "只输出脚本，不要解释。严格语法：\n"
                    "- label 必须顶格；对白/旁白在 label 内缩进 4 空格\n"
                    '- 旁白：一行双引号文本，如 "雨下大了。"（不要把"旁白"二字写进去）\n'
                    '- 对白：define名 "台词"（define 名用英文小写）\n'
                    '- 场景：scene 后必须有图片名，如 scene bg_street；禁止裸 scene\n'
                    "- define 声明角色放在所有 label 之前（顶层），禁止放进 label 内部\n"
                    "- 分支：menu: 后每行一个选项，选项文本用双引号；不要写 menu menu\n"
                    "- 选项若跳转用 jump 标签名；全章必须有且只有一个 return 结尾，"
                    "禁止把选项跳回 start 造成死循环\n"
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


def _rpy_has_structural_flaws(rpy: str) -> Optional[str]:
    """Return a reason string when LLM Ren'Py is structurally unsafe, else None.

    Checks that map to the failure modes observed with free models:
    scene missing image / bare scene, narrator prefix baked into text,
    malformed or in-label define statements, duplicated labels,
    `menu menu:` keyword doubling, and a self-looping jump back to start.
    """
    in_label = False
    seen_labels = set()
    for raw in (rpy or "").split("\n"):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        m_label = _LABEL_HEAD.match(raw)
        if m_label:
            name = m_label.group(1)
            in_label = True
            if name in seen_labels:
                return f"重复的 label: {name}"
            seen_labels.add(name)
            continue
        if _MENU_MENU.match(s):
            return "menu 关键字重复（menu menu）"
        if _LOOSE_SCENE_NO_IMG.match(s):
            return "scene 缺少图片名（裸 scene）"
        if _LOOSE_SCENE.match(s):
            return "scene 缺少图片名（裸 scene）"
        if _NARRATOR_PREFIX.match(s):
            return "旁白文本带「旁白」前缀"
        if _DEFINE_INSIDE.match(s):
            if in_label:
                return "define 写在了 label 内部"
            if not _DEFINE_CHAR.match(raw):
                return "define 未用 = Character(...) 声明角色"
        if _SELF_LOOP.match(s):
            return "存在 jump start 自循环"
    return None


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
        # QUALITY GATE: if the model's output is structurally broken (common
        # with free models), fall back to the deterministic prose parser which
        # always yields structurally sound blocks — worse fidelity, but never
        # a dead loop or a bare `scene bg`.
        flaw = _rpy_has_structural_flaws(rpy)
        if flaw:
            fallback = parse_prose_to_blocks(text, project.characters)
            if fallback:
                return blocks_to_rpy_text(fallback, project.characters), fallback
            raise ValueError(f"模型输出有结构缺陷（{flaw}），自动修复失败，请重试一次")
        return (rpy if rpy.endswith("\n") else rpy + "\n"), blocks
    blocks = parse_prose_to_blocks(text, project.characters)
    if not blocks:
        raise ValueError("无法从剧本文稿解析出脚本")
    return blocks_to_rpy_text(blocks, project.characters), blocks
