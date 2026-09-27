"""Dynamic preference axes: tags, cold-start path, convergence brief.

冷启动那条改动的原因（用户反馈）：角色卡空白时反复点「生成三组」，方向永远是那三个。
根因是这里过去**下令**模型"使用冷启动兜底三轴（一一对应）"，模型回什么就被当成轴的
最终答案。现在冷启动请模型自拟，固定三轴退居**解析兜底**——它只在模型返回残缺时出现。
"""

from __future__ import annotations

from app.core.character_voice.corpus import confirmed_axes, format_corpus_for_prompt
from app.core.character_voice.generate import (
    _AXIS_NO_DEFAULT_RULE,
    _FALLBACK_AXES,
    _build_axes_brief,
    _parse_axes_from_model,
    _parse_preference_variants,
    axes_from_tag_ids,
    list_axis_tags,
)
from app.domain.types import Character, VoiceCorpusLine, VoiceCorpusSample


def _char(**kwargs) -> Character:
    base = {"id": "c1", "defineName": "senpai", "displayName": "学姐"}
    base.update(kwargs)
    return Character.model_validate(base)


def test_list_axis_tags_pool_size():
    tags = list_axis_tags()
    assert 15 <= len(tags) <= 30
    ids = {t["id"] for t in tags}
    assert "gentle_persuade" in ids
    assert "cold_short" in ids


def test_axes_from_tag_ids_caps_at_three():
    got = axes_from_tag_ids(
        ["gentle_persuade", "formal_duty", "childlike", "leader"]
    )
    assert len(got) == 3
    assert got[0]["label"] == "温柔劝说"


def test_build_brief_uses_pinned_and_invents_rest():
    char = _char(voice="温柔克制", bio="温柔学姐")
    pinned = axes_from_tag_ids(["gentle_persuade"])
    seed, rule = _build_axes_brief(char, pinned=pinned, confirmed=["温柔劝说"])
    assert len(seed) == 1
    assert "自拟" in rule or "补" in rule or "凑满" in rule


def test_cold_start_asks_the_model_to_invent_and_keeps_a_safety_net():
    """冷启动：**不再**把固定三轴下给模型，但仍保留确定性兜底。

    这是用户反馈的那个 bug 的另一半：角色卡空白时，反复点生成拿到的永远是同样三个方向。
    所以这里钉两件事——
    1. 提示词里**不许**出现兜底三轴，也不许出现"一一对应"这种下令式措辞；
    2. 兜底仍然作为 seed 返回，模型返回残缺时有确定的三条可补。
    """
    char = _char()
    seed, rule = _build_axes_brief(char, pinned=[], confirmed=[])

    # 安全网还在
    assert len(seed) == 3

    # 但不再下令照搬：这是修复的核心（旧实现是"使用冷启动兜底三轴（一一对应）"）
    assert "自拟" in rule
    assert "一一对应" not in rule
    assert "兜底" not in rule
    for axis in _FALLBACK_AXES:
        assert axis["label"] not in rule, f"兜底轴「{axis['label']}」不该出现在提示词里"


def test_cold_start_model_axes_win_over_the_fallback_seed():
    """冷启动下结果用模型自拟的三条；兜底只是 seed，不覆盖模型。"""
    seed, _ = _build_axes_brief(_char(), pinned=[], confirmed=[])
    parsed = {
        "axes": [
            {"id": "probe", "label": "试探性反问", "hint": "先摸对方底"},
            {"id": "withdraw", "label": "沉默回避", "hint": "用沉默挡回去"},
            {"id": "blunt", "label": "直白拆穿", "hint": "不绕弯"},
        ]
    }
    got = _parse_axes_from_model(parsed, seed)
    assert [a["label"] for a in got] == ["试探性反问", "沉默回避", "直白拆穿"]


def test_cold_start_safety_net_fills_when_the_model_returns_too_few():
    """模型返回残缺时，兜底三轴才出场——它是安全网，不是默认答案。"""
    seed, _ = _build_axes_brief(_char(), pinned=[], confirmed=[])
    got = _parse_axes_from_model({"axes": [{"label": "只有这一条"}]}, seed)
    assert len(got) == 3
    assert [a["label"] for a in got][0] == "只有这一条"
    fallback_labels = {a["label"] for a in _FALLBACK_AXES}
    assert fallback_labels & {a["label"] for a in got}, "残缺时应当由兜底补位"


def test_no_default_axis_rule_names_the_real_tags():
    """那句"禁止默认套用"点名的三条必须与标签池的 label 逐字一致。

    过去写的是「软自嘲**留白**」，而标签池里叫「软自嘲」（"留白"只在 hint 里）——
    名字都对不上，模型未必认得出是同一条轴。
    """
    labels = {t["label"] for t in list_axis_tags()}
    for name in ("冷短回避", "热吐槽防护", "软自嘲"):
        assert name in labels, f"{name} 已经不是标签池里的名字了，提示词该跟着改"
        assert name in _AXIS_NO_DEFAULT_RULE
    assert "软自嘲留白" not in _AXIS_NO_DEFAULT_RULE


def test_confirmed_axes_and_prompt():
    char = _char(
        voiceCorpus=[
            VoiceCorpusSample(
                id="s1",
                scenario="misunderstood",
                scenarioLabel="被误解时",
                axis="温柔劝说",
                lines=[VoiceCorpusLine(speaker="self", text="先坐下，慢慢说。")],
                source="preference",
            )
        ]
    )
    assert confirmed_axes(char) == ["温柔劝说"]
    bit = format_corpus_for_prompt(char)
    assert "已确认方向" in bit
    assert "温柔劝说" in bit


def test_parse_variants_keeps_dynamic_labels():
    parsed = {
        "axes": [
            {"id": "soft", "label": "温柔劝说", "hint": "软"},
            {"id": "quiet", "label": "沉默关心", "hint": "少话"},
            {"id": "nudge", "label": "轻嗔带刺", "hint": "轻刺"},
        ],
        "variants": [
            {
                "axisId": "soft",
                "axisLabel": "温柔劝说",
                "hypothesis": "先安抚",
                "lines": [{"speaker": "self", "text": "别急。"}],
            },
            {
                "axisId": "quiet",
                "axisLabel": "沉默关心",
                "hypothesis": "少说多陪",
                "lines": [{"speaker": "self", "text": "……我在。"}],
            },
            {
                "axisId": "nudge",
                "axisLabel": "轻嗔带刺",
                "hypothesis": "轻刺提醒",
                "lines": [{"speaker": "self", "text": "又乱想了吧。"}],
            },
        ],
    }
    variants, axes = _parse_preference_variants(parsed, seed_axes=[])
    assert [v["axisLabel"] for v in variants] == ["温柔劝说", "沉默关心", "轻嗔带刺"]
    assert axes[1]["label"] == "沉默关心"
