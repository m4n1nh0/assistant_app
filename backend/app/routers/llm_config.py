from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_db
from ..core.security import get_current_user
from ..models.schemas import UserLLMConfigUpdate
from ..services.llm_status_service import get_available_llms, get_llm_statuses
from ..services.user_llm_config_service import (
    activate_user_llms,
    list_provider_config,
    load_user_llm_runtime,
    migrate_legacy_environment_for_user,
    reset_user_llms,
    runtime_settings,
    save_provider_config,
)

router = APIRouter(prefix="/llm", tags=["LLM"], dependencies=[Depends(get_current_user)])


async def _response(user: dict, *, force: bool = False) -> dict:
    await migrate_legacy_environment_for_user(user)
    runtime = await load_user_llm_runtime(user["tutor_id"])
    token = activate_user_llms(runtime)
    try:
        statuses = await get_llm_statuses(force=force)
        available = await get_available_llms()
        return {
            "providers": await list_provider_config(user["tutor_id"]),
            "active_llms": runtime_settings.active_llms,
            "available_llms": available,
            "llm_labels": runtime_settings.llm_labels,
            "llm_status": {
                provider: status.model_dump(mode="json")
                for provider, status in statuses.items()
            },
        }
    finally:
        reset_user_llms(token)


@router.get("/config")
async def get_llm_config(user: dict = Depends(get_current_user)):
    return await _response(user)


@router.put("/config")
async def update_llm_config(
    body: UserLLMConfigUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await migrate_legacy_environment_for_user(user)
    try:
        await save_provider_config(
            user["tutor_id"],
            [item.model_dump() for item in body.providers],
            db,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await _response(user, force=True)


@router.post("/status/refresh")
async def refresh_llm_status(user: dict = Depends(get_current_user)):
    return await _response(user, force=True)
