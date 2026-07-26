from fastapi import Request, Response
from fastapi_limiter.depends import RateLimiter

_ready = False


def mark_ready(ready: bool) -> None:
    global _ready
    _ready = ready


def rate_limit(times: int, seconds: int):
    """Per-IP rate limit dependency. No-ops if Redis/FastAPILimiter never initialized."""
    limiter = RateLimiter(times=times, seconds=seconds)

    async def dependency(request: Request, response: Response) -> None:
        if not _ready:
            return
        await limiter(request, response)

    return dependency
