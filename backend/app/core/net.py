from fastapi import Request


def client_ip(request: Request) -> str:
    """Real client IP behind a reverse proxy (Railway, etc.), falling back to the socket peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def client_ip_identifier(request: Request) -> str:
    return client_ip(request)
