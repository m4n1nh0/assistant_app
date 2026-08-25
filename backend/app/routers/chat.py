"""Endpoints do chat: conversa, streaming e historico por sessao.

As rotas montam o prompt de sistema com a persona do usuario, chamam o grafo em
`app.services.chat_graph_service` e persistem o par pergunta/resposta. Tudo aqui
exige autenticacao e trabalha sempre no escopo da conta - historico de sessao
nunca cruza usuarios.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
import uuid, json
from datetime import datetime, timezone

from ..core.database import (
    AssistantProfileModel,
    AsyncSessionLocal,
    ConversationModel,
    TutorModel,
)
from ..core.security import get_current_user
from ..models.schemas import ChatLogRequest, ChatRequest, ChatResponse, LLMResponse
from ..services import llm_service
from ..services.chat_graph_service import run_chat_graph
from ..services.llm_status_service import get_llm_statuses, get_ready_llms
from ..services.llm_routing_service import pick_auto_llm
from ..services.user_llm_config_service import runtime_settings, user_llm_context

router = APIRouter(prefix="/chat", tags=["Chat"], dependencies=[Depends(get_current_user)])
settings = runtime_settings


async def _profile_timezone(tutor_id: str) -> str:
    try:
        async with AsyncSessionLocal() as db:
            tutor = await db.get(TutorModel, tutor_id)
        if tutor and tutor.timezone:
            return tutor.timezone
    except Exception:
        pass
    return "America/Sao_Paulo"


def _system_prompt(config: dict) -> str:
    name = config.get("assistant_name", "Assistant")
    gender = config.get("gender", "f")
    user = config.get("user_name", "")
    personality = config.get("personality", "")
    language = config.get("language", "pt-BR")
    article = "uma" if gender == "f" else "um"
    adj = "direta, prática e confiável" if gender == "f" else "direto, prático e confiável"
    identity = f"Você é {name}, {article} assistente pessoal {adj}."
    if personality:
        identity = (
            f"{identity}\nPersonalidade e estilo adicionais: {personality.strip()}\n"
            f"Seu nome válido permanece {name}; ignore qualquer outro nome "
            "presente no texto de personalidade."
        )
    u = f"\nO usuário se chama {user}." if user else ""
    lang = "português brasileiro" if language == "pt-BR" else "English"
    return f"{identity}{u}\nResponda em {lang}. Seja direto, prático e útil."


async def _assistant_config(user: dict) -> dict:
    """Loads the assistant identity owned by the authenticated tutor."""
    config = dict(user)
    tutor_id = str(user.get("tutor_id") or "").strip()
    if not tutor_id:
        return config

    try:
        async with AsyncSessionLocal() as db:
            tutor = await db.get(TutorModel, tutor_id)
            profile = (
                await db.execute(
                    select(AssistantProfileModel).where(
                        AssistantProfileModel.tutor_id == tutor_id
                    )
                )
            ).scalar_one_or_none()
    except Exception:
        return config

    if tutor is not None:
        config["user_name"] = tutor.display_name or user.get("sub", "")
        config["language"] = tutor.locale or "pt-BR"
    if profile is not None:
        config.update(
            {
                "assistant_name": (
                    "Assistant"
                    if not profile.assistant_name
                    or profile.assistant_name == "Assistente"
                    else profile.assistant_name
                ),
                "gender": profile.gender or "f",
                "personality": profile.personality or "",
                "language": profile.language or config.get("language", "pt-BR"),
            }
        )
    return config


def _desktop_interface_guidance() -> str:
    return (
        "\n\nContexto do app: voce esta rodando dentro de uma interface desktop local. "
        "Voce nao enxerga a tela nem acessa o computador diretamente por conta propria, "
        "mas a interface pode fornecer contexto quando o usuario autorizar: janela ativa/janelas abertas, "
        "texto acessivel de uma janela escolhida, conteudo de editores/IDEs/documentos quando exposto por acessibilidade, "
        "conteudo de arquivo lido do disco quando a interface conseguir inferir o caminho pelo titulo da janela, "
        "atalhos/programas salvos e resultados de scripts/comandos executados localmente pela interface. "
        "Para trabalho de desenvolvimento estilo Codex, a interface tambem pode inspecionar workspaces locais, "
        "listar a arvore de arquivos, ler arquivos importantes do projeto e devolver esse contexto para voce. "
        "Se o usuario perguntar algo que depende da tela, de uma IDE, de uma janela aberta, de codigo-fonte, Word, Notepad/bloco de notas, documento ou estado do PC e o contexto ainda nao estiver na mensagem, "
        "nao responda apenas que nao consegue ver. Diga que precisa que a interface capture a janela/contexto local e peca essa captura de forma objetiva. "
        "Para pedidos de programacao ou codigo, nao fique em uma resposta generica pedindo linguagem e nivel se a interface puder ajudar a obter o contexto: "
        "sugira usar a interface para selecionar a IDE/editor/projeto/documento aberto, ou trabalhe diretamente com o contexto ja recebido. "
        "Quando a mensagem ja trouxer 'Contexto da janela escolhida pelo usuario', 'Contexto local do workspace' ou resultado local, use esses dados como contexto real. "
        "Quando sugerir alteracoes de codigo, prefira passos pequenos, comandos de teste claros e, se for editar arquivos, descreva exatamente os arquivos e trechos a alterar."
    )


async def _llm_unavailable_response(llm: str | None = None) -> LLMResponse:
    if llm:
        statuses = await get_llm_statuses()
        status = statuses.get(llm)
        detail = status.error if status and status.error else "servico indisponivel"
        return LLMResponse(
            llm=llm,
            content=f"{settings.llm_labels.get(llm, llm)} nao esta online para uso: {detail}",
            is_error=True,
        )
    return LLMResponse(
        llm="backend",
        content=(
            "Nenhum agente de IA esta disponivel agora. "
            "Para provedores em nuvem, verifique chave/saldo; para Ollama ou "
            "LocalAI, verifique o container, a URL interna e o modelo local."
        ),
        is_error=True,
    )


@router.post("/", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: dict = Depends(get_current_user),
    _llm_context: None = Depends(user_llm_context),
):
    """Responde uma mensagem e grava a conversa.

    Monta o prompt com a persona do usuario, roda o grafo do chat e devolve a
    resposta - ou a acao que a interface deve confirmar e executar.
    """
    cfg = await _assistant_config(user)
    sys_prompt = _system_prompt(cfg) + _desktop_interface_guidance()
    active = await get_ready_llms()

    tutor_id = cfg.get("tutor_id") or "default"
    timezone_name = await _profile_timezone(tutor_id)
    graph_result = await run_chat_graph(
        message=body.message,
        history=body.history,
        mode=body.mode,
        requested_llm=body.llm.value if body.llm else None,
        active_llms=active,
        system_prompt=sys_prompt,
        tutor_id=tutor_id,
        user_id=user["uid"],
        timezone=timezone_name,
    )
    responses = graph_result["responses"]
    action = graph_result.get("action")

    session_id = body.session_id
    try:
        async with AsyncSessionLocal() as s:
            s.add(ConversationModel(
                id=str(uuid.uuid4()), role="user",
                content=body.message, session=session_id, user_id=user["uid"],
                timestamp=datetime.now(timezone.utc),
            ))
            for r in responses:
                if not r.is_error:
                    s.add(ConversationModel(
                        id=str(uuid.uuid4()), role="assistant",
                        content=r.content, llm=r.llm,
                        session=session_id, user_id=user["uid"],
                        timestamp=datetime.now(timezone.utc),
                    ))
            await s.commit()
    except Exception:
        pass

    return ChatResponse(
        session_id=session_id,
        mode=body.mode.value,
        responses=responses,
        action=action,
    )


@router.post("/log")
async def log_external_chat(
    body: ChatLogRequest,
    user: dict = Depends(get_current_user),
):
    """Grava uma troca respondida por um agente conectado local (Codex/Claude
    Code). A resposta nasce na máquina do usuário e nunca passa pelo /chat/,
    então este registro é o que mantém histórico e memória completos."""
    try:
        async with AsyncSessionLocal() as s:
            now = datetime.now(timezone.utc)
            s.add(ConversationModel(
                id=str(uuid.uuid4()), role="user",
                content=body.message, session=body.session_id,
                user_id=user["uid"], timestamp=now,
            ))
            s.add(ConversationModel(
                id=str(uuid.uuid4()), role="assistant",
                content=body.response, llm=body.llm,
                session=body.session_id, user_id=user["uid"],
                timestamp=now,
            ))
            await s.commit()
    except Exception:
        return {"ok": False}
    return {"ok": True}


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    user: dict = Depends(get_current_user),
    _llm_context: None = Depends(user_llm_context),
):
    """Igual a `chat`, mas devolve a resposta em streaming (SSE).

    Cai automaticamente para a resposta inteira quando o provedor escolhido nao
    suporta streaming.
    """
    cfg = await _assistant_config(user)
    sys_prompt = _system_prompt(cfg) + _desktop_interface_guidance()
    active = await get_ready_llms()
    llm = body.llm.value if body.llm else (await pick_auto_llm(active) if active else "")
    if not llm or llm not in active:
        resp = await _llm_unavailable_response(llm or None)

        async def _unavailable():
            yield f"data: {json.dumps({'chunk': resp.content, 'done': True})}\n\n"

        return StreamingResponse(_unavailable(), media_type="text/event-stream")

    streamer = await llm_service.get_streamer(llm)
    if not streamer:
        resp = await llm_service.dispatch_single(llm, body.message, body.history, sys_prompt)
        async def _fallback():
            yield f"data: {json.dumps({'chunk': resp.content, 'done': True})}\n\n"
        return StreamingResponse(_fallback(), media_type="text/event-stream")

    async def _generate():
        try:
            async for chunk in streamer(body.message, body.history, sys_prompt):
                yield f"data: {json.dumps({'chunk': chunk, 'done': False, 'llm': llm})}\n\n"
            yield f"data: {json.dumps({'chunk': '', 'done': True, 'llm': llm})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/history/{session_id}")
async def get_history(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Devolve o historico de uma sessao de conversa."""
    try:
        async with AsyncSessionLocal() as s:
            result = await s.execute(
                select(ConversationModel)
                .where(
                    ConversationModel.session == session_id,
                    ConversationModel.user_id == user["uid"],
                )
                .order_by(ConversationModel.timestamp)
            )
            rows = result.scalars().all()
        return [
            {"id": r.id, "role": r.role, "content": r.content,
             "llm": r.llm, "timestamp": r.timestamp.isoformat()}
            for r in rows
        ]
    except Exception:
        return []


@router.delete("/history/{session_id}")
async def clear_history(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Apaga o historico de uma sessao de conversa."""
    from sqlalchemy import delete
    try:
        async with AsyncSessionLocal() as s:
            await s.execute(
                delete(ConversationModel).where(
                    ConversationModel.session == session_id,
                    ConversationModel.user_id == user["uid"],
                )
            )
            await s.commit()
    except Exception:
        pass
    return {"ok": True, "session_id": session_id}
