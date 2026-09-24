"""纯函数测试：标记批改的提示词拼装、模型输出清理，以及多变体的按证据取舍。

多变体那一组会 patch 掉 `chat_completions`（不发真请求），验的是**调用形状**：
N 次并发独立采样、温度铺开、logprobs 只在支持的档位上要、结果按证据排序。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest

from app.core.ai import DeepSeekConfig
from app.core.mark_revise import (
    _CONTEXT_CAP,
    _QUOTE_CAP,
    build_mark_messages,
    clean_model_text,
    parse_variants,
    revise_marked_text,
)


def test_parse_variants_reads_json_and_cleans_it():
    """模型自作主张返回 JSON 时取正文，绝不把一整段 JSON 交给作者。"""
    raw = '```json\n{"variants": ["改后一。", "「改后二。」"]}\n```'
    assert parse_variants(raw) == ["改后一。"]
    assert parse_variants('{"text": "他把手举到眼前。"}') == ["他把手举到眼前。"]
    assert parse_variants('{"replacement": "他把手举到眼前。"}') == ["他把手举到眼前。"]


def test_parse_variants_falls_back_to_single_when_model_ignores_json():
    # 模型不听话时宁可只给一版，也不能让作者什么都拿不到
    assert parse_variants("他就那样站着，没动。") == ["他就那样站着，没动。"]


def test_parse_variants_handles_single_mode_and_garbage():
    assert parse_variants("改后：他把手举到眼前。") == ["他把手举到眼前。"]
    assert parse_variants("") == []
    # 明确声明了 variants 却没有内容 → 返回空，而不是把 JSON 当正文
    assert parse_variants('{"variants": []}') == []
    assert parse_variants('{"variants": "不是列表"}') == []



def _user_text(messages) -> str:
    return [m for m in messages if m["role"] == "user"][0]["content"]


def _system_text(messages) -> str:
    return [m for m in messages if m["role"] == "system"][0]["content"]


def test_rewrite_prompt_carries_context_and_asks_for_one_paragraph_only():
    messages = build_mark_messages(
        quote="他慢慢抬起手，举到眼前。",
        prefix="窗外的雾在退。",
        suffix="那双手不是他的。",
        instruction="改得更冷、更短",
        intent="rewrite",
        style_guide="你习惯短句，避免四字格。",
    )
    system = _system_text(messages)
    user = _user_text(messages)

    # 范围约束是这类批改的核心：只输出这一段
    assert "只输出" in system
    assert "其余一字不动" in system
    # 上下文与要求都要带上
    assert "窗外的雾在退。" in user
    assert "他慢慢抬起手，举到眼前。" in user
    assert "那双手不是他的。" in user
    assert "改得更冷、更短" in user
    # 作者文风记忆要被注入（贴作者自己的腔调）
    assert "你习惯短句" in user


def test_advice_mode_forbids_rewriting():
    messages = build_mark_messages(quote="他感到一阵说不清的恐惧。", intent="advice")
    system = _system_text(messages)
    assert "不要改写正文" in system
    assert "只输出建议本身" in system
    # 建议模式不该出现"输出改写后的这一段"这类指令
    assert "只输出正文那一段" not in system


def test_missing_instruction_falls_back_to_default_goal():
    user = _user_text(build_mark_messages(quote="随便一句。"))
    assert "没写具体要求" in user
    assert "更具体" in user


def test_long_inputs_are_clipped_to_bounds():
    user = _user_text(
        build_mark_messages(
            quote="字" * 5000,
            prefix="前" * 5000,
            suffix="后" * 5000,
            instruction="要" * 5000,
            style_guide="风" * 5000,
        )
    )
    assert "字" * _QUOTE_CAP in user
    assert "字" * (_QUOTE_CAP + 1) not in user
    assert "前" * (_CONTEXT_CAP + 1) not in user
    assert "后" * (_CONTEXT_CAP + 1) not in user


def test_clean_model_text_strips_common_wrappers():
    assert clean_model_text("改后：他把手举到眼前。") == "他把手举到眼前。"
    assert clean_model_text("```\n他把手举到眼前。\n```") == "他把手举到眼前。"
    assert clean_model_text("“他把手举到眼前。”") == "他把手举到眼前。"
    assert clean_model_text("「他把手举到眼前。」") == "他把手举到眼前。"
    # 正常文本不动
    assert clean_model_text("他把手举到眼前。") == "他把手举到眼前。"
    # 只有一侧有引号时不剥（避免误伤正文里的引号）
    assert clean_model_text("“他说。") == "“他说。"


# ---- 多变体：并发独立采样 + 按证据排序 ----------------------------------------


def _cfg(model: str = "deepseek-flash") -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test", baseUrl="https://api.example.com", model=model)


def _response(text: str, *, logprobs: dict | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "deepseek-flash",
            "choices": [{"message": {"content": text}, "logprobs": logprobs}],
        },
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
    )


def _peaked(token_count: int = 40) -> dict:
    return {
        "content": [
            {
                "token": "他",
                "logprob": -0.01,
                "top_logprobs": [
                    {"token": "他", "logprob": -0.01},
                    {"token": "她", "logprob": -7.0},
                ],
            }
            for _ in range(token_count)
        ]
    }


def _flat(token_count: int = 40) -> dict:
    return {
        "content": [
            {
                "token": "的",
                "logprob": -1.1,
                "top_logprobs": [
                    {"token": "的", "logprob": -1.09},
                    {"token": "地", "logprob": -1.11},
                ],
            }
            for _ in range(token_count)
        ]
    }


QUOTE = "他慢慢抬起手，举到眼前。"


def _run_multi(replies, *, model: str = "deepseek-flash", want: int = 3, names=None):
    """跑多变体路径并记录每次调用的形状。"""
    calls = []
    in_flight = {"now": 0, "peak": 0}

    async def fake(config, *, messages, **kwargs):  # noqa: ANN001, ANN003
        # 索引必须在 await **之前**取：三次任务并发时，await 之后再取会拿到同一个值
        index = len(calls)
        calls.append({"messages": messages, **kwargs})
        in_flight["now"] += 1
        in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
        await asyncio.sleep(0)  # 让出控制权：三次调用必须真的并发
        in_flight["now"] -= 1
        return replies[index % len(replies)]

    async def _go():
        with patch("app.core.mark_revise.chat_completions", fake):
            return await revise_marked_text(
                _cfg(model), quote=QUOTE, instruction="更冷", candidates=want, names=names
            )

    return asyncio.run(_go()), calls, in_flight


def test_multi_variant_samples_independently_and_concurrently():
    """多变体 = N 次**独立**采样（并发）：每版有自己的采样分布，才能按置信度取舍。"""
    replies = [_response("他抬起手。"), _response("他把手举到眼前，停住。"), _response("他抬手。")]
    result, calls, in_flight = _run_multi(replies)
    assert result.error is None
    assert len(calls) == 3
    assert in_flight["peak"] == 3, "三次采样没有并发"
    # 温度铺开（否则 N 版会很像）
    temps = sorted(c["temperature"] for c in calls)
    assert len(set(temps)) == 3
    # 提示词里**不再**要求"一次给 N 版 JSON"（那条路没有每版自己的分布）
    assert all("variants" not in c["messages"][1]["content"] for c in calls)
    assert all(len(c["messages"]) == 2 for c in calls)


def test_multi_variant_requests_logprobs_only_when_supported():
    replies = [_response("他抬起手。", logprobs=_peaked()), _response("他抬手。", logprobs=_flat())]
    _, calls, _ = _run_multi(replies, model="deepseek-flash", want=2)
    assert all(c["logprobs"] is True for c in calls)

    _, unsupported, _ = _run_multi(replies, model="glm-5.3", want=2)
    assert all(c["logprobs"] is False for c in unsupported)
    # 事实核对：`top_logprobs` 由 `_chat_body` 填默认值（见 tests/test_llm_logprobs.py），
    # 调用点只负责表达"我要这个信号"。
    assert all("top_logprobs" not in c for c in calls)


def test_multi_variant_picks_the_best_evidenced_version():
    """回归：过去 `replacement = variants[0]`——取"模型先写的那版"，与质量无关。"""
    bad = "他慢慢抬起手，举到眼前。" * 4  # 长度失控（确定性检查会抓到）
    good = "他抬起手，停在眼前。"
    replies = [_response(bad), _response(good), _response(bad)]
    result, _, _ = _run_multi(replies)
    assert result.replacement == good
    assert result.candidates[0] == good, "候选要按证据排序，第一版即 winner"
    assert result.ranking and result.ranking[0]["recommended"] is True
    assert result.ranking[0]["rank"] == 1
    assert "第" in result.selectionNote and "总分" in result.selectionNote


def test_multi_variant_uses_confidence_when_checks_all_pass():
    """两版都没问题时，模型自身置信度就是区分依据（论文的 Best-of-N 结论）。"""
    text = "他抬起手，停在眼前。"
    replies = [_response(text, logprobs=_flat()), _response(text, logprobs=_peaked())]
    result, _, _ = _run_multi(replies, want=2)
    assert result.replacement == text
    scores = {row["variantIndex"]: row["score"] for row in result.ranking}
    assert scores[1] > scores[0]
    assert result.ranking[0]["variantIndex"] == 1
    assert result.ranking[0]["certainty"]["kind"] == "topk-proxy"


def test_multi_variant_reports_unmeasured_signals():
    """拿不到 logprobs 时是"未测量"，不是 0 分——说明里要写出来。"""
    replies = [_response("他抬起手。"), _response("他抬手。")]
    result, _, _ = _run_multi(replies, model="glm-5.3", want=2)
    assert all(row["certainty"] is None for row in result.ranking)
    assert "未测量" in result.selectionNote
    # 两份候选：没有多数可依，一致性也不参与
    assert "没有多数可依" in result.selectionNote


def test_multi_variant_survives_partial_failures():
    replies = [_response("他抬起手。"), _response(""), _response("他抬起了手。")]

    async def fake(config, *, messages, **kwargs):  # noqa: ANN001, ANN003
        return replies.pop(0)

    async def _go():
        with patch("app.core.mark_revise.chat_completions", fake):
            return await revise_marked_text(_cfg(), quote=QUOTE, candidates=3)

    result = asyncio.run(_go())
    assert result.error is None
    assert len(result.candidates) == 2, "空响应那一版要被丢掉，其余照常"
    assert all(c.strip() for c in result.candidates)


def test_multi_variant_all_failed_reports_error():
    async def fake(config, *, messages, **kwargs):  # noqa: ANN001, ANN003
        return _response("")

    async def _go():
        with patch("app.core.mark_revise.chat_completions", fake):
            return await revise_marked_text(_cfg(), quote=QUOTE, candidates=3)

    result = asyncio.run(_go())
    assert result.error and "没有返回内容" in result.error


def test_advice_mode_still_makes_exactly_one_call():
    calls = []

    async def fake(config, *, messages, **kwargs):  # noqa: ANN001, ANN003
        calls.append(kwargs)
        return _response("这里的问题是形容词堆砌。")

    async def _go():
        with patch("app.core.mark_revise.chat_completions", fake):
            return await revise_marked_text(_cfg(), quote=QUOTE, intent="advice", candidates=3)

    result = asyncio.run(_go())
    assert len(calls) == 1, "建议模式不该走多变体"
    assert result.advice


def test_single_variant_path_still_retries_with_problems_fed_back():
    """单版路径不变：自检发现问题 → 带上问题再改一次（模型给了干净版本就用它）。"""
    calls = []

    async def fake(config, *, messages, **kwargs):  # noqa: ANN001, ANN003
        calls.append(messages)
        if len(calls) == 1:
            return _response("他慢慢抬起手，举到眼前。" * 4)
        return _response("他抬起手，停在眼前。")

    async def _go():
        with patch("app.core.mark_revise.chat_completions", fake):
            return await revise_marked_text(_cfg(), quote=QUOTE, candidates=1, names=["林夏"])

    result = asyncio.run(_go())
    assert len(calls) == 2
    assert "上一版的问题" in calls[1][1]["content"]
    assert result.replacement == "他抬起手，停在眼前。"
    assert result.warnings == []


def test_variant_count_is_clamped_to_three():
    replies = [_response("他抬起手。")]
    _, calls, _ = _run_multi(replies, want=99)
    assert len(calls) == 3


@pytest.mark.parametrize("bad", [0, -5, "x"])
def test_variant_count_falls_back_to_one(bad):
    replies = [_response("他抬起手。")]
    _, calls, _ = _run_multi(replies, want=bad)
    assert len(calls) == 1

