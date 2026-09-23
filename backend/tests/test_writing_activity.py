"""写作活动记录（连载页与写作统计的地基）：全正文写作也必须记上。

为什么专门测这个：`writing_activity` 是「写作统计」热力图与「连载 / 发布」页里
**今日净增、连续更新天数、更新日历**的唯一数据源。而记录路径 `sync_chapter_rows_from_vn`
原先用 `count_blocks_words(ch.blocks)` 算字数增量——那是**只数脚本块**的口径，
纯正文写作（`prose` 有内容、`blocks` 只有一个 label）算出来前后都是 0，
`record_activity` 见到 delta == 0 就直接 return：**一个字都不会被记下来**。

也就是说：给小说作者做的那个页面，在真实使用里会永远显示 0。这个文件把这条钉住。

另外钉住时区口径：后端按"作者当地日期"记账（前端传 UTC 偏移），
否则中国时区凌晨写的字会被记到前一天，页面显示"今日净增 0"。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import db_gate
import pytest

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()


def _prose_project(title: str, prose: str) -> dict:
    return {
        "title": title,
        "chapters": [
            {
                "id": "ch1",
                "title": "第一章",
                "prose": prose,
                # 纯正文写作的典型形状：只有一个起始 label，没有 narration/dialogue 块
                "blocks": [{"type": "label", "id": "start", "name": "start"}],
            }
        ],
    }


def _today_local(offset_minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).date().isoformat()


def test_prose_only_writing_is_recorded_in_activity():
    """纯正文写作：保存后 /stats 的 activity 必须出现今天的净增。"""

    async def _run():
        await db_gate.create_all()
        await db_gate.truncate_all()
        async with db_gate.make_client(APP) as client:
            owner = await db_gate.register_headers(client, "act_prose")
            created = await client.post(
                "/api/v1/projects",
                json={"title": "活动记录"},
                headers=owner,
            )
            pid = created.json()["id"]

            # 第一次保存：写入 40 个字的正文
            payload = _prose_project("活动记录", "雨停了，他站在月台上。" * 4)
            payload["id"] = pid
            saved = await client.put(
                f"/api/v1/projects/{pid}",
                json={"data": payload, "force": True},
                headers={**owner, "X-TZ-Offset": "480"},
            )
            assert saved.status_code == 200, saved.text

            stats = await client.get(f"/api/v1/projects/{pid}/stats", headers=owner)
            assert stats.status_code == 200, stats.text
            activity = stats.json()["activity"]
            assert activity, "纯正文写作没有产生任何活动记录（连载页会永远显示 0）"
            today = [d for d in activity if d["date"] == _today_local(480)]
            assert today, f"今天的记录不在 activity 里：{activity}"
            assert today[0]["net"] > 0, today

            # 章节字数口径也要对得上（正文优先）
            chapters = stats.json()["chapters"]
            assert chapters[0]["words"] > 0, chapters

    asyncio.run(_run())


def test_script_block_writing_still_recorded():
    """脚本块工程不能被这次修复弄坏（原来能记的现在还要能记）。"""

    async def _run():
        await db_gate.create_all()
        await db_gate.truncate_all()
        async with db_gate.make_client(APP) as client:
            owner = await db_gate.register_headers(client, "act_blocks")
            created = await client.post(
                "/api/v1/projects", json={"title": "块工程"}, headers=owner
            )
            pid = created.json()["id"]
            payload = {
                "id": pid,
                "title": "块工程",
                "chapters": [
                    {
                        "id": "ch1",
                        "title": "第一章",
                        "blocks": [
                            {"type": "label", "id": "start", "name": "start"},
                            {"type": "narration", "text": "雨停了，他站在月台上。"},
                            {"type": "dialogue", "characterId": "a", "text": "走吧。"},
                        ],
                    }
                ],
            }
            saved = await client.put(
                f"/api/v1/projects/{pid}",
                json={"data": payload, "force": True},
                headers={**owner, "X-TZ-Offset": "480"},
            )
            assert saved.status_code == 200, saved.text
            stats = await client.get(f"/api/v1/projects/{pid}/stats", headers=owner)
            activity = stats.json()["activity"]
            assert activity and sum(d["net"] for d in activity) > 0, activity

    asyncio.run(_run())


def test_activity_date_uses_author_timezone():
    """按作者当地日期记账：偏移 +480（东八区）时，日期必须等于当地日期。

    这条如果不成立，东八区用户在本地 00:00–08:00 写的字会落到前一天，
    连载页的「今日净增」在早上永远是 0。
    """
    from app.services.writing_stats import activity_date_key

    # 固定的 UTC 时刻：2026-03-10T20:30Z = 东八区 2026-03-11 04:30
    when = datetime(2026, 3, 10, 20, 30, tzinfo=timezone.utc)
    assert activity_date_key(when, tz_offset_minutes=480) == "2026-03-11"
    assert activity_date_key(when, tz_offset_minutes=0) == "2026-03-10"
    # 西五区：2026-03-10T02:00Z = 当地 2026-03-09 21:00
    early = datetime(2026, 3, 10, 2, 0, tzinfo=timezone.utc)
    assert activity_date_key(early, tz_offset_minutes=-300) == "2026-03-09"


def test_activity_date_key_is_safe_with_absurd_offsets():
    """偏移量只接受现实范围（-12h..+14h），越界**夹住**而不是忽略。

    夹住是有意的：忽略会静默退回 UTC（用户看到的仍是错的那一天），
    夹住则只是把离谱的请求头折到最接近的真实时区。
    """
    from app.services.writing_stats import activity_date_key

    when = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
    # 999999 → 夹到 +840（UTC+14）→ 当地 03-11 02:00
    assert activity_date_key(when, tz_offset_minutes=999999) == "2026-03-11"
    # -999999 → 夹到 -720（UTC-12）→ 当地 03-10 00:00
    assert activity_date_key(when, tz_offset_minutes=-999999) == "2026-03-10"
    # 边界值本身就是合法时区，不发生位移以外的变化
    assert activity_date_key(when, tz_offset_minutes=840) == "2026-03-11"
    assert activity_date_key(when, tz_offset_minutes=-720) == "2026-03-10"
    # 乱填成非数字：当 0（UTC），不抛异常
    assert activity_date_key(when, tz_offset_minutes="不是数字") == "2026-03-10"
