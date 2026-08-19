"""Unit tests for email auth helpers (no Resend network)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from app.models.tables import AuthEmailToken, User
from app.services.auth_email import (
    consume_email_token,
    is_email_verified,
    normalize_email,
)


def test_normalize_email():
    assert normalize_email("  Foo@Bar.COM ") == "foo@bar.com"


def test_legacy_user_without_email_is_verified():
    u = User(username="a", password_hash="x", email=None, email_verified_at=None)
    assert is_email_verified(u) is True


def test_user_with_unverified_email():
    u = User(username="a", password_hash="x", email="a@b.com", email_verified_at=None)
    assert is_email_verified(u) is False


def test_consume_rejects_expired_token():
    row = AuthEmailToken(
        id="t1",
        user_id="u1",
        token="abc",
        purpose="verify",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        used_at=None,
    )
    user = User(id="u1", username="a", password_hash="x", email="a@b.com")
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    db.execute = AsyncMock(return_value=result)
    db.get = AsyncMock(return_value=user)

    got = asyncio.run(consume_email_token(db, "abc", "verify"))
    assert got is None
