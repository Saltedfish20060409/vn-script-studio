"""长程基准：A 层（确定性）与 B 层（需模型）的契约钉住。

B 层语义矛盾**不**用更长提示词解决；量具上必须标明「需模型」，
确定性检测器不得假装召回它们（见 docs/longrange-consistency-and-eval.md）。
"""

from __future__ import annotations

from app.core.eval_longrange import detect_deterministic
from app.core.project import normalize_project

# 文档里写明的 B 层范畴：年龄 / 季节 / 关系 / 物件属性
B_LAYER_CODES = frozenset(
    {
        "age_conflict",
        "season_conflict",
        "relation_conflict",
        "object_attr_conflict",
    }
)


def test_deterministic_detector_does_not_claim_b_layer_codes():
    """空项目上跑确定性检测：返回的 code 不得属于 B 层语义集合。"""
    project = normalize_project(
        {
            "id": "p-b",
            "title": "契约",
            "chapters": [{"id": "ch1", "title": "一", "prose": "雨停了。"}],
        }
    )
    hits = detect_deterministic(project)
    for hit in hits:
        assert hit.get("code") not in B_LAYER_CODES, hit


def test_b_layer_code_set_is_documented_and_nonempty():
    assert B_LAYER_CODES
    for code in B_LAYER_CODES:
        assert "_" in code
