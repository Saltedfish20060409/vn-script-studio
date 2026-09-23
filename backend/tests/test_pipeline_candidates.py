"""best-of-N 采样 + 确定性打分的测试。

这里锁住的是三条**行为承诺**，不是实现细节：
1. **不真发请求**：全部用注入的假 completer，网络路径一次都不走（缺 key 时连尝试都不尝试）；
2. **打分能替作者挑**：带 error 级问题的候选绝不能因为"温度合适/length 刚好"就被选中；
3. **失败不扩散**：单个候选炸掉，其余候选照常完成；全炸就返回 error 信封而不抛异常。

另外把"理由"也当成契约测：它是给作者看的一句话，必须提到**具体依据**（节拍覆盖、声线
偏离这类可核对的数字），否则作者没法判断这个工具是不是在瞎选。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.core.ai import DeepSeekConfig
from app.core.pipeline.candidates import (
    DEFAULT_CANDIDATES,
    SOFT_WEIGHTS,
    build_candidate_messages,
    count_chars,
    generate_best_candidates,
    generate_candidates,
    rank_candidates,
    score_candidate,
    temperature_ladder,
)
from app.core.project import normalize_project

# ------------------------------------------------------------------ 夹具工具


def _d(char_id: str, text: str) -> dict:
    return {"type": "dialogue", "characterId": char_id, "text": text}


def _ch(cid: str, blocks: list, title: str | None = None) -> dict:
    return {"id": cid, "title": title or cid, "blocks": blocks}


def _project(chapters: list, characters: list | None = None):
    return normalize_project(
        {
            "id": "p1",
            "title": "候选测试",
            "characters": characters
            or [
                {"id": "lin", "defineName": "lin", "displayName": "林夏"},
                {"id": "zhou", "defineName": "zhou", "displayName": "周屿"},
            ],
            "chapters": chapters,
        }
    )


#: 寡言克制：短句、几乎没有语气助词与逗号（用于建出声线画像）。
LACONIC = [
    "嗯。",
    "不要。",
    "走。",
    "知道。",
    "是吗。",
    "好。",
    "不。",
    "随便。",
    "算了。",
    "行。",
    "不用。",
    "没事。",
    "等。",
    "看。",
    "别。",
    "可以。",
    "不必。",
    "知道了。",
]

#: 一份"干净"的候选：无 error，节拍词齐，长度落在默认区间内。
CLEAN = (
    "林夏: 站台上没有人。\n"
    "周屿: 那我们再等一会儿。\n"
    "旁白: 雨点打在雨伞上，她把伞往他那边偏了偏。\n"
    "林夏: 你先把伞拿好。\n"
    "周屿: 我拿着。\n"
    "旁白: 末班车没有来，站台的灯灭了一盏，两个人谁也没有走。\n"
    "林夏: 再等十分钟。\n"
    "周屿: 好。\n"
    "旁白: 雨声把两个人的呼吸都盖住了，她数着站牌上的字，一遍又一遍，直到数乱。\n"
    "林夏: 你说，车还会来吗。\n"
    "周屿: 会来的。\n"
    "旁白: 他答得很轻，像是说给自己听；檐下的水连成一条线，落在两个人的脚边。\n"
).strip()

#: 含 error 级问题的候选：narrative_lint 的设定倾倒（"好感度"）会直接判 error。
DIRTY = (
    "林夏: 好感度加一。\n"
    "旁白: 她站在站台上等着，雨下得很大，站台的灯忽明忽暗。\n"
    "周屿: 雨伞在这里。\n"
    "旁白: 末班车没有来，两个人在站台上站了很久，谁也没有说话。\n"
).strip()

BEAT_SHEET: Dict[str, Any] = {
    "goal": "站台等待与末班车",
    "beats": [{"name": "站台"}, {"name": "雨伞"}],
}


def _fake(summary: List[Dict[str, Any]], body: str = CLEAN):
    """假 completer：记录每次调用的温度，返回固定正文（不再访问网络）。"""

    async def completer(config, *, messages, temperature, timeout=0) -> str:
        summary.append({"temperature": temperature, "messages": messages, "timeout": timeout})
        return body

    return completer


def _by_temperature(summary: List[Dict[str, Any]], mapping: Dict[float, Any], default: Any):
    """按温度返回不同正文（或抛异常）的假 completer：用来构造"某一档有问题"。"""

    async def completer(config, *, messages, temperature, timeout=0) -> str:
        summary.append({"temperature": temperature})
        value = mapping.get(temperature, default)
        if isinstance(value, Exception):
            raise value
        return value

    return completer


CONFIG = DeepSeekConfig(apiKey="test-key-not-real")


# ------------------------------------------------------------------ 采样阶段


def test_ladder_is_centered_and_spread_around_the_base():
    temps = temperature_ladder(0.78, 3)
    assert len(temps) == 3
    assert temps[1] == 0.78
    assert temps[0] < temps[1] < temps[2]
    assert round(temps[2] - temps[0], 4) == 0.16


def test_ladder_is_clamped_into_the_legal_range():
    """靠边时梯形会被夹平——这不是 bug，而是"不能越过 llm_params 的合法区间"。"""
    temps = temperature_ladder(0.2, 3)
    assert temps[0] == 0.2
    assert all(0.2 <= t <= 1.0 for t in temps)


def test_every_candidate_is_called_with_a_distinct_temperature():
    summary: List[Dict[str, Any]] = []
    result = asyncio.run(
        generate_candidates(
            CONFIG,
            _project([_ch("ch1", [_d("lin", "嗯。")])]),
            task="continue",
            instruction="续写站台那一段",
            n=3,
            completer=_fake(summary),
        )
    )
    assert len(summary) == 3
    assert result["succeeded"] == 3
    assert result["failed"] == 0
    temps = [row["temperature"] for row in summary]
    assert len(set(temps)) == 3, temps
    assert sorted(result["temperatures"]) == sorted(temps)
    assert [c["temperature"] for c in result["candidates"]] == temps
    assert all(c["text"] == CLEAN for c in result["candidates"])


def test_candidates_share_one_prompt_and_carry_task_context():
    summary: List[Dict[str, Any]] = []
    asyncio.run(
        generate_candidates(
            CONFIG,
            _project([_ch("ch1", [_d("lin", "嗯。")])]),
            task="continue",
            instruction="续写站台那一段",
            n=2,
            beat_sheet=BEAT_SHEET,
            context_text="上一段：她走进了站台。",
            completer=_fake(summary),
        )
    )
    prompts = {row["messages"][1]["content"] for row in summary}
    assert len(prompts) == 1
    prompt = prompts.pop()
    assert "续写站台那一段" in prompt
    assert "节拍表" in prompt
    assert "她走进了站台" in prompt


def test_build_messages_is_a_pure_helper():
    messages = build_candidate_messages(task="rewrite", instruction="改得更冷")
    assert messages[0]["role"] == "system"
    assert "改得更冷" in messages[1]["content"]


def test_missing_api_key_returns_error_without_any_request():
    """没有 key 且没注入 completer：直接返回 error 信封，不发网络请求、不抛异常。"""
    result = asyncio.run(
        generate_candidates(
            DeepSeekConfig(apiKey=""),
            _project([_ch("ch1", [_d("lin", "嗯。")])]),
            task="continue",
            instruction="续写",
            n=3,
        )
    )
    assert result["error"]
    assert result["candidates"] == []


def test_invalid_n_is_refused_without_sampling():
    summary: List[Dict[str, Any]] = []
    result = asyncio.run(
        generate_candidates(
            CONFIG,
            _project([_ch("ch1", [_d("lin", "嗯。")])]),
            task="continue",
            instruction="续写",
            n=0,
            completer=_fake(summary),
        )
    )
    assert result["error"]
    assert result["candidates"] == []
    assert summary == []


def test_one_failed_candidate_does_not_block_the_others():
    summary: List[Dict[str, Any]] = []
    completer = _by_temperature(summary, {0.86: RuntimeError("上游 500")}, CLEAN)
    result = asyncio.run(
        generate_candidates(
            CONFIG,
            _project([_ch("ch1", [_d("lin", "嗯。")])]),
            task="continue",
            instruction="续写",
            n=3,
            completer=completer,
        )
    )
    assert len(summary) == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    failed = [c for c in result["candidates"] if c["error"]]
    assert len(failed) == 1
    assert "上游 500" in failed[0]["error"]
    assert all(not c["error"] for c in result["candidates"] if c["temperature"] != 0.86)


def test_total_failure_returns_error_instead_of_raising():
    summary: List[Dict[str, Any]] = []
    completer = _by_temperature(summary, {}, RuntimeError("全部超时"))
    result = asyncio.run(
        generate_best_candidates(
            CONFIG,
            _project([_ch("ch1", [_d("lin", "嗯。")])]),
            task="continue",
            instruction="续写",
            n=3,
            completer=completer,
        )
    )
    assert result["error"]
    assert result["candidates"] == []
    assert result["succeeded"] == 0
    assert result["failed"] == 3
    assert result["cost"]["modelCalls"] == 3


# ------------------------------------------------------------------ 打分阶段


def test_score_is_deterministic_and_keeps_every_raw_number():
    project = _project([_ch("ch1", [_d("lin", t) for t in LACONIC])])
    first = score_candidate(CLEAN, project, beat_sheet=BEAT_SHEET, instruction="约 300 字")
    second = score_candidate(CLEAN, project, beat_sheet=BEAT_SHEET, instruction="约 300 字")
    assert first == second
    for key in (
        "lintError",
        "lintWarn",
        "lintPass",
        "beatCoverage",
        "voiceDrift",
        "aiFlavor",
        "lengthOk",
        "score",
    ):
        assert key in first, key
    assert 0.0 <= first["score"] <= 1.0
    assert first["lintPass"] is True
    assert first["hardErrorCount"] == 0


def test_hard_error_collapses_the_score_to_zero():
    project = _project([_ch("ch1", [_d("lin", t) for t in LACONIC])])
    dirty = score_candidate(DIRTY, project, beat_sheet=BEAT_SHEET, instruction="约 300 字")
    clean = score_candidate(CLEAN, project, beat_sheet=BEAT_SHEET, instruction="约 300 字")
    assert dirty["lintError"] >= 1
    assert dirty["score"] == 0.0
    assert clean["score"] > dirty["score"]
    assert any("一票否决" in note for note in dirty["notes"])


def test_empty_draft_is_treated_as_a_hard_error():
    """空稿在体检里 errorCount 是 0（两套 lint 对空文本都直接返回），必须显式压到 0 分。"""
    project = _project([_ch("ch1", [_d("lin", t) for t in LACONIC])])
    empty = score_candidate("   ", project, beat_sheet=BEAT_SHEET, instruction="续写")
    assert empty["empty"] is True
    assert empty["score"] == 0.0
    assert empty["lintPass"] is False
    assert empty["hardErrorCount"] >= 1


def test_beat_term_only_participates_when_a_beat_sheet_is_given():
    project = _project([_ch("ch1", [_d("lin", t) for t in LACONIC])])
    without = score_candidate(CLEAN, project, instruction="续写")
    with_sheet = score_candidate(CLEAN, project, beat_sheet=BEAT_SHEET, instruction="续写")
    assert without["beatCoverage"]["checked"] is False
    assert without["beatCoverage"]["penalty"] is None
    assert "beat" not in without["weights"]  # 不参与，且权重不会被它平白放大
    assert with_sheet["beatCoverage"]["checked"] is True
    assert with_sheet["beatCoverage"]["total"] == 2
    assert with_sheet["beatCoverage"]["covered"] == 2
    assert with_sheet["weights"]["beat"] > 0


def test_missing_beats_lower_the_score():
    project = _project([_ch("ch1", [_d("lin", t) for t in LACONIC])])
    covered = score_candidate(CLEAN, project, beat_sheet=BEAT_SHEET, instruction="续写")
    hair = "林夏: 今天天很好。\n周屿: 是啊。\n旁白: 什么都没有发生。\n"
    missed = score_candidate(hair * 6, project, beat_sheet=BEAT_SHEET, instruction="续写")
    assert missed["beatCoverage"]["covered"] == 0
    assert missed["beatCoverage"]["errorCount"] >= 1
    assert missed["score"] < covered["score"]


def test_voice_drift_is_measured_for_the_character_that_appears():
    """寡言的角色被写成话密：声线项必须参与并给出偏离值（最差的那个角色）。"""
    project = _project([_ch("ch1", [_d("lin", t) for t in LACONIC])])
    verbose = (
        "林夏: 我今天在车站等了三个小时呢，结果什么也没等到，真是的。\n"
        "林夏: 你要是不来的话，我就一直等下去哦，反正我也没什么别的地方可以去嘛。\n"
        "林夏: 说起来啊，那天的雨其实挺大的，我站在檐下看了很久，心里有点乱。\n"
    )
    voiced = score_candidate(verbose, project, instruction="续写")
    assert voiced["voiceDrift"]["checked"] is True
    assert voiced["voiceDrift"]["worstName"] == "林夏"
    assert voiced["voiceDrift"]["worst"] > 0
    assert "voice" in voiced["weights"]


def test_voice_term_skips_characters_without_a_usable_profile():
    """台词不足以建画像的角色不参与，且如实说明是"跳过"而不是给 0 分。"""
    project = _project(
        [_ch("ch1", [_d("lin", "嗯。"), _d("lin", "走。")])],
        characters=[
            {"id": "lin", "defineName": "lin", "displayName": "林夏"},
        ],
    )
    row = score_candidate("林夏: 我今天在车站等了三个小时呢，结果什么也没等到。\n", project)
    assert row["voiceDrift"]["checked"] is False
    assert row["voiceDrift"]["rows"][0]["ready"] is False
    assert "voice" not in row["weights"]


def test_length_band_follows_the_instruction_and_penalizes_short_drafts():
    project = _project([_ch("ch1", [_d("lin", t) for t in LACONIC])])
    long_enough = score_candidate(CLEAN, project, instruction="约 300 字")
    tiny = score_candidate("林夏: 嗯。\n", project, instruction="约 300 字")
    assert long_enough["lengthOk"]["ok"] is True
    assert long_enough["lengthOk"]["source"] == "instruction(约数)"
    assert tiny["lengthOk"]["ok"] is False
    assert tiny["lengthOk"]["verdict"] == "偏短"
    assert tiny["lengthOk"]["penalty"] > 0
    assert tiny["score"] < long_enough["score"]


def test_ai_flavor_issues_are_counted_separately():
    """套话/AI 味单独计数：作者要能看出"这份扣分是因为一股 AI 味"。"""
    project = _project([_ch("ch1", [_d("lin", t) for t in LACONIC])])
    cliche = "旁白: 他微微一笑，不禁想起往事，涌上心头。\n" * 3
    row = score_candidate(cliche * 4, project, instruction="续写")
    assert row["aiFlavor"]["count"] >= 1
    assert all(code for code in row["aiFlavor"]["codes"])
    assert row["penalties"]["aiFlavor"] > 0


def test_count_chars_matches_the_shared_word_count_convention():
    assert count_chars("林夏") == 2
    assert count_chars("abc def") == 2
    assert count_chars("") == 0


def test_weights_add_up_so_a_hard_error_always_loses():
    """权重表的自检：软项之和 = 1.0 = 硬错误权重，这是"一票否决"成立的算术前提。"""
    assert abs(sum(SOFT_WEIGHTS.values()) - 1.0) < 1e-9


# ------------------------------------------------------------------ 排序阶段


def test_rank_picks_the_clean_draft_over_a_dirty_one():
    summary: List[Dict[str, Any]] = []
    # 最"中规中矩"的基础温度那一档返回带 error 的稿子 —— 它绝不能成为 winner。
    completer = _by_temperature(summary, {0.78: DIRTY}, CLEAN)
    result = asyncio.run(
        generate_best_candidates(
            CONFIG,
            _project([_ch("ch1", [_d("lin", t) for t in LACONIC])]),
            task="continue",
            instruction="约 300 字",
            n=3,
            beat_sheet=BEAT_SHEET,
            completer=completer,
        )
    )
    assert len(summary) == 3
    dirty_rows = [c for c in result["candidates"] if c["text"] == DIRTY]
    assert len(dirty_rows) == 1
    assert dirty_rows[0]["score"] == 0.0
    assert dirty_rows[0]["hardErrorCount"] >= 1
    assert dirty_rows[0]["rank"] == 3
    assert result["winner"]["text"] == CLEAN
    assert result["winner"]["rank"] == 1
    assert result["winner"]["score"] > 0
    assert "一票否决" in dirty_rows[0]["whyNotWinner"]


def test_rank_reason_is_chinese_and_cites_concrete_evidence():
    summary: List[Dict[str, Any]] = []
    result = asyncio.run(
        generate_best_candidates(
            CONFIG,
            _project([_ch("ch1", [_d("lin", t) for t in LACONIC])]),
            task="continue",
            instruction="约 300 字",
            n=2,
            beat_sheet=BEAT_SHEET,
            completer=_fake(summary),
        )
    )
    reason = result["reason"]
    assert isinstance(reason, str) and reason
    assert reason.startswith("第 1 份：")
    assert "error 级问题" in reason
    assert "节拍覆盖 2/2" in reason
    assert "AI 味" in reason
    assert "长度" in reason
    assert any("\u4e00" <= ch <= "\u9fff" for ch in reason)


def test_rank_reports_why_the_losers_lost():
    low = {"index": 1, "score": 0.5, "hardErrorCount": 0, "lintError": 0}
    high = {"index": 2, "score": 0.9, "hardErrorCount": 0, "lintError": 0}
    bad = {"index": 3, "score": 0.0, "hardErrorCount": 2, "lintError": 2}
    result = rank_candidates([low, high, bad])
    assert [row["index"] for row in result["ranked"]] == [2, 1, 3]
    assert result["winner"]["index"] == 2
    losers = {row["index"]: row["whyNotWinner"] for row in result["ranked"][1:]}
    assert "总分低" in losers[1]
    assert "一票否决" in losers[3]


def test_rank_prefers_fewer_hard_errors_before_score():
    """两份都是 0 分时，仍要按硬错误多少分高下（作者看到的是一个有序列表）。"""
    worse = {"index": 1, "score": 0.0, "hardErrorCount": 3, "lintError": 3}
    better = {"index": 2, "score": 0.0, "hardErrorCount": 1, "lintError": 1}
    result = rank_candidates([worse, better])
    assert result["winner"]["index"] == 2
    assert "被一票否决" in result["ranked"][1]["whyNotWinner"]


def test_rank_on_empty_input_is_safe():
    result = rank_candidates([])
    assert result["ranked"] == []
    assert result["winner"] is None
    assert "没有可比较的候选" in result["reason"]


# ------------------------------------------------------------------ 主入口


def test_best_entry_reports_n_success_scores_and_cost_us_notice():
    summary: List[Dict[str, Any]] = []
    completer = _by_temperature(summary, {0.86: RuntimeError("温度太高被拒")}, CLEAN)
    result = asyncio.run(
        generate_best_candidates(
            CONFIG,
            _project([_ch("ch1", [_d("lin", t) for t in LACONIC])]),
            task="continue",
            instruction="约 300 字",
            n=3,
            beat_sheet=BEAT_SHEET,
            completer=completer,
        )
    )
    assert result["n"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert result["failures"][0]["temperature"] == 0.86
    assert all("score" in row and "reason" in row for row in result["candidates"])
    assert all("evidence" in row for row in result["candidates"])
    assert result["cost"]["modelCalls"] == 3
    assert result["cost"]["multiplier"] == 3
    assert "3 倍" in result["cost"]["note"]
    assert result["scoring"]["deterministic"] is True


def test_best_entry_defaults_to_three_candidates():
    summary: List[Dict[str, Any]] = []
    result = asyncio.run(
        generate_best_candidates(
            CONFIG,
            _project([_ch("ch1", [_d("lin", t) for t in LACONIC])]),
            task="continue",
            instruction="续写",
            completer=_fake(summary),
        )
    )
    assert result["n"] == DEFAULT_CANDIDATES == 3
    assert len(summary) == 3


def test_base_temperature_override_is_respected():
    summary: List[Dict[str, Any]] = []
    result = asyncio.run(
        generate_candidates(
            CONFIG,
            _project([_ch("ch1", [_d("lin", t) for t in LACONIC])]),
            task="continue",
            instruction="续写",
            n=3,
            base_temperature=0.6,
            completer=_fake(summary),
        )
    )
    assert result["baseTemperature"] == 0.6
    assert result["temperatures"] == [0.52, 0.6, 0.68]


def test_best_entry_survives_a_completer_that_returns_a_bad_shape():
    """假 completer 返回 None（模型侧异常形态）时同样只记 error，不影响其它候选。"""
    summary: List[Dict[str, Any]] = []
    result = asyncio.run(
        generate_best_candidates(
            CONFIG,
            _project([_ch("ch1", [_d("lin", t) for t in LACONIC])]),
            task="continue",
            instruction="续写",
            n=3,
            completer=_by_temperature(summary, {0.7: None}, CLEAN),
        )
    )
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert result["winner"]["text"] == CLEAN
