"""NL↔RPY 完整映射：mapId、指纹、冲突、保结构合并（独立 ADR）。"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple

ConflictKind = Literal["none", "prose", "blocks", "both"]


def new_map_id() -> str:
    return "m_" + uuid.uuid4().hex[:12]


def ensure_block_map_ids(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        nb = dict(b)
        if not str(nb.get("mapId") or "").strip():
            nb["mapId"] = new_map_id()
        # recurse menu / if
        if nb.get("type") == "menu" and isinstance(nb.get("choices"), list):
            choices = []
            for ch in nb["choices"]:
                if not isinstance(ch, dict):
                    continue
                c2 = dict(ch)
                if isinstance(c2.get("blocks"), list):
                    c2["blocks"] = ensure_block_map_ids(c2["blocks"])
                choices.append(c2)
            nb["choices"] = choices
        if nb.get("type") == "if" and isinstance(nb.get("branches"), list):
            branches = []
            for br in nb["branches"]:
                if not isinstance(br, dict):
                    continue
                b2 = dict(br)
                if isinstance(b2.get("blocks"), list):
                    b2["blocks"] = ensure_block_map_ids(b2["blocks"])
                branches.append(b2)
            nb["branches"] = branches
        out.append(nb)
    return out


def fingerprint_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:32]


def fingerprint_blocks(blocks: List[Dict[str, Any]]) -> str:
    import json

    raw = json.dumps(blocks or [], ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def detect_conflict(
    prose: str,
    blocks: List[Dict[str, Any]],
    nl_rpy_map: Optional[Dict[str, Any]],
) -> ConflictKind:
    if not nl_rpy_map or not isinstance(nl_rpy_map, dict):
        return "none"
    prose_fp = fingerprint_text(prose or "")
    blocks_fp = fingerprint_blocks(blocks or [])
    old_p = str(nl_rpy_map.get("proseFingerprint") or "")
    old_b = str(nl_rpy_map.get("blocksFingerprint") or "")
    prose_dirty = bool(old_p) and prose_fp != old_p
    blocks_dirty = bool(old_b) and blocks_fp != old_b
    if prose_dirty and blocks_dirty:
        return "both"
    if prose_dirty:
        return "prose"
    if blocks_dirty:
        return "blocks"
    return "none"


def build_nl_rpy_map(
    prose: str,
    blocks: List[Dict[str, Any]],
    *,
    segments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    ensured = ensure_block_map_ids(blocks)
    map_ids = [str(b.get("mapId")) for b in ensured if b.get("mapId")]
    segs = segments or [
        {
            "id": "seg_all",
            "proseStart": 0,
            "proseEnd": len(prose or ""),
            "mapIds": map_ids,
        }
    ]
    return {
        "version": 1,
        "proseFingerprint": fingerprint_text(prose or ""),
        "blocksFingerprint": fingerprint_blocks(ensured),
        "segments": segs,
    }


def merge_preserve_structure(
    old_blocks: List[Dict[str, Any]],
    new_blocks: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """按 mapId 对齐：新块尽量继承旧块的 label/menu/characterId。

    返回 (merged, unmapped_old)。
    """
    old = ensure_block_map_ids(old_blocks)
    new = ensure_block_map_ids(new_blocks)
    by_id = {str(b.get("mapId")): b for b in old if b.get("mapId")}
    used: set[str] = set()
    merged: List[Dict[str, Any]] = []
    for nb in new:
        mid = str(nb.get("mapId") or "")
        ob = by_id.get(mid) if mid else None
        if ob is None and nb.get("type") == "label":
            # 同名 label 对齐
            name = str(nb.get("name") or "")
            for cand in old:
                if cand.get("type") == "label" and str(cand.get("name") or "") == name:
                    ob = cand
                    mid = str(cand.get("mapId") or mid)
                    break
        if ob is not None:
            used.add(str(ob.get("mapId") or mid))
            out = dict(nb)
            out["mapId"] = ob.get("mapId") or out.get("mapId") or new_map_id()
            if ob.get("type") == "label" and nb.get("type") == "label":
                out["id"] = ob.get("id") or out.get("id")
                out["name"] = ob.get("name") or out.get("name")
            if ob.get("type") == "dialogue" and nb.get("type") == "dialogue":
                if ob.get("characterId"):
                    out["characterId"] = ob["characterId"]
            if ob.get("type") == "menu" and nb.get("type") == "menu":
                out["id"] = ob.get("id") or out.get("id")
                # 保留旧 choice jump 若文案相同
                old_choices = ob.get("choices") if isinstance(ob.get("choices"), list) else []
                new_choices = nb.get("choices") if isinstance(nb.get("choices"), list) else []
                fixed = []
                for nc in new_choices:
                    if not isinstance(nc, dict):
                        continue
                    nc2 = dict(nc)
                    for oc in old_choices:
                        if isinstance(oc, dict) and str(oc.get("text") or "") == str(
                            nc.get("text") or ""
                        ):
                            if oc.get("jump"):
                                nc2["jump"] = oc["jump"]
                            if oc.get("condition"):
                                nc2["condition"] = oc["condition"]
                            break
                    fixed.append(nc2)
                out["choices"] = fixed
            merged.append(out)
        else:
            merged.append(nb)
    unmapped = [b for b in old if str(b.get("mapId") or "") not in used]
    return merged, unmapped
