"""给应用自己的 logger 挂上真实可见的 handler。

背景（线上实测）：容器里只有 ``vnss.access`` 的日志真的落盘，其它模块用
``logging.getLogger(__name__)`` 拿到的 logger 写出来的东西**全部消失**——包括
安全审计日志 ``security login_failed`` 和排查用的 ``resend noop``。结果就是用户
反馈「收不到验证邮件」时，服务端一点线索都没留下（本次排查只能靠 DB 反推）。

原因与 ``vnss.access`` 相同：uvicorn 在导入应用之后才执行自己的 dictConfig，
导入期创建的 logger 的级别/handler 会被重置掉。显式挂 StreamHandler +
``propagate = False`` 就不再看别人的脸色。

用法::

    from app.core.app_logging import app_logger
    logger = app_logger("vnss.auth")
"""

from __future__ import annotations

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def app_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """幂等地返回一个自带 handler、不吃 root 配置的 logger。"""
    lg = logging.getLogger(name)
    if not lg.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        lg.addHandler(handler)
    lg.setLevel(level)
    lg.propagate = False
    # uvicorn 的 dictConfig 可能把导入期创建的 logger 置为 disabled —— 显式打开。
    lg.disabled = False
    return lg
