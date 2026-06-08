import hashlib

import redis.asyncio as redis

CACHE_TTL = 3600


def _make_cache_key(query: str, region: str, limit: int) -> str:
    raw = f"{query.strip().lower()}|{region.strip().lower()}|{limit}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"cache:{digest}"


async def get_cached_search_id(
    r: redis.Redis, query: str, region: str, limit: int
) -> str | None:
    key = _make_cache_key(query, region, limit)
    value = await r.get(key)
    return value


async def cache_search_id(
    r: redis.Redis, query: str, region: str, limit: int, search_id: str
):
    key = _make_cache_key(query, region, limit)
    await r.setex(key, CACHE_TTL, search_id)


async def invalidate_cache(r: redis.Redis, query: str, region: str, limit: int):
    key = _make_cache_key(query, region, limit)
    await r.delete(key)
