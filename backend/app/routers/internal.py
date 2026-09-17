"""Rotas entre servicos: o que outro processo interno pede a assistant-api.

Hoje ha uma so, e ela existe por uma razao fisica: a maquina do usuario so e
alcancavel pelo WebSocket da sessao, e esse socket mora aqui. Quando o grafo
roda no agent-orchestrator, a capacidade local escolhida pelo agente volta por
esta rota para seguir pelo socket.

Nada aqui usa JWT de usuario. A autenticacao e o segredo interno, e token nao
configurado fecha a rota (ver `core.internal_auth`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core.internal_auth import require_internal_token
from ..ports.tools import ToolError, ToolTimeout
from ..services.device_catalog_service import get_device_catalog

router = APIRouter(
    prefix="/internal",
    tags=["Internal"],
    include_in_schema=False,
    dependencies=[Depends(require_internal_token)],
)


class DeviceInvokeRequest(BaseModel):
    """Chamada de capacidade encaminhada por outro servico."""

    device_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    capability_id: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    repeatable: bool = True


@router.post("/devices/invoke")
async def invoke_device_capability(body: DeviceInvokeRequest) -> dict[str, Any]:
    """Executa uma capacidade na maquina de uma sessao conectada.

    So atende capacidade que aquela maquina publicou de fato: o servico chamador
    e confiavel, mas um manifesto velho do lado dele nao pode virar chamada a
    algo que a maquina ja nao declara.

    Falha volta como `ok: false` com `retryable`, e nao como erro HTTP: o
    chamador precisa distinguir "a maquina nao respondeu a tempo" de "a maquina
    recusou", e o status HTTP nao carrega essa diferenca.
    """
    from .websocket import remote_capabilities

    tool = get_device_catalog().find(body.tool_name, body.device_id)
    if tool is None:
        return {
            "ok": False,
            "retryable": False,
            "error": (
                f"{body.tool_name}: a maquina desta sessao nao esta conectada "
                "ou nao publicou esta capacidade"
            ),
        }

    try:
        output = await remote_capabilities.call(
            device_id=body.device_id,
            tool_name=body.tool_name,
            capability_id=body.capability_id,
            args=body.arguments,
            timeout=body.timeout_seconds,
            repeatable=body.repeatable,
        )
    except ToolTimeout as exc:
        return {"ok": False, "retryable": True, "error": str(exc)}
    except ToolError as exc:
        return {"ok": False, "retryable": False, "error": str(exc)}
    return {"ok": True, "output": output}
