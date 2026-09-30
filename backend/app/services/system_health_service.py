"""Bounded, cached infrastructure checks; no user credentials or actions."""

import asyncio
import time

from sqlalchemy import text

from ..adapters.container import (
    get_mcp_gateway, get_orchestration_gateway, get_tool_gateway,
)
from ..core.config import get_settings
from ..core.database import engine

_cache = None
_lock = asyncio.Lock()


async def _database():
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    return True


async def _redis():
    from redis.asyncio import Redis

    client = Redis.from_url(get_settings().redis_url, socket_timeout=3)
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()


async def _qdrant():
    from qdrant_client import AsyncQdrantClient

    settings = get_settings()
    client = AsyncQdrantClient(
        url=settings.qdrant_url, api_key=settings.qdrant_api_key or None,
        timeout=3, check_compatibility=False,
    )
    try:
        await client.get_collections()
        return True
    finally:
        await client.close()


async def _orchestration():
    return (await get_orchestration_gateway().health()).get("ok") is True


async def _tools():
    return (await get_tool_gateway().health()).get("ok") is True


async def _mcp():
    return all(item.reachable for item in await get_mcp_gateway().health())


async def _email():
    from .registration_invite_service import brevo_api_diagnostic

    if not get_settings().brevo_api_key.strip():
        return False
    return (await brevo_api_diagnostic()).get("success") is True


async def _check(probe, *, configured=True, transport=None):
    result = {"configured": configured, "ok": None, "status": "disabled"}
    if transport:
        result["transport"] = transport
    if not configured:
        return result
    try:
        result["ok"] = await asyncio.wait_for(probe(), timeout=5) is True
        result["status"] = "ok" if result["ok"] else "unavailable"
    except asyncio.TimeoutError:
        result.update(ok=False, status="timeout")
    except Exception:
        result.update(ok=False, status="unavailable")
    return result


async def collect_health():
    """Coalesce concurrent callers; cache snapshots for 30 seconds."""
    global _cache
    async with _lock:
        if _cache is not None and time.monotonic() - _cache[0] < 30:
            return _cache[1]
        settings = get_settings()
        from .registration_invite_service import registration_delivery_configured

        checks = {
            "database": (_database, {"configured": bool(settings.database_url)}),
            "redis": (_redis, {"configured": bool(settings.redis_url)}),
            "qdrant": (_qdrant, {"configured": bool(settings.qdrant_url)}),
            "orchestration": (_orchestration, {
                "transport": "remote" if settings.uses_remote_orchestrator else "local",
            }),
            "tools": (_tools, {
                "transport": "remote" if settings.uses_remote_tools else "local",
            }),
            "mcp": (_mcp, {
                "configured": settings.uses_remote_mcp or bool(settings.mcp_servers.strip()),
                "transport": "remote" if settings.uses_remote_mcp else "local",
            }),
            "email": (_email, {
                "configured": bool(settings.brevo_api_key.strip()) or settings.health_alerts_enabled,
            }),
        }
        results = await asyncio.gather(*(
            _check(probe, **options) for probe, options in checks.values()
        ))
        services = dict(zip(checks, results))
        # Email API readiness does not prove message delivery or sender validity.
        services["email"]["delivery_configured"] = registration_delivery_configured()
        if settings.health_alerts_enabled and not services["email"]["delivery_configured"]:
            services["email"].update(ok=False, status="misconfigured")
        _cache = (time.monotonic(), services)
        return services
