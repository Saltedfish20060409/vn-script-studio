"""自定义接口地址的两道检查：保存时查形状、请求时查 DNS。

为什么要分两道（这里就是线上的那次教训）：
- 账号存储模式下 Base URL 曾经**存不进去**（前端键名写错，见
  `test_settings_put_contract.py`），于是地址一直是建表默认值，用户填的从未生效；
- 修好之后还有第二个坑：地址能存进去了，但如果它不是 https 公网地址，
  **请求时**会被安全守卫拦下并静默换成服务端地址——用户看到"保存成功、
  当前生效却是另一个域名"。所以保存时先用 `https_url_shape_ok` 拦明显用不了的写法。

`https_url_shape_ok` 故意**不查 DNS**：保存设置不该因为一次 DNS 抖动失败，
测试里也不该依赖某个域名解析得出来（那会让这条守卫变成看网络脸色）。
真正的安全边界是请求时的 `_is_safe_base_url`（含 DNS），本文件也把它的边界钉住。
"""

from __future__ import annotations

import pytest

from app.core.llm_client_override import (
    _is_safe_base_url,
    https_url_shape_ok,
    merge_llm_credentials,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.deepseek.com",
        "https://api.deepseek.com/v1",
        "https://relay.example.test/v1",
        "https://open.bigmodel.cn/api/paas/v4",
        "  https://api.moonshot.cn  ",  # 前后空格要能容忍
    ],
)
def test_shape_accepts_public_https_urls(url):
    assert https_url_shape_ok(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "http://api.deepseek.com",  # 非 https
        "api.deepseek.com",  # 漏了 scheme
        "https://localhost",  # 单标签、且是环回
        "http://localhost:11434",  # 本机 Ollama：服务端连不上，必须明说
        "https://192.168.1.10/v1",  # 内网
        "https:///v1",  # 没有主机名
        "ftp://api.deepseek.com",
    ],
)
def test_shape_rejects_obviously_unusable_urls(url):
    """保存时能拦下的写法——每一条在请求时都会被静默替换掉，所以宁可当场报错。"""
    assert https_url_shape_ok(url) is False


def test_shape_is_deliberately_looser_than_the_request_time_guard():
    """两道检查的分工：请求时那道含 DNS，所以"形状对但解析不到"只在请求时被拦。"""
    unresolvable = "https://definitely-not-a-real-host.example.invalid/v1"
    assert https_url_shape_ok(unresolvable) is True
    assert _is_safe_base_url(unresolvable) is False


def test_request_time_guard_still_blocks_private_and_non_https():
    """请求时的边界不能因为加了保存时检查而放松。"""
    assert _is_safe_base_url("http://api.deepseek.com") is False
    assert _is_safe_base_url("https://localhost") is False
    assert _is_safe_base_url("https://127.0.0.1/v1") is False


def test_user_layer_url_is_bound_to_the_user_key():
    """用户层：地址没填时**回落**到服务端地址，但不会把别人的地址当自己的。

    这条记录的是现状（不是理想）：`user_llm_credentials` 会把空地址填成服务端地址，
    所以"只填了 Key 的用户"实际打的是服务端配的那个端点。
    记账意义在于：这是**刻意**的（DeepSeek/站内为默认预期），
    真要改成"没填地址就拒绝调用"是产品决定，改的时候这条测试会提醒你。
    """
    merged = merge_llm_credentials(
        override=None,
        user_creds={"api_key": "sk-user", "base_url": "", "model": "m"},
        server={"api_key": "sk-server", "base_url": "https://server.example", "model": "s"},
    )
    assert merged["source"] == "user"
    assert merged["api_key"] == "sk-user"
    assert merged["base_url"] == "https://server.example"
    # 空地址是"没填"，不是"被拒"——两者必须能区分，否则界面会误报
    assert merged["url_rejected"] == ""


def test_rejected_user_url_is_reported_not_silently_swapped():
    """用户填了地址但过不了守卫时，必须**留下痕迹**（`url_rejected`）。

    为什么要单独一个键：这通调用会改用服务端地址发出，而用户以为用的是自己的地址
    （真实反馈就是两行数字打架）。只靠前端比较域名去猜会误报；
    服务端在这里是**确切知道**自己丢了哪个地址的，所以由它告诉界面。
    """
    bad = "https://192.168.1.10/v1"  # 内网：守卫必拒
    merged = merge_llm_credentials(
        override=None,
        user_creds={"api_key": "sk-user", "base_url": bad, "model": "m"},
        server={"api_key": "sk-server", "base_url": "https://server.example", "model": "s"},
    )
    assert merged["base_url"] == "https://server.example"
    assert merged["url_rejected"] == bad
    assert merged["source"] == "user", "换了地址不等于换了谁的账户"


def test_rejected_client_url_is_reported_too():
    """浏览器层（本机存储）同样要留痕：那是用户此刻填在设置页里的地址。"""
    bad = "http://localhost:11434"
    merged = merge_llm_credentials(
        override={"api_key": "sk-client", "base_url": bad, "model": "m"},
        user_creds=None,
        server={"api_key": "sk-server", "base_url": "https://server.example", "model": "s"},
    )
    assert merged["source"] == "client"
    assert merged["url_rejected"] == bad


def test_healthy_url_is_not_reported_as_rejected():
    """能用的地址不能被误标成"被拒"——否则界面天天报一条假警报。"""
    merged = merge_llm_credentials(
        override=None,
        user_creds={"api_key": "sk-user", "base_url": "https://api.deepseek.com", "model": "m"},
        server={"api_key": "sk-server", "base_url": "https://server.example", "model": "s"},
    )
    assert merged["base_url"] == "https://api.deepseek.com"
    assert merged["url_rejected"] == ""


def test_server_layer_never_reports_a_rejection():
    """用站方 Key 时不看用户地址，也就不该报"你的地址被拒"。"""
    merged = merge_llm_credentials(
        override=None,
        user_creds=None,
        server={"api_key": "sk-server", "base_url": "https://server.example", "model": "s"},
    )
    assert merged["source"] == "server"
    assert merged["url_rejected"] == ""
