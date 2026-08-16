"""Shared fixtures for API/DB integration tests.

DB tests are gated on ``db_gate.DB_AVAILABLE`` (see db_gate.py). When the test
PostgreSQL is reachable:
- a session-scoped autouse fixture runs ``Base.metadata.create_all`` once;
- a per-test autouse fixture truncates every table before each ``db``-marked test.

Core unit tests (no ``db`` marker) are completely unaffected: fixtures no-op.
"""

from __future__ import annotations

import asyncio

import pytest

import db_gate


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "db: integration test that requires the PostgreSQL test database"
    )


@pytest.fixture(scope="session", autouse=True)
def _create_test_schema():
    if not db_gate.DB_AVAILABLE:
        yield
        return
    asyncio.run(db_gate.create_all())
    yield


@pytest.fixture(autouse=True)
def _clean_db_before_test(request):
    # Only DB-marked modules pay for the truncate roundtrip.
    if not db_gate.DB_AVAILABLE or "db" not in request.keywords:
        yield
        return
    asyncio.run(db_gate.truncate_all())
    yield
