"""给应用自己的 logger 挂上真实可见的 handler。

背景（线上实测）：容器里只有 ``vnss.access`` 的日志真的落盘，其它模块写出来的东西
**全部消失**——包括安全审计日志 ``security login_failed``、验证邮件排查日志
``resend noop``、限流/向量检索的 warning。结果就是用户反馈「收不到验证邮件」时，
服务端一点线索都没留下（本次排查只能靠 DB 反推）。

根因（2026-09-13 实测确认，不是 uvicorn）：启动时 ``_alembic_upgrade_sync()`` 会
``alembic.config.Config("alembic.ini")``，而 alembic.ini 带 ``[loggers]`` 段，于是触发
``logging.config.fileConfig()`` —— 它默认 ``disable_existing_loggers=True``，把本进程里
所有不在 ini 里点名的 logger（我们全部的 app.* / vnss.*）**直接 disabled**，root 也被换成
WARN + console。``vnss.access`` 之所以侥幸活着，是因为访问日志中间件**每个请求**都重新取
一次 logger，等于顺手把状态恢复了。

所以：模块顶层调 app_logger() 不够（那时还没被 alembic 关掉），必须在 migrate 之后
调用 ``configure_app_loggers()`` 重新接管（见 app/main.py 的 lifespan）。

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
    # alembic 的 fileConfig 会把导入期创建的 logger 置为 disabled —— 显式打开。
    lg.disabled = False
    return lg


def configure_app_loggers(level: int = logging.INFO) -> list[str]:
    """在 **alembic 迁移之后**重新接管本进程里所有 app.* / vnss.* logger。

    alembic.ini 的 fileConfig 会把它们 disabled 掉（见模块 docstring），所以必须在
    lifespan 里、``_alembic_upgrade_sync()`` 之后调用。启动日志与测试可核对返回值。
    """
    names = []
    for name, obj in list(logging.Logger.manager.loggerDict.items()):
        if not isinstance(obj, logging.Logger):
            continue  # PlaceHolder：父级还没建出来
        if name == "app" or name.startswith(("app.", "vnss.")):
            app_logger(name, level=level)
            names.append(name)
    return sorted(names)
