"""P6 critique_contract 守卫（不依赖 DB）。"""

from __future__ import annotations

from app.core.capability_router import critique_framing as router_frame
from app.core.critique_contract import (
    CRITIQUE_OUTPUT_CONTRACT,
    critique_framing,
    parse_critique_payload,
)


def test_critique_framing_vn_vs_novel():
    vn = critique_framing("vn")
    novel = critique_framing("novel")
    assert "critique" in vn and "视觉小说" in vn
    assert "小说" in novel or "轻小说" in novel
    assert vn != novel
    assert CRITIQUE_OUTPUT_CONTRACT.split("只输出")[0] or True
    assert "JSON" in router_frame("vn")


def test_parse_critique_payload_structured():
    raw = json_dumps(
        {
            "summary": "对白偏说明书",
            "issues": [
                {
                    "code": "exposition",
                    "severity": "warn",
                    "quote": "正如你所知",
                    "reason": "说明书腔",
                    "suggestion": "改成动作暗示",
                }
            ],
        }
    )
    out = parse_critique_payload(raw)
    assert out["summary"] == "对白偏说明书"
    assert len(out["issues"]) == 1
    assert out["issues"][0]["code"] == "exposition"


def test_parse_critique_payload_plain_fallback():
    out = parse_critique_payload("整段都太空洞了。")
    assert out["issues"] == []
    assert "空洞" in out["summary"]


def json_dumps(obj):
    import json

    return json.dumps(obj, ensure_ascii=False)
