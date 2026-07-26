from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import (
    AssistantProfileModel,
    TutorModel,
    TutorSettingModel,
    get_db,
)
from ..core.security import get_current_user
from ..models.schemas import (
    TutorProfileRequest,
    TutorProfileResponse,
    TutorSettingRequest,
    TutorSettingResponse,
)

router = APIRouter(prefix="/tutor", tags=["Tutor"], dependencies=[Depends(get_current_user)])


def _profile_response(tutor: TutorModel, profile: AssistantProfileModel) -> TutorProfileResponse:
    return TutorProfileResponse(
        tutor_id=tutor.id,
        display_name=tutor.display_name,
        email=tutor.email,
        timezone=tutor.timezone,
        locale=tutor.locale,
        notes=tutor.notes or "",
        assistant_name=profile.assistant_name,
        personality=profile.personality or "",
        response_mode=profile.response_mode,
        tts_enabled=bool(profile.tts_enabled),
        config=profile.config or {},
    )


@router.put("/", response_model=TutorProfileResponse)
async def upsert_tutor(
    body: TutorProfileRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tutor = await db.get(TutorModel, user["tutor_id"])

    if tutor is None:
        tutor = TutorModel(
            id=user["tutor_id"],
            display_name=body.display_name,
            email=body.email,
            timezone=body.timezone,
            locale=body.locale,
            notes=body.notes,
        )
        db.add(tutor)
        await db.flush()
    else:
        tutor.display_name = body.display_name
        tutor.email = body.email
        tutor.timezone = body.timezone
        tutor.locale = body.locale
        tutor.notes = body.notes

    result = await db.execute(
        select(AssistantProfileModel).where(AssistantProfileModel.tutor_id == tutor.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = AssistantProfileModel(tutor_id=tutor.id)
        db.add(profile)

    profile.assistant_name = body.assistant_name
    profile.personality = body.personality
    profile.language = body.locale
    profile.response_mode = body.response_mode.value
    profile.tts_enabled = body.tts_enabled
    profile.config = body.config

    await db.commit()
    await db.refresh(tutor)
    await db.refresh(profile)
    return _profile_response(tutor, profile)


@router.get("/{tutor_id}", response_model=TutorProfileResponse)
async def get_tutor(
    tutor_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Tutor nao encontrado")
    tutor = await db.get(TutorModel, user["tutor_id"])
    if tutor is None:
        raise HTTPException(404, "Tutor não encontrado")

    result = await db.execute(
        select(AssistantProfileModel).where(AssistantProfileModel.tutor_id == tutor.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = AssistantProfileModel(tutor_id=tutor.id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)

    return _profile_response(tutor, profile)


@router.put("/{tutor_id}/settings/{key}", response_model=TutorSettingResponse)
async def upsert_setting(
    tutor_id: str,
    key: str,
    body: TutorSettingRequest,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Tutor nao encontrado")
    tutor_id = user["tutor_id"]
    result = await db.execute(
        select(TutorSettingModel).where(
            TutorSettingModel.tutor_id == tutor_id,
            TutorSettingModel.key == key,
        )
    )
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = TutorSettingModel(tutor_id=tutor_id, key=key)
        db.add(setting)

    setting.value = body.value
    setting.scope = body.scope
    await db.commit()
    await db.refresh(setting)
    return TutorSettingResponse(
        id=setting.id,
        tutor_id=setting.tutor_id,
        key=setting.key,
        value=setting.value or {},
        scope=setting.scope,
    )


@router.get("/{tutor_id}/settings", response_model=list[TutorSettingResponse])
async def list_settings(
    tutor_id: str,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Tutor nao encontrado")
    tutor_id = user["tutor_id"]
    result = await db.execute(
        select(TutorSettingModel).where(TutorSettingModel.tutor_id == tutor_id)
    )
    return [
        TutorSettingResponse(
            id=item.id,
            tutor_id=item.tutor_id,
            key=item.key,
            value=item.value or {},
            scope=item.scope,
        )
        for item in result.scalars().all()
    ]
