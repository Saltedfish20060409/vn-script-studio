"""`logprobs` 的开关方向：**未知模型默认不发**（与 `response_format` 相反）。

为什么值得单独钉住：两种参数发错时的代价不对称——
- `response_format` 不被支持时只是少一条服务端约束（提示词里本来就写着"只输出 JSON"），
  所以未知模型保留原行为更安全（见 `supports_json_mode`）；
- `logprobs` 不被支持时，未知**参数**会把整个请求打成 400。那是"为了一个可选信号
  把主功能弄挂"，绝不可以。

`logprobs` 的用途只有一个：给多变体取舍提供"模型自身置信度"（Best-of-N /
self-certainty，见 `core/variant_select.py`）。拿不到就是"未测量"，取舍退回
一致性 + 确定性检查，功能不受影响。
"""
from __future__ import annotations

import httpx
import pytest

from app.core.ai import DeepSeekConfig
from app.core.llm_http import DEFAULT_TOP_LOGPROBS, _chat_body, response_logprobs
from app.core.model_presets import supports_logprobs

_MESSAGES = [{"role": "user", "content": "hi"}]


def _config(model: str) -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test", baseUrl="https://api.example.com", model=model)


def _body(model: str, **kwargs) -> dict:
    _model, body = _chat_body(
        _config(model),
        messages=_MESSAGES,
        temperature=0.7,
        response_format=None,
        max_tokens=None,
        stream=False,
        **kwargs,
    )
    return body


# ---- 能力表 ------------------------------------------------------------------


def test_supports_logprobs_is_false_by_default():
    """认不出来一律 False：发错参数会 400，代价太大。"""
    assert supports_logprobs("") is False
    assert supports_logprobs("my-custom-model") is False
    assert supports_logprobs("glm-5.3") is False
    # 思考档与 logprobs 的组合未经验证，所以也不标
    assert supports_logprobs("deepseek-flash-think") is False


def test_supports_logprobs_is_true_for_verified_deepseek_tiers():
    assert supports_logprobs("deepseek-flash") is True
    assert supports_logprobs("deepseek-v4-flash") is True
    assert supports_logprobs("deepseek-v4-pro") is True


# ---- 出站请求体 --------------------------------------------------------------


def test_supported_model_gets_logprobs_with_default_topk():
    body = _body("deepseek-flash", logprobs=True)
    assert body["logprobs"] is True
    assert body["top_logprobs"] == DEFAULT_TOP_LOGPROBS


def test_topk_is_clamped_to_a_sane_range():
    assert _body("deepseek-flash", logprobs=True, top_logprobs=1)["top_logprobs"] == 2
    assert _body("deepseek-flash", logprobs=True, top_logprobs=999)["top_logprobs"] == 20


def test_unsupported_model_never_gets_the_keys():
    for model in ("glm-5.3", "my-custom-model", "deepseek-flash-think", ""):
        body = _body(model, logprobs=True)
        assert "logprobs" not in body, model
        assert "top_logprobs" not in body, model


def test_not_requested_means_not_sent():
    body = _body("deepseek-flash")
    assert "logprobs" not in body and "top_logprobs" not in body


def test_streaming_never_gets_logprobs():
    """流式响应的 logprobs 形状不同（增量里带），我们没有解析它——所以干脆不发。"""
    _model, body = _chat_body(
        _config("deepseek-flash"),
        messages=_MESSAGES,
        temperature=0.7,
        response_format=None,
        max_tokens=None,
        stream=True,
        logprobs=True,
    )
    assert "logprobs" not in body


# ---- 读响应 ------------------------------------------------------------------


def _response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
    )


def test_response_logprobs_reads_first_choice():
    payload = {
        "choices": [
            {"message": {"content": "甲"}, "logprobs": {"content": [{"token": "甲", "logprob": -0.1}]}}
        ]
    }
    assert response_logprobs(_response(payload)) == {"content": [{"token": "甲", "logprob": -0.1}]}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": "甲"}}]},
        {"choices": [{"message": {"content": "甲"}, "logprobs": None}]},
    ],
)
def test_response_logprobs_is_none_when_absent(payload):
    assert response_logprobs(_response(payload)) is None


def test_response_logprobs_tolerates_non_json_body():
    """上游返回 HTML 错误页时不能因此炸掉：这里只负责取值，解析失败就是"没有"。"""
    res = httpx.Response(
        200, text="<html>oops</html>", request=httpx.Request("POST", "https://api.example.com")
    )
    assert response_logprobs(res) is None
