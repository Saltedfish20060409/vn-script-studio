"""API tests: /projects/{id}/lore cards CRUD + lookup (Moegirl disabled → offline seeds)."""

from __future__ import annotations

import asyncio

import pytest

import db_gate

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()


def _run(coro):
    return asyncio.run(coro)


async def _create_project(client, headers) -> str:
    r = await client.post(
        "/api/v1/projects", json={"title": "Lore 项目", "from_demo": True}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_lore_cards_save_list_delete():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "lore_user")
            pid = await _create_project(client, headers)

            # empty initially
            r = await client.get(f"/api/v1/projects/{pid}/lore/cards", headers=headers)
            assert r.status_code == 200
            assert r.json()["cards"] == []

            # save a card
            r = await client.post(
                f"/api/v1/projects/{pid}/lore/cards",
                json={
                    "term": "傲娇",
                    "kind": "trope",
                    "definition_short": "口是心非，用冷淡掩饰在意。",
                    "do": ["表面冷淡", "事后补一句软话"],
                    "dont": ["直接告白"],
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text
            card = r.json()["card"]
            card_id = card["id"]
            assert card["term"] == "傲娇"
            assert card["kind"] == "trope"

            # list shows the card
            r = await client.get(f"/api/v1/projects/{pid}/lore/cards", headers=headers)
            cards = r.json()["cards"]
            assert len(cards) == 1
            assert cards[0]["id"] == card_id

            # save same term again → upsert (same card id, updated definition)
            r = await client.post(
                f"/api/v1/projects/{pid}/lore/cards",
                json={
                    "term": "傲娇",
                    "kind": "trope",
                    "definition_short": "更新后的定义。",
                },
                headers=headers,
            )
            assert r.status_code == 200
            updated = r.json()["card"]
            assert updated["id"] == card_id
            assert updated["definition_short"] == "更新后的定义。"

            r = await client.get(f"/api/v1/projects/{pid}/lore/cards", headers=headers)
            assert len(r.json()["cards"]) == 1

            # delete
            r = await client.delete(
                f"/api/v1/projects/{pid}/lore/cards/{card_id}", headers=headers
            )
            assert r.status_code == 200
            assert r.json()["ok"] is True

            r = await client.get(f"/api/v1/projects/{pid}/lore/cards", headers=headers)
            assert r.json()["cards"] == []

            # delete again → 404
            r = await client.delete(
                f"/api/v1/projects/{pid}/lore/cards/{card_id}", headers=headers
            )
            assert r.status_code == 404

    _run(_scenario())


def test_lore_cards_are_project_scoped():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "scope_user")
            pid1 = await _create_project(client, headers)
            pid2 = await _create_project(client, headers)

            await client.post(
                f"/api/v1/projects/{pid1}/lore/cards",
                json={"term": "三无", "definition_short": "情感外露极少。"},
                headers=headers,
            )

            r = await client.get(f"/api/v1/projects/{pid1}/lore/cards", headers=headers)
            assert len(r.json()["cards"]) == 1
            r = await client.get(f"/api/v1/projects/{pid2}/lore/cards", headers=headers)
            assert r.json()["cards"] == []

    _run(_scenario())


def test_lore_lookup_offline_seed_and_404():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "lookup_user")
            pid = await _create_project(client, headers)

            # Moegirl disabled in test settings → seed card, source=seed
            r = await client.post(
                f"/api/v1/projects/{pid}/lore/lookup",
                json={"term": "傲娇", "prefer_live": True},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["source"] == "seed"
            assert body["card"]["term"] == "傲娇"

            # unknown term, no seed → 404
            r = await client.post(
                f"/api/v1/projects/{pid}/lore/lookup",
                json={"term": "完全不存在的术语xyz"},
                headers=headers,
            )
            assert r.status_code == 404

            # empty term → 400
            r = await client.post(
                f"/api/v1/projects/{pid}/lore/lookup",
                json={"term": "   "},
                headers=headers,
            )
            assert r.status_code == 400

    _run(_scenario())


def test_lore_meta_reports_moegirl_disabled():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "meta_user")
            pid = await _create_project(client, headers)

            r = await client.get(f"/api/v1/projects/{pid}/lore/meta", headers=headers)
            assert r.status_code == 200
            assert r.json()["moegirlEnabled"] is False

    _run(_scenario())
