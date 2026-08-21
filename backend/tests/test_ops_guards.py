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
