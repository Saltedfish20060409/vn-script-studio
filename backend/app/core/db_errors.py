"""把"数据库拒绝写入"（DataError）翻译成用户能读懂的一句话。

**为什么单独一个模块**：翻译逻辑是纯函数，能离线测；而挂 handler 的
`app/main.py` 需要真实数据库才能跑到。实盘见 main.py 的 `_data_error_handler`：

2026-09-26 线上，用户在「类型 / 题材」贴了一段长文本，Postgres 报
`value too long for type character varying(128)`，SQLAlchemy 抛 DataError，
没人接 → 500，响应体只有一句 `Internal Server Error`。界面显示「保存失败」，
用户既不知道哪一项有问题、也永远修不好。
"""

from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.app_logging import app_logger

_VARCHAR_LIMIT = re.compile(
    r"value too long for type character varying\((\d+)\)", re.IGNORECASE
)


def describe_data_error(exc: BaseException) -> str:
    """DataError → 一句人话（含"最多多少字符"这种可执行的信息）。"""
    raw = str(getattr(exc, "orig", None) or exc)

    matched = _VARCHAR_LIMIT.search(raw)
    if matched:
        return (
            f"有字段超出长度限制（这一列最多 {matched.group(1)} 个字符），"
            "这次保存被拒绝：请精简后再保存。"
        )
    if "numeric field overflow" in raw or "out of range" in raw:
        return "有数值超出允许范围，这次保存被拒绝：请检查填的数字。"
    if "invalid input syntax" in raw:
        return "有字段的格式不被接受，这次保存被拒绝：请检查格式后重试。"
    if "null value in column" in raw:
        return "有必填字段是空的，这次保存被拒绝：请补上再保存。"
    return "这次保存被数据库拒绝了（数据超出允许的长度或范围），请精简后重试。"


def data_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI 的 DataError 处理器：400 + 人话，同时把真实异常打进日志。

    放在这里（而不是塞在 create_app 里的闭包）是为了能**离线测**：
    这个兜底本身不该只有出事那天才第一次被执行到。
    """
    detail = describe_data_error(exc)
    app_logger("vnss.dbguard").error(
        "db rejected write: %s %s -> %s",
        getattr(request, "method", "?"),
        getattr(getattr(request, "url", None), "path", "?"),
        exc,
    )
    return JSONResponse(status_code=400, content={"detail": detail})
