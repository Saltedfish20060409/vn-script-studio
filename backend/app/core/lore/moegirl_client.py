"""MediaWiki client for 萌娘百科 (Moegirlpedia).

Uses official api.php. Respect rate limits; content is typically CC BY-NC-SA —
we store distilled craft cards + attribution, not wholesale page dumps for generation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

DEFAULT_API = "https://zh.moegirl.org.cn/api.php"
DEFAULT_UA = "VNScriptStudio/0.1 (self-use writing aid; +https://github.com/Saltedfish20060409/vn-script-studio)"


@dataclass
class MoegirlPage:
    title: str
    pageid: Optional[int]
    extract: str
    url: str
    missing: bool = False


def page_url(title: str) -> str:
    return f"https://zh.moegirl.org.cn/{quote(title.replace(' ', '_'), safe='()%')}"


async def search_titles(
    query: str,
    *,
    api_base: str = DEFAULT_API,
    user_agent: str = DEFAULT_UA,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    # 萌百禁用了 list=search（action-notallowed），但 opensearch 仍可用。
    # opensearch 返回 [query, [title1, title2, ...]]：精确词条常在前，模糊词条在后。
    params = {
        "action": "opensearch",
        "search": q,
        "limit": max(1, min(limit, 20)),
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": user_agent}) as client:
        res = await client.get(api_base, params=params)
        res.raise_for_status()
        data = res.json()
    titles = data[1] if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list) else []
    out = []
    for title in titles:
        title = (title or "").strip()
        if not title:
            continue
        out.append(
            {
                "title": title,
                "snippet": "",
                "pageid": None,
                "url": page_url(title),
            }
        )
    return out


async def fetch_extract(
    title: str,
    *,
    api_base: str = DEFAULT_API,
    user_agent: str = DEFAULT_UA,
    chars: int = 1200,
) -> MoegirlPage:
    title = (title or "").strip()
    if not title:
        return MoegirlPage(title="", pageid=None, extract="", url="", missing=True)
    params = {
        "action": "query",
        "prop": "extracts|info",
        "exintro": 1,
        "explaintext": 1,
        "exchars": max(200, min(chars, 2000)),
        "titles": title,
        "inprop": "url",
        "redirects": 1,
        "format": "json",
        "formatversion": 2,
    }
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": user_agent}) as client:
        res = await client.get(api_base, params=params)
        res.raise_for_status()
        data = res.json()
    pages = ((data.get("query") or {}).get("pages")) or []
    if not pages:
        return MoegirlPage(
            title=title, pageid=None, extract="", url=page_url(title), missing=True
        )
    p = pages[0]
    missing = bool(p.get("missing"))
    real_title = p.get("title") or title
    extract = (p.get("extract") or "").strip()
    url = p.get("fullurl") or page_url(real_title)
    return MoegirlPage(
        title=real_title,
        pageid=p.get("pageid"),
        extract=extract,
        url=url,
        missing=missing or not extract,
    )
