"""Content-addressed project snapshots (hash + object payload)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional, Union

from app.domain.types import ProjectSnapshot, VnProject


def snapshot_payload_dict(project: VnProject | dict[str, Any]) -> Dict[str, Any]:
    if isinstance(project, VnProject):
        data = project.model_dump(mode="json", by_alias=True)
    else:
        data = dict(project)
    data.pop("snapshots", None)
    return data


def content_hash_for_payload(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def decode_snapshot_payload(payload: Union[str, Dict[str, Any], Any]) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return dict(payload)
    if isinstance(payload, str):
        return json.loads(payload)
    raise TypeError("snapshot payload must be dict or JSON string")


def latest_content_hash(snaps: list[ProjectSnapshot] | None) -> Optional[str]:
    if not snaps:
        return None
    last = snaps[-1]
    if last.contentHash:
        return last.contentHash
    try:
        decoded = decode_snapshot_payload(last.payload)
        return content_hash_for_payload(decoded)
    except Exception:  # noqa: BLE001
        return None
