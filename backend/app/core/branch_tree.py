"""Ported from packages/core/src/branchTree.ts"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.domain.types import ScriptBlock, VnProject


@dataclass
class BranchNode:
    id: str
    kind: str  # "label" | "menu" | "choice" | "jump" | "end"
    title: str
    children: List["BranchNode"] = field(default_factory=list)


def build_branch_tree(project: VnProject, chapterId: Optional[str] = None) -> List[BranchNode]:
    """Build a lightweight branch tree from menu/jump/label structure."""
    chapters = (
        [c for c in project.chapters if c.id == chapterId] if chapterId else project.chapters
    )

    roots: List[BranchNode] = []
    for ch in chapters:
        chapter_root = BranchNode(
            id=f"ch-{ch.id}",
            kind="label",
            title=ch.title,
            children=_walk_blocks(ch.blocks, ch.id),
        )
        roots.append(chapter_root)
    return roots


def _walk_blocks(blocks: List[ScriptBlock], prefix: str) -> List[BranchNode]:
    nodes: List[BranchNode] = []
    for i, b in enumerate(blocks):
        btype = b.get("type")
        if btype == "label":
            nodes.append(
                BranchNode(
                    id=f"{prefix}-label-{b['name']}-{i}",
                    kind="label",
                    title=f"label {b['name']}",
                    children=[],
                )
            )
        elif btype == "menu":
            choices = b.get("choices", []) or []
            children: List[BranchNode] = []
            for ci, c in enumerate(choices):
                jump = c.get("jump")
                children.append(
                    BranchNode(
                        id=f"{prefix}-choice-{b.get('id')}-{ci}",
                        kind="choice",
                        title=c.get("text", ""),
                        children=(
                            [
                                BranchNode(
                                    id=f"{prefix}-jump-{jump}-{ci}",
                                    kind="jump",
                                    title=f"→ {jump}",
                                    children=[],
                                )
                            ]
                            if jump
                            else []
                        ),
                    )
                )
            prompt = b.get("prompt")
            menu_node = BranchNode(
                id=f"{prefix}-menu-{b.get('id')}-{i}",
                kind="menu",
                title=f"选项：{prompt}" if prompt else f"menu {b.get('id')}",
                children=children,
            )
            nodes.append(menu_node)
        elif btype == "jump":
            nodes.append(
                BranchNode(
                    id=f"{prefix}-jump-{b['target']}-{i}",
                    kind="jump",
                    title=f"jump {b['target']}",
                    children=[],
                )
            )
        elif btype == "return":
            nodes.append(
                BranchNode(id=f"{prefix}-end-{i}", kind="end", title="return", children=[])
            )
    return nodes
