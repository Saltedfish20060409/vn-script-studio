"""P2: Moegirl lookup in-process TTL cache."""
from __future__ import annotations

import time

from app.services import lore as lore_svc


def test_cache_roundtrip():
    lore_svc._lookup_cache.clear()
    payload = {"card": {"term": "傲娇"}, "source": "moegirl", "hits": []}
    lore_svc._cache_put("傲娇", payload)
    got = lore_svc._cache_get("傲娇")
    assert got is not None
    assert got["card"]["term"] == "傲娇"
    # Cache returns a copy — mutating it must not corrupt the store
    got["card"]["term"] = "mutated"
    assert lore_svc._cache_get("傲娇")["card"]["term"] == "傲娇"


def test_cache_miss_and_expiry():
    lore_svc._lookup_cache.clear()
    assert lore_svc._cache_get("不存在词") is None

    lore_svc._lookup_cache["过期词"] = (time.time() - 25 * 3600, {"card": {}})
    assert lore_svc._cache_get("过期词") is None
    assert "过期词" not in lore_svc._lookup_cache


def test_cache_cap_clears():
    lore_svc._lookup_cache.clear()
    for i in range(600):
        lore_svc._cache_put(f"term-{i}", {"card": {"term": f"t{i}"}})
    assert len(lore_svc._lookup_cache) <= 512
    lore_svc._lookup_cache.clear()
