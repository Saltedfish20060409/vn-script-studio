"""Tests: app logger 的可见性（线上踩过的坑：日志被 alembic.ini 的 fileConfig 吞掉）。"""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path

import pytest

from app.core.app_logging import app_logger, configure_app_loggers


def _reset(name: str) -> logging.Logger:
    lg = logging.getLogger(name)
    for handler in list(lg.handlers):
        lg.removeHandler(handler)
    lg.setLevel(logging.NOTSET)
    lg.propagate = True
    lg.disabled = False
    return lg


def test_app_logger_is_self_contained_and_idempotent():
    """自带 handler、不吃 root 配置，并且重复调用不会叠加 handler。"""
    _reset("vnss.test_auth_logging")
    once = app_logger("vnss.test_auth_logging")
    twice = app_logger("vnss.test_auth_logging")
    assert once is twice
    assert len(once.handlers) == 1
    assert once.level == logging.INFO
    assert once.propagate is False
    _reset("vnss.test_auth_logging")


def test_app_logger_reenables_disabled_logger():
    """被 dictConfig 关掉的 logger，再取一次要能重新写日志。"""
    lg = _reset("vnss.test_disabled")
    lg.disabled = True
    assert app_logger("vnss.test_disabled").disabled is False
    _reset("vnss.test_disabled")


def test_configure_app_loggers_undoes_alembic_fileconfig():
    """根因回归测试：alembic.ini 的 fileConfig 会关掉我们的 logger，必须能重新接管。

    线上「只有 vnss.access 有日志、安全审计与验证邮件排查全丢」就是这么来的。
    """
    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    if not ini.exists():
        # 在某些非常规布局下（例如只把 tests/app 拷进容器跑）拿不到 ini，
        # 这属于环境差异而不是行为回归，跳过而不是误报失败。
        pytest.skip(f"找不到 alembic.ini：{ini}")

    _reset("vnss.auth")
    app_logger("vnss.auth")  # 先按模块顶层的方式建好（handler + INFO）
    logging.config.fileConfig(str(ini), disable_existing_loggers=True)

    victim = logging.getLogger("vnss.auth")
    assert victim.disabled is True  # 复现：被 alembic 关掉了

    touched = configure_app_loggers()
    assert "vnss.auth" in touched
    assert victim.disabled is False
    assert victim.handlers
    assert victim.level == logging.INFO
    _reset("vnss.auth")
    _reset("vnss.audit")


def test_configure_app_loggers_covers_app_and_vnss():
    """启动时的统一接管：app.* / vnss.* 都要拿到 handler 且不再禁用。"""
    names = ["app.api.v1.demo", "vnss.audit"]
    for name in names:
        logger = _reset(name)
        logger.disabled = True
        logger.setLevel(logging.ERROR)

    touched = configure_app_loggers()
    assert "app.api.v1.demo" in touched
    assert "vnss.audit" in touched

    for name in names:
        logger = logging.getLogger(name)
        assert logger.disabled is False
        assert logger.handlers, name
        assert logger.level == logging.INFO

    for name in names:
        _reset(name)
