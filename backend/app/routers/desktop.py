import asyncio
import sys

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..core.security import get_current_user
from ..models.schemas import DesktopWindowContextResponse, DesktopWindowsResponse
from ..services import desktop_window_service
from ..services.desktop_window_service import WindowNotFoundError

router = APIRouter(prefix="/desktop", tags=["Desktop"], dependencies=[Depends(get_current_user)])


def _require_local_client(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127."):
        return
    raise HTTPException(
        status_code=403,
        detail="Desktop context is available only from the local machine.",
    )


@router.get("/windows", response_model=DesktopWindowsResponse)
async def list_desktop_windows(
    request: Request,
    limit: int = Query(default=120, ge=1, le=300),
):
    _require_local_client(request)
    windows = await asyncio.to_thread(desktop_window_service.list_windows, limit)
    return {
        "platform": sys.platform,
        "supported": desktop_window_service.is_supported_platform(),
        "active_window_id": next((item.id for item in windows if item.is_active), None),
        "windows": [item.to_dict() for item in windows],
    }


@router.get("/windows/{window_id}/context", response_model=DesktopWindowContextResponse)
async def get_desktop_window_context(
    window_id: str,
    request: Request,
    max_chars: int = Query(default=12000, ge=1000, le=30000),
):
    _require_local_client(request)
    try:
        return await asyncio.to_thread(
            desktop_window_service.extract_window_context,
            window_id,
            max_chars,
        )
    except WindowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
