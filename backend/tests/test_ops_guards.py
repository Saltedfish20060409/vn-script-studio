"""Unit tests: quota cap policy + in-process rate limit."""

import time

from app.core.rate_limit import check_rate
from app.core.usage import effective_daily_cap


class _S:
    llm_daily_token_cap = 0
    llm_shared_key_daily_cap = 200_000


def test_byok_unlimited_when_user_cap_zero():
    assert effective_daily_cap(_S(), {"source": "client"}) == 0
    assert effective_daily_cap(_S(), {"source": "user"}) == 0


def test_shared_server_key_uses_shared_cap():
    assert effective_daily_cap(_S(), {"source": "server"}) == 200_000


def test_user_cap_still_applies_to_byok_when_set():
    s = _S()
    s.llm_daily_token_cap = 50_000
    assert effective_daily_cap(s, {"source": "client"}) == 50_000
    assert effective_daily_cap(s, {"source": "server"}) == 50_000


def test_unknown_source_is_byok_unlimited():
    assert effective_daily_cap(_S(), {}) == 0
    assert effective_daily_cap(_S(), None) == 0


def test_check_rate_allows_under_limit():
    token = f"unit-rate-{time.time_ns()}"
    assert check_rate(token, "unit_test", 3, window=30)
    assert check_rate(token, "unit_test", 3, window=30)
    assert check_rate(token, "unit_test", 3, window=30)
    assert check_rate(token, "unit_test", 3, window=30) is False


def test_require_rate_raises_on_limit():
    from fastapi import HTTPException

    from app.core.rate_limit import require_rate

    token = f"unit-req-{time.time_ns()}"
    require_rate(token, "unit_req", 1, window=30)
    try:
        require_rate(token, "unit_req", 1, window=30)
    except HTTPException as exc:
        assert exc.status_code == 429
    else:
        raise AssertionError("expected 429")


def test_admin_username_set_parses():
    from app.config import Settings

    s = Settings.model_construct(
        secret_key="x" * 64,
        admin_usernames=" alice, bob , ",
    )
    assert s.admin_username_set == {"alice", "bob"}
    empty = Settings.model_construct(secret_key="x" * 64, admin_usernames="")
    assert empty.admin_username_set == set()


def test_ensure_admin_uses_db_flag_without_env():
    import asyncio

    from app.config import Settings
    from app.services.admin_access import ensure_admin_access

    user = type("U", (), {"username": "anyone", "is_admin": True})()
    settings = Settings.model_construct(secret_key="x" * 64, admin_usernames="")

    async def _run():
        return await ensure_admin_access(user, settings, db=None)  # type: ignore[arg-type]

    assert asyncio.run(_run()) is True


def test_ensure_admin_seed_when_no_db_admins(monkeypatch):
    import asyncio

    from app.config import Settings
    from app.services import admin_access

    class FakeUser:
        username = "seed"
        is_admin = False

    class FakeDb:
        async def commit(self):
            return None

        async def refresh(self, _u):
            return None

    async def fake_count(_db):
        return 0

    monkeypatch.setattr(admin_access, "count_db_admins", fake_count)
    user = FakeUser()
    settings = Settings.model_construct(
        secret_key="x" * 64, admin_usernames="seed"
    )

    async def _run():
        return await admin_access.ensure_admin_access(user, settings, FakeDb())

    assert asyncio.run(_run()) is True
    assert user.is_admin is True


def test_ensure_admin_empty_env_denies_without_explicit_bootstrap(monkeypatch):
    """SECURITY (H-1): empty ADMIN_USERNAMES must NOT auto-promote the first
    login unless admin_bootstrap_empty is explicitly enabled. Prevents a
    public instance being hijacked by whoever registers first."""
    import asyncio

    from app.config import Settings
    from app.services import admin_access

    class FakeUser:
        username = "localdev"
        is_admin = False

    class FakeDb:
        async def commit(self):
            return None

        async def refresh(self, _u):
            return None

    async def fake_count(_db):
        return 0

    monkeypatch.setattr(admin_access, "count_db_admins", fake_count)
    user = FakeUser()
    # Default: admin_bootstrap_empty=False → denied
    settings = Settings.model_construct(secret_key="x" * 64, admin_usernames="")

    async def _run():
        return await admin_access.ensure_admin_access(user, settings, FakeDb())

    assert asyncio.run(_run()) is False
    assert user.is_admin is False

    # Explicit opt-in: admin_bootstrap_empty=True → first login still bootstraps
    user2 = FakeUser()
    settings2 = Settings.model_construct(
        secret_key="x" * 64, admin_usernames="", admin_bootstrap_empty=True
    )

    async def _run2():
        return await admin_access.ensure_admin_access(user2, settings2, FakeDb())

    assert asyncio.run(_run2()) is True
    assert user2.is_admin is True


def test_ensure_admin_env_ignored_when_db_has_admins(monkeypatch):
    import asyncio

    from app.config import Settings
    from app.services import admin_access

    class FakeUser:
        username = "seed"
        is_admin = False

    async def fake_count(_db):
        return 2

    monkeypatch.setattr(admin_access, "count_db_admins", fake_count)
    user = FakeUser()
    settings = Settings.model_construct(
        secret_key="x" * 64, admin_usernames="seed"
    )

    async def _run():
        return await admin_access.ensure_admin_access(user, settings, object())  # type: ignore[arg-type]

    assert asyncio.run(_run()) is False
    assert user.is_admin is False


def test_flag_user_new_and_busy_is_danger():
    from datetime import datetime, timedelta, timezone

    from app.api.v1.admin import _flag_user

    created = datetime.now(timezone.utc) - timedelta(hours=6)
    flags, labels, severity = _flag_user(
        project_count=10,
        tokens_today=0,
        calls_today=0,
        created_at=created,
        disabled_at=None,
        max_projects=80,
    )
    assert "new_and_busy" in flags
    assert severity == "danger"
    assert labels


def test_flag_user_projects_warn():
    from app.api.v1.admin import _flag_user

    flags, _labels, severity = _flag_user(
        project_count=45,
        tokens_today=0,
        calls_today=0,
        created_at=None,
        disabled_at=None,
        max_projects=80,
    )
    assert "projects_warn" in flags
    assert severity == "warn"
