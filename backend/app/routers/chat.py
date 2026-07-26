from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
import uuid, json
from datetime import datetime, timezone

from ..core.database import AsyncSessionLocal, ConversationModel
from ..core.security import get_current_user
from ..core.config import get_settings
from ..models.schemas import ChatRequest, ChatResponse, LLMResponse, ResponseModeEnum
from ..services import llm_service
from ..services.computer_action_service import build_computer_action
from ..services.coding_action_service import build_coding_action
from ..services.llm_status_service import get_llm_statuses, get_ready_llms
from ..services.llm_routing_service import pick_auto_llm
from ..services.launcher_service import (
    build_auto_registration_from_launch,
    build_launch_action,
    build_launch_context,
    build_project_open_action,
    build_registration_context,
    build_shortcut_registration_action,
    find_shortcut_in_message,
)

router = APIRouter(prefix="/chat", tags=["Chat"], dependencies=[Depends(get_current_user)])
settings = get_settings()


def _system_prompt(config: dict) -> str:
    name = config.get("assistant_name", "Assistente")
    gender = config.get("gender", "f")
    user = config.get("user_name", "")
    personality = config.get("personality", "")
    language = config.get("language", "pt-BR")
    if not personality:
        article = "uma" if gender == "f" else "um"
        adj = "direta, prática e confiável" if gender == "f" else "direto, prático e confiável"
        personality = f"Você é {name}, {article} assistente pessoal {adj}."
    u = f"\nO usuário se chama {user}." if user else ""
    lang = "português brasileiro" if language == "pt-BR" else "English"
    return f"{personality}{u}\nResponda em {lang}. Seja direto, prático e útil."


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


def _registration_ack_response(action) -> LLMResponse:
    target_text = "encontrando o app no computador" if not action.target else "usando o destino informado"
    return LLMResponse(
        llm="backend",
        content=f"Vou cadastrar o atalho {action.name} {target_text}.",
    )


def _project_open_ack_response(action) -> LLMResponse:
    return LLMResponse(
        llm="backend",
        content=f"Vou abrir {action.name}.",
    )


def _computer_action_ack_response(action: dict) -> LLMResponse:
    return LLMResponse(
        llm="backend",
        content=f"Vou executar {action['name']} no computador e analisar o resultado.",
    )


def _coding_action_ack_response(action: dict) -> LLMResponse:
    return LLMResponse(
        llm="backend",
        content=f"Vou pedir para a interface inspecionar o workspace local: {action['name']}.",
    )


@router.post("/", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: dict = Depends(get_current_user),
):
    cfg = user
    sys_prompt = _system_prompt(cfg) + _desktop_interface_guidance()
    active = await get_ready_llms()

    tutor_id = cfg.get("tutor_id") or "default"
    action = None
    computer_action = build_computer_action(body.message)
    coding_action = build_coding_action(body.message)
    project_action = build_project_open_action(body.message)
    registration_action = build_shortcut_registration_action(body.message)
    if computer_action:
        action = computer_action
    elif coding_action:
        action = coding_action
    elif project_action:
        action = project_action
    elif registration_action:
        action = registration_action
        sys_prompt += build_registration_context(registration_action)
    else:
        try:
            async with AsyncSessionLocal() as db:
                shortcut = await find_shortcut_in_message(body.message, tutor_id, db)
            if shortcut:
                action = build_launch_action(shortcut)
                sys_prompt += build_launch_context(shortcut)
            else:
                # Launch intent but no registered shortcut → offer auto-registration
                auto_reg = build_auto_registration_from_launch(body.message)
                if auto_reg:
                    action = auto_reg
                    registration_action = auto_reg
                    sys_prompt += build_registration_context(auto_reg)
        except Exception:
            pass

    if computer_action:
        responses = [_computer_action_ack_response(computer_action)]
    elif coding_action:
        responses = [_coding_action_ack_response(coding_action)]
    elif project_action:
        responses = [_project_open_ack_response(project_action)]
    elif registration_action:
        responses = [_registration_ack_response(registration_action)]
    else:
        match body.mode:
            case ResponseModeEnum.multi:
                if body.llm and body.llm.value not in active:
                    responses = [await _llm_unavailable_response(body.llm.value)]
                else:
                    llms = [body.llm.value] if body.llm else active
                    if not llms:
                        responses = [await _llm_unavailable_response()]
                    else:
                        responses = await llm_service.dispatch_multi(llms, body.message, body.history, sys_prompt)

            case ResponseModeEnum.chain:
                if body.llm and body.llm.value not in active:
                    responses = [await _llm_unavailable_response(body.llm.value)]
                else:
                    llms = [body.llm.value] if body.llm else active
                    if not llms:
                        responses = [await _llm_unavailable_response()]
                    else:
                        resp = await llm_service.dispatch_chain(llms, body.message, body.history, sys_prompt)
                        responses = [resp]

            case _:
                llm = body.llm.value if body.llm else (await pick_auto_llm(active) if active else "")
                if not llm:
                    responses = [await _llm_unavailable_response()]
                elif llm not in active:
                    responses = [await _llm_unavailable_response(llm)]
                else:
                    resp = await llm_service.dispatch_single(llm, body.message, body.history, sys_prompt)
                    responses = [resp]

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


@router.post("/stream")
async def chat_stream(
    body: ChatRequest,
    user: dict = Depends(get_current_user),
):
    cfg = user
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
