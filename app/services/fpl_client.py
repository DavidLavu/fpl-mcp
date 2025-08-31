from __future__ import annotations

from typing import Any, Final, Optional

import httpx
from cachetools import TTLCache
from fastapi import HTTPException

from app.util.settings import get_settings


BASE_URL: Final[str] = "https://fantasy.premierleague.com/api"

_CLIENT: Optional[httpx.AsyncClient] = None

# TTL cache for GET JSON responses
_CACHE: TTLCache[str, Any] = TTLCache(maxsize=512, ttl=get_settings().cache_ttl)


def get_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient, creating it lazily if needed."""
    global _CLIENT
    if _CLIENT is None or getattr(_CLIENT, "is_closed", False):
        _CLIENT = httpx.AsyncClient(timeout=15.0)
    return _CLIENT


async def aclose_client() -> None:
    """Close the shared AsyncClient if it exists and is open."""
    global _CLIENT
    if _CLIENT is not None and not getattr(_CLIENT, "is_closed", False):
        await _CLIENT.aclose()


async def _get(url: str) -> Any:
    """GET a JSON resource with caching and robust error handling.

    - Checks a TTLCache first; returns cached value when present.
    - On cache miss, fetches from upstream, raises for HTTP errors,
      stores JSON in the cache, and returns it.
    - On any httpx/network error, raises HTTP 502 with a safe message.
    """
    if url in _CACHE:
        return _CACHE[url]
    try:
        resp = await get_client().get(url)
        resp.raise_for_status()
        data = resp.json()
        _CACHE[url] = data
        return data
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 502
        if status == 404:
            raise HTTPException(status_code=404, detail="Resource not found") from exc
        raise HTTPException(status_code=502, detail="Upstream FPL API error") from exc
    except httpx.HTTPError as exc:  # timeouts, connection errors
        raise HTTPException(status_code=502, detail="Upstream FPL API error") from exc


async def bootstrap() -> dict:
    """Return the FPL bootstrap-static payload as a dict.

    Endpoint: https://fantasy.premierleague.com/api/bootstrap-static/
    """
    return await _get(f"{BASE_URL}/bootstrap-static/")


async def fixtures() -> list[dict]:
    """Return the list of fixtures.

    Endpoint: https://fantasy.premierleague.com/api/fixtures/
    """
    data = await _get(f"{BASE_URL}/fixtures/")
    # Upstream returns a list; ensure type for callers
    if not isinstance(data, list):
        raise HTTPException(status_code=502, detail="Unexpected FPL response format for fixtures")
    return data


async def fixtures_by_gw(gw: int) -> list[dict]:
    """Return fixtures filtered to a given gameweek (event).

    Filters items where `event == gw`.
    """
    all_fixtures = await fixtures()
    return [f for f in all_fixtures if f.get("event") == gw]


async def manager_picks(tid: int, gw: int) -> dict:
    """Return manager picks for a given team id (entry) and gameweek.

    Endpoint: https://fantasy.premierleague.com/api/entry/{tid}/event/{gw}/picks/
    """
    return await _get(f"{BASE_URL}/entry/{tid}/event/{gw}/picks/")
