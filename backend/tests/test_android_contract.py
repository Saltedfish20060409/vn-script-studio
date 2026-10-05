"""Android 客户端 API 契约守卫（漂移检测）。

为什么需要：移动端的 DTO 是手写的（Kotlin 侧没有 OpenAPI 代码生成的构建依赖，
CI 里也不必装 openapi-generator）。手写 DTO 的风险是后端悄悄改了字段，
App 在用户手机上才炸。这里把「Android 依赖哪些接口、哪些字段」写成
`shared/test-fixtures/android_api_contract.json`，由两边各自校验：

- 本文件：用后端的 OpenAPI 校验——契约里的接口必须存在，契约里的字段必须还在 schema 里；
- Android `ApiContractTest`：校验 Retrofit 接口声明与契约一致（不多也不少）。

改后端接口导致这里红，说明 Android 端需要同步（或者契约需要有意识地更新）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.main import create_app

CONTRACT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "shared"
    / "test-fixtures"
    / "android_api_contract.json"
)

_PARAM_RE = re.compile(r"\{[^}]+\}")


def _norm(path: str) -> str:
    return _PARAM_RE.sub("{}", path)


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def openapi() -> dict:
    return create_app().openapi()


def _server_operations(openapi: dict) -> set[tuple[str, str]]:
    ops: set[tuple[str, str]] = set()
    for path, item in openapi["paths"].items():
        for method in item:
            if method in {"get", "post", "put", "patch", "delete"}:
                ops.add((method, _norm(path)))
    return ops


def test_contract_operations_exist(contract, openapi):
    server = _server_operations(openapi)
    wanted = [*contract["operations"], *contract["streams"]]
    missing = [
        f"{o['method'].upper()} {o['path']}"
        for o in wanted
        if (o["method"], _norm(o["path"])) not in server
    ]
    assert not missing, f"Android 依赖的接口在后端不存在了：{missing}"


def test_contract_schema_fields_exist(contract, openapi):
    schemas = openapi["components"]["schemas"]
    problems: list[str] = []
    for name, fields in contract["schemas"].items():
        schema = schemas.get(name)
        if schema is None:
            problems.append(f"schema {name} 不存在")
            continue
        props = set((schema.get("properties") or {}).keys())
        absent = [f for f in fields if f not in props]
        if absent:
            problems.append(f"{name} 缺少字段 {absent}")
    assert not problems, "Android 依赖的字段已从后端 schema 消失：\n" + "\n".join(problems)


def test_refresh_endpoint_accepts_optional_body(openapi):
    """原生客户端把 refresh token 放在请求体里；Web 端不带请求体——所以请求体必须是可选的。"""
    op = openapi["paths"]["/api/v1/auth/refresh"]["post"]
    body = op.get("requestBody")
    assert body is not None, "refresh 应声明（可选）请求体"
    assert not body.get("required", False), "refresh 请求体必须可选，否则 Web 端的无体请求会 422"
