"""设置页的"字段名契约"：前端送的键必须真的被后端 schema 接受。

**为什么专门一个文件**：这里踩过一次线上问题，而且是最难查的那种——**静默丢弃**。

现象（用户截图）：账号存储模式下，用户把 Base URL 填成 `https://api.mc08.eu.org/v1`、
模型名填成 `[反代][匿名]space-bunny`，保存后「当前生效」显示
`[反代][匿名]space-bunny @ api.deepseek.com`：模型名存进去了，**Base URL 没有**。

真因：`SettingsModal.persist()` 送的键是 `base_url`，而 `SettingsPutIn` 只声明了
`api_base_url`。Pydantic 默认忽略未知字段（不报错），于是这一项**被无声丢掉**，
接口照样返回 200、界面照样提示"已保存到账号"。模型名（`api_model`）名字对得上，
所以只有 URL 这一项丢——用户看到的就是"两行自相矛盾"。

后果不只是显示难看：`row.api_base_url` 一直停在建表默认值 `https://api.deepseek.com`，
于是**用户自己的 Key 被发到自己没有指定的域名**去（自己在界面上填的地址从未生效）。

所以这里用两条测试把契约钉住：
1. 前端 `persist()` 里 `putSettings({...})` 的顶层键集合，必须**全部**是
   `SettingsPutIn` 的字段（多一个都算错——未知键会被静默忽略）；
2. `SettingsPutIn` 对未知键的行为也要被显式记录下来：忽略而不是报错，
   这正是"必须靠测试而不是靠运行时才发现"的原因。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Set

from app.schemas import SettingsPutIn

FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
SETTINGS_MODAL = FRONTEND_SRC / "components" / "SettingsModal.tsx"


def _put_settings_body_keys(source: str, func: str = "putSettings") -> Set[str]:
    """取 `putSettings({ ... })` 实参对象字面量的**顶层**键。

    逐字符走一遍并数大括号深度：设置页这个实参里有三元表达式与函数调用，
    但对括号/引号是平衡的（`""` 这类空串不影响），所以深度 1 上的 `key:` 就是顶层键。
    不按缩进去猜：缩进会被人重排，重排一次守卫就悄悄失效了。
    """
    at = source.index(f"{func}({{")
    start = source.index("{", at)
    depth = 0
    end = start
    for i in range(start, len(source)):
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    body = source[start + 1 : end]
    # 去掉嵌套调用里的内容：这里没有嵌套对象，只需按行取 `key:` 形状的顶层键
    keys: Set[str] = set()
    for match in re.finditer(r"(?m)^\s*([a-z_][a-z0-9_]*)\s*:", body):
        keys.add(match.group(1))
    return keys


def test_frontend_persist_keys_are_all_accepted_by_the_schema():
    """前端保存凭据时送的每个键，后端 schema 都必须声明——否则就是静默丢弃。"""
    source = SETTINGS_MODAL.read_text(encoding="utf-8")
    keys = _put_settings_body_keys(source)
    assert keys, "没解析到 putSettings 的实参键，TS 结构可能变了"

    declared = set(SettingsPutIn.model_fields)
    unknown = sorted(keys - declared)
    assert not unknown, (
        f"这些键后端 schema 里没有，会被 Pydantic 静默忽略（保存看起来成功、其实没存）：{unknown}"
    )


def test_base_url_is_sent_under_the_name_the_backend_declares():
    """Base URL 必须以 `api_base_url` 送出。

    单独钉一条，是因为它就是那次线上问题的原样：写成 `base_url` 时上面那条
    "未知键"断言会红，但如果有人图省事把 `base_url` 加进 schema 当别名，
    这里会拦住——别名会让 `api_base_url` 与 `base_url` 两份真源长期并存。
    """
    source = SETTINGS_MODAL.read_text(encoding="utf-8")
    keys = _put_settings_body_keys(source)
    assert "api_base_url" in keys, f"Base URL 没有以 api_base_url 送出：{sorted(keys)}"
    assert "base_url" not in keys, "不要送 base_url：schema 里叫 api_base_url"


def test_unknown_keys_are_silently_ignored_by_design():
    """记录 Pydantic 的行为：未知键被忽略、不抛错。

    这条**不是**在赞同这个行为，而是把"为什么必须有上面那两条测试"写成可执行的说明：
    如果哪天 schema 改成 `extra="forbid"`，这条会红，那时应当把守卫改成
    "未知键会被 422 拒绝"——两种都可以，但必须有测试盯着。
    """
    relaxed = SettingsPutIn.model_validate({"base_url": "https://relay.example/v1"})
    assert relaxed.api_base_url is None
    typed = SettingsPutIn.model_validate({"api_base_url": "https://relay.example/v1"})
    assert typed.api_base_url == "https://relay.example/v1"
    # 其余键名一直是对的（模型名 / 窗口 / 评审档），钉住免得被"顺手改名"
    for key in ("api_key", "api_model", "api_context_window_k", "critic_api_key",
                "critic_api_base_url", "critic_api_model", "panel_glass", "bg_scrim"):
        assert key in SettingsPutIn.model_fields, f"schema 少了 {key}"
