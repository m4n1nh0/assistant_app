from fastapi import APIRouter, Depends, HTTPException, Query, Request
from ipaddress import ip_address, ip_network
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import ScriptSnippetModel, get_db
from ..core.security import get_current_user

from ..models.schemas import (
    ComputerActionInfo,
    ComputerActionRunRequest,
    ComputerActionRunResponse,
    ScriptSnippetCreate,
    ScriptSnippetResponse,
    ScriptSnippetUpdate,
    ScriptShellsResponse,
)
from ..services import computer_action_service
router = APIRouter(prefix="/computer", tags=["Computer"], dependencies=[Depends(get_current_user)])


def _script_response(item: ScriptSnippetModel) -> ScriptSnippetResponse:
    return ScriptSnippetResponse(
        id=item.id,
        tutor_id=item.tutor_id,
        name=item.name,
        shell=item.shell,
        script=item.script,
        working_directory=item.working_directory,
        timeout_seconds=item.timeout_seconds or 30,
        allow_high_risk=item.allow_high_risk is True,
        description=item.description,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _clean_script_fields(
    *,
    name: str | None,
    script: str | None,
    working_directory: str | None,
    description: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    clean_name = name.strip() if name is not None else None
    clean_script = script.strip() if script is not None else None
    clean_cwd = working_directory.strip() if working_directory else None
    clean_description = description.strip() if description else None
    return clean_name, clean_script, clean_cwd, clean_description


def _require_local_client(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host in {"127.0.0.1", "::1", "localhost"} or host.startswith("127."):
        return
    try:
        client_ip = ip_address(host)
        docker_bridge_networks = (
            ip_network("172.16.0.0/12"),
            ip_network("fc00::/7"),
        )
        if any(client_ip in network for network in docker_bridge_networks):
            return
    except ValueError:
        pass
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded_for in {"127.0.0.1", "::1", "localhost"} or forwarded_for.startswith("127."):
        return
    raise HTTPException(
        status_code=403,
        detail="Computer actions are available only from the local machine.",
    )


@router.get("/actions", response_model=list[ComputerActionInfo])
async def list_computer_actions(request: Request):
    _require_local_client(request)
    return [action.to_dict() for action in computer_action_service.list_actions()]


@router.post(
    "/actions/{action_id}/run",
    response_model=ComputerActionRunResponse,
)
async def run_computer_action(
    action_id: str,
    body: ComputerActionRunRequest,
    request: Request,
):
    _require_local_client(request)
    computer_action_service.get_action(action_id)
    raise HTTPException(
        status_code=501,
        detail="Execucao local desativada no backend. A interface desktop deve executar esta acao.",
    )


@router.get("/scripts/shells", response_model=ScriptShellsResponse)
async def list_script_shells(request: Request):
    _require_local_client(request)
    return {
        "default_shell": "powershell",
        "available_shells": ["powershell", "pwsh", "cmd", "bash", "sh", "zsh"],
    }


@router.get("/scripts", response_model=list[ScriptSnippetResponse])
async def list_saved_scripts(
    request: Request,
    tutor_id: str = Query(default="default"),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_local_client(request)
    tutor_id = user["tutor_id"]
    result = await db.execute(
        select(ScriptSnippetModel)
        .where(ScriptSnippetModel.tutor_id == tutor_id)
        .order_by(ScriptSnippetModel.name)
    )
    return [_script_response(item) for item in result.scalars().all()]


@router.post("/scripts", response_model=ScriptSnippetResponse, status_code=201)
async def create_saved_script(
    body: ScriptSnippetCreate,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_local_client(request)
    name, script, cwd, description = _clean_script_fields(
        name=body.name,
        script=body.script,
        working_directory=body.working_directory,
        description=body.description,
    )
    if not name:
        raise HTTPException(400, "Nome do script nao pode ficar vazio")
    if not script:
        raise HTTPException(400, "Script nao pode ficar vazio")
    item = ScriptSnippetModel(
        tutor_id=user["tutor_id"],
        name=name,
        shell=body.shell.value,
        script=script,
        working_directory=cwd,
        timeout_seconds=body.timeout_seconds,
        allow_high_risk=body.allow_high_risk,
        description=description,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _script_response(item)


@router.post("/scripts/run")
async def run_script(request: Request):
    _require_local_client(request)
    raise HTTPException(
        status_code=501,
        detail="Execucao de scripts desativada no backend. A interface desktop deve executar scripts localmente.",
    )


@router.patch("/scripts/{script_id}", response_model=ScriptSnippetResponse)
async def update_saved_script(
    script_id: str,
    body: ScriptSnippetUpdate,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_local_client(request)
    item = await db.get(ScriptSnippetModel, script_id)
    if item is None or item.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Script nao encontrado")
    name, script, cwd, description = _clean_script_fields(
        name=body.name,
        script=body.script,
        working_directory=body.working_directory,
        description=body.description,
    )
    if body.name is not None:
        if not name:
            raise HTTPException(400, "Nome do script nao pode ficar vazio")
        item.name = name
    if body.shell is not None:
        item.shell = body.shell.value
    if body.script is not None:
        if not script:
            raise HTTPException(400, "Script nao pode ficar vazio")
        item.script = script
    if body.working_directory is not None:
        item.working_directory = cwd
    if body.timeout_seconds is not None:
        item.timeout_seconds = body.timeout_seconds
    if body.allow_high_risk is not None:
        item.allow_high_risk = body.allow_high_risk
    if body.description is not None:
        item.description = description
    await db.commit()
    await db.refresh(item)
    return _script_response(item)


@router.delete("/scripts/{script_id}", status_code=204)
async def delete_saved_script(
    script_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_local_client(request)
    item = await db.get(ScriptSnippetModel, script_id)
    if item is None or item.tutor_id != user["tutor_id"]:
        raise HTTPException(404, "Script nao encontrado")
    await db.delete(item)
    await db.commit()
