"""Formato de fio entre a assistant-api e o agent-orchestrator.

Os dois lados usam as mesmas funcoes, entao o que um serializa o outro sabe ler
- nao ha dois formatos divergindo devagar. O ponto delicado e a acao proposta a
interface: no processo ela e um modelo pydantic, e a rota da API depende do tipo
concreto para responder. Por isso a volta reconstroi o modelo pelo campo `type`,
em vez de entregar um dicionario que so funcionaria por coincidencia.
"""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError

from ...models.schemas import (
    CalendarCreateAction,
    CodingAction,
    ComputerAction,
    EducationOpenAction,
    LaunchAction,
    LLMResponse,
    Message,
    ProjectGroupImportAction,
    ResponseModeEnum,
    ShortcutRegistrationAction,
)
from ...ports.orchestration import ChatTurn
from ...services.client_capability_service import ClientCapability, ClientManifest

_ACTION_MODELS: dict[str, type[BaseModel]] = {
    "launch": LaunchAction,
    "open_project": LaunchAction,
    "register_shortcut": ShortcutRegistrationAction,
    "computer_action": ComputerAction,
    "coding_action": CodingAction,
    "calendar_create": CalendarCreateAction,
    "education_open": EducationOpenAction,
    "project_group_import": ProjectGroupImportAction,
}


# --- turno -------------------------------------------------------------------


def turn_to_payload(
    turn: ChatTurn,
    *,
    device: ClientManifest | None = None,
) -> dict[str, Any]:
    """Corpo de `POST /orchestrate/chat`."""
    return {
        "message": turn.message,
        "history": [item.model_dump(mode="json") for item in turn.history],
        "mode": turn.mode.value,
        "requested_llm": turn.requested_llm,
        "active_llms": list(turn.active_llms),
        "system_prompt": turn.system_prompt,
        "tutor_id": turn.tutor_id,
        "user_id": turn.user_id,
        "timezone": turn.timezone,
        "conversation_id": turn.conversation_id,
        "execution_id": turn.execution_id,
        "device_id": turn.device_id,
        "device": manifest_to_payload(device) if device is not None else None,
    }


def turn_from_payload(body: dict[str, Any]) -> ChatTurn:
    """Le o corpo recebido pelo orquestrador."""
    history: list[Message] = []
    for item in body.get("history") or []:
        try:
            history.append(Message.model_validate(item))
        except ValidationError:
            continue
    return ChatTurn(
        message=str(body.get("message") or ""),
        history=history,
        mode=ResponseModeEnum(body.get("mode") or "single"),
        requested_llm=body.get("requested_llm") or None,
        active_llms=tuple(str(item) for item in body.get("active_llms") or ()),
        system_prompt=str(body.get("system_prompt") or ""),
        tutor_id=str(body.get("tutor_id") or ""),
        user_id=str(body.get("user_id") or ""),
        timezone=str(body.get("timezone") or "America/Sao_Paulo"),
        conversation_id=str(body.get("conversation_id") or ""),
        execution_id=str(body.get("execution_id") or ""),
        device_id=str(body.get("device_id") or ""),
    )


# --- maquina do usuario ------------------------------------------------------


def manifest_to_payload(manifest: ClientManifest) -> dict[str, Any]:
    """O catalogo ja validado de uma maquina, para viajar junto com o turno."""
    return {
        "device_id": manifest.device_id,
        "platform": manifest.platform,
        "capabilities": [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "args_schema": item.args_schema,
                "risk_level": item.risk_level,
                "requires_confirmation": item.requires_confirmation,
                "read_only": item.read_only,
                "platforms": list(item.platforms),
            }
            for item in manifest.capabilities
        ],
    }


def manifest_from_payload(payload: Any) -> ClientManifest | None:
    """Reconstroi o manifesto sem revalidar.

    A validacao ja aconteceu na API, quando a interface publicou - e e la que
    mora a regra de exigir confirmacao. Aqui o manifesto vem de um servico
    autenticado, entao e lido como esta.
    """
    if not isinstance(payload, dict) or not payload.get("device_id"):
        return None
    capabilities = tuple(
        ClientCapability(
            id=str(item.get("id") or ""),
            name=str(item.get("name") or ""),
            description=str(item.get("description") or ""),
            args_schema=item.get("args_schema") or {},
            risk_level=str(item.get("risk_level") or "low"),
            requires_confirmation=bool(item.get("requires_confirmation", False)),
            read_only=bool(item.get("read_only", True)),
            platforms=tuple(item.get("platforms") or ()),
        )
        for item in payload.get("capabilities") or []
        if isinstance(item, dict) and item.get("id")
    )
    return ClientManifest(
        device_id=str(payload["device_id"]),
        platform=str(payload.get("platform") or ""),
        capabilities=capabilities,
    )


# --- resultado ---------------------------------------------------------------


def result_to_payload(state: dict[str, Any]) -> dict[str, Any]:
    """Estado final do grafo no formato de resposta do orquestrador."""
    action = state.get("action")
    if isinstance(action, BaseModel):
        action = action.model_dump(mode="json")
    return {
        "action_kind": state.get("action_kind"),
        "action": jsonable_encoder(action),
        "responses": [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item
            for item in state.get("responses") or []
        ],
        "agent_id": state.get("agent_id", ""),
        "tool_trace": jsonable_encoder(state.get("tool_trace") or []),
        "handoffs": jsonable_encoder(state.get("handoffs") or []),
        "errors": [str(item) for item in state.get("errors") or []],
        "execution_id": state.get("execution_id", ""),
    }


def result_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Resposta do orquestrador de volta ao formato que as rotas consomem."""
    return {
        "action_kind": payload.get("action_kind") or "chat",
        "action": action_from_payload(payload.get("action")),
        "responses": [
            LLMResponse.model_validate(item)
            for item in payload.get("responses") or []
        ],
        "agent_id": payload.get("agent_id") or "",
        "tool_trace": payload.get("tool_trace") or [],
        "handoffs": payload.get("handoffs") or [],
        "errors": payload.get("errors") or [],
        "execution_id": payload.get("execution_id") or "",
    }


def action_from_payload(payload: Any) -> Any:
    """Devolve a acao ao seu modelo concreto, pelo campo `type`.

    Tipo desconhecido - orquestrador mais novo que a API durante um deploy -
    segue como dicionario: a interface ainda recebe o JSON, e a rota nao cai.
    """
    if not isinstance(payload, dict):
        return payload
    model = _ACTION_MODELS.get(str(payload.get("type") or ""))
    if model is None:
        return payload
    try:
        return model.model_validate(payload)
    except ValidationError:
        return payload
