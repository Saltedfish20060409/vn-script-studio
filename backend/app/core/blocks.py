"""Script block 遍历工具（分析模块共用）。

`_walk` 曾在 `script_analysis.py` 与 `asset_audit.py` 各写一份（逐字相同），
而新的分析模块还要用同一套遍历语义，所以抽到这里一处实现。

语义要点：**菜单选项正文与 if 分支正文都要算进去**。少算这一层，统计里
"选项里的对白"会凭空消失——这不是简化，是缺陷（作者写在分支里的台词也是台词）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple


def walk_blocks(blocks: Optional[List[Any]]) -> Iterator[Dict[str, Any]]:
    """深度遍历：先自身，再菜单选项正文与 if 分支正文（任意嵌套）。"""
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        yield b
        for choice in b.get("choices") or []:
            if isinstance(choice, dict):
                yield from walk_blocks(choice.get("blocks") or [])
        for branch in b.get("branches") or []:
            if isinstance(branch, dict):
                yield from walk_blocks(branch.get("blocks") or [])


def iter_project_blocks(project: Any) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """(chapterId, block) 流，按章序与块序（含分支正文）。"""
    for ch in getattr(project, "chapters", None) or []:
        cid = str(getattr(ch, "id", "") or "")
        for b in walk_blocks(getattr(ch, "blocks", None) or []):
            yield cid, b


def iter_dialogue(
    project: Any, *, character_id: Optional[str] = None
) -> Iterator[Tuple[str, str, str]]:
    """(chapterId, characterId, text) 台词流；给 character_id 时只返回该角色。

    空台词被丢弃：空白对白不是语言行为，进了统计只会把均值往 0 拉。
    """
    for cid, b in iter_project_blocks(project):
        if b.get("type") != "dialogue":
            continue
        cid_char = str(b.get("characterId") or "")
        if character_id is not None and cid_char != str(character_id):
            continue
        text = str(b.get("text") or "").strip()
        if not text:
            continue
        yield cid, cid_char, text


def iter_narration(project: Any) -> Iterator[Tuple[str, str]]:
    """(chapterId, text) 旁白流（含分支正文）。"""
    for cid, b in iter_project_blocks(project):
        if b.get("type") != "narration":
            continue
        text = str(b.get("text") or "").strip()
        if text:
            yield cid, text
