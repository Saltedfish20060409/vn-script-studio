"""库里拒绝写入时，用户该看到一句人话，而不是 `Internal Server Error`。

实盘（2026-09-26）：`value too long for type character varying(128)` 变成 500，
界面只说"保存失败"，用户既不知道哪一项、也永远修不好（15 次连续失败、改动一直没落盘）。
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

# app.config 会硬拒默认 SECRET_KEY（可猜的签名密钥 = 账号接管漏洞），
# 所以要在导入 app.main 之前先给一个测试用的（与 db_gate 同一把）。
os.environ.setdefault(
    "SECRET_KEY", "unit-test-secret-key-0123456789abcdef0123456789abcdef"
)

from sqlalchemy.exc import DataError  # noqa: E402

from app.core.db_errors import data_error_handler, describe_data_error  # noqa: E402


def _data_error(orig: str) -> DataError:
    """构造一个带真实 orig 文案的 DataError（SQLAlchemy 的 str() 只给类型名）。"""
    err = DataError("UPDATE projects SET genre=$1", {}, Exception(orig))
    return err


def test_varchar_overflow_names_the_limit_and_is_actionable():
    msg = describe_data_error(
        _data_error("value too long for type character varying(128)")
    )
    assert "128" in msg
    assert "长度" in msg
    # 必须给出下一步动作，否则等于换了一句废话
    assert "精简" in msg
    # 不能把英文原文直接甩给用户
    assert "character varying" not in msg


def test_other_kinds_of_rejection_also_get_chinese():
    assert "数值" in describe_data_error(
        _data_error('numeric field overflow: "A field with precision 5"')
    )
    assert "格式" in describe_data_error(
        _data_error('invalid input syntax for type integer: "abc"')
    )
    assert "必填" in describe_data_error(
        _data_error('null value in column "title" violates not-null constraint')
    )


def test_unknown_data_error_still_says_something_useful():
    """没见过的 DataError 不能退化成 500 那句话：仍然是"这次保存被拒绝 + 怎么办"。"""
    msg = describe_data_error(_data_error("some new driver complaint"))
    assert "保存被" in msg
    assert "Internal Server Error" not in msg


def test_handler_returns_400_with_readable_detail():
    """兜底 handler 本身：状态码必须是 400，body 里是能读懂的话。

    直接调处理器（不经过整站）：这个兜底不该只有出事那天才第一次被执行到。
    """
    request = SimpleNamespace(
        method="PUT",
        url=SimpleNamespace(path="/api/v1/projects/proj-x"),
    )
    response = data_error_handler(
        request, _data_error("value too long for type character varying(128)")
    )
    assert response.status_code == 400
    detail = json.loads(bytes(response.body).decode("utf-8"))["detail"]
    assert "128" in detail
    assert "Internal Server Error" not in detail


def test_handler_is_registered_on_the_app():
    """注册这件事也要钉住：处理器写好了但没挂上去，等于没有。

    只 import 模块级的 app（不启动服务、不跑 lifespan），所以不碰数据库。
    """
    from app.main import app

    assert DataError in app.exception_handlers
    assert app.exception_handlers[DataError] is data_error_handler
