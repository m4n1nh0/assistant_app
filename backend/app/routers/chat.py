"""Endpoints do chat: conversa, streaming e historico por sessao.

As rotas montam o prompt de sistema com a persona do usuario, chamam o grafo em
`app.services.chat_graph_service` e persistem o par pergunta/resposta. Tudo aqui
exige autenticacao e trabalha sempre no escopo da conta - historico de sessao
nunca cruza usuarios.

Todo turno de conversa, inclusive o do streaming, passa pelo grafo: quem fala com os
provedores de IA e o orquestrador (ou o grafo local), nunca a rota. O streaming entrega a
resposta pronta em pedacos.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
import uuid, json
from contextlib import ExitStack
from datetime import datetime, timezone

from ..core.database import (
    AssistantProfileModel,
    AsyncSessionLocal,
    ConversationModel,
    TutorModel,
)
from shared.observability import bind
from ..core.security import get_current_user
from ..models.schemas import (
    ChatLogRequest,
    ChatRequest,
    ChatResponse,
    LLMResponse,
    ToolReadResult,
)
from ..services.chat_graph_service import run_chat_graph, stream_chat_graph
from ..services.device_catalog_service import session_device
from ..services.llm_status_service import get_llm_statuses, get_ready_llms
from ..services.stream_text import text_chunks
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
        "\n\nO que vale para a tela do computador nao vale para o Modo Aula. "
        "O cadastro do professor - disciplinas, turmas, alunos, aulas gravadas, "
        "quizzes, banco de questoes, resultado de quiz aplicado e tempo de "
        "estudo - esta no banco de dados do proprio app e voce le por ferramenta, "
        "sem depender de captura de janela. Quando a pergunta for sobre esses "
        "dados, consulte a ferramenta antes de responder: dizer que nao tem "
        "acesso, ou pedir que o usuario cole a questao ou autorize a captura da "
        "tela para ler o que ja esta cadastrado, e erro."
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
    return await _run_chat_turn(body, user)


async def _turn_kwargs(body: ChatRequest, user: dict) -> tuple[str, dict]:
    """Persona, provedores ativos e fuso: tudo que o grafo precisa para rodar o turno."""
    cfg = await _assistant_config(user)
    sys_prompt = _system_prompt(cfg) + _desktop_interface_guidance()
    active = await get_ready_llms()

    tutor_id = cfg.get("tutor_id") or "default"
    timezone_name = await _profile_timezone(tutor_id)
    return tutor_id, dict(
        message=body.message,
        history=body.history,
        mode=body.mode,
        requested_llm=body.llm.value if body.llm else None,
        active_llms=active,
        system_prompt=sys_prompt,
        tutor_id=tutor_id,
        user_id=user["uid"],
        timezone=timezone_name,
        # A sessao e o `thread_id` do checkpoint: e o que permite retomar a
        # execucao em vez de refazer a conversa inteira.
        conversation_id=body.session_id,
    )


async def _run_chat_turn(body: ChatRequest, user: dict) -> ChatResponse:
    """Um turno completo: persona, grafo, historico gravado e resposta montada.

    E o que o `/chat/` e o `/chat/stream` compartilham, para nenhum dos dois falar com um
    provedor por fora do grafo.
    """
    tutor_id, kwargs = await _turn_kwargs(body, user)
    # Amarra a maquina desta sessao: as capacidades que a interface publicou
    # pelo WebSocket so aparecem para o agente enquanto este `with` durar, e so
    # para a conversa desta conta.
    with session_device(user["uid"], body.session_id), bind(
        conversation_id=body.session_id, tenant_id=tutor_id, user_id=user["uid"]
    ):
        graph_result = await run_chat_graph(**kwargs)
    return await _finish_turn(body, user, graph_result)


async def _stream_chat_turn(body: ChatRequest, user: dict):
    """O mesmo turno de `_run_chat_turn`, entregando o texto aos pedacos enquanto o grafo roda.

    Gera `("reset", None)` quando o modelo recomeca (descarte o texto parcial), `("delta", texto)`
    a cada pedaco e, por ultimo, `("final", ChatResponse)` ja com a conversa gravada. O `final` e
    a verdade: o texto transmitido e uma previa.
    """
    tutor_id, kwargs = await _turn_kwargs(body, user)
    state = None
    # Sem `with`: este gerador pode ser encerrado fora da tarefa que o criou (a interface fechou a
    # conexao no meio), e aí o `reset` de um `ContextVar` acusa "token de outro contexto".
    contexts = ExitStack()
    contexts.enter_context(session_device(user["uid"], body.session_id))
    contexts.enter_context(
        bind(conversation_id=body.session_id, tenant_id=tutor_id, user_id=user["uid"])
    )
    try:
        async for event in stream_chat_graph(**kwargs):
            kind = event.get("type")
            if kind == "final":
                state = event["state"]
            elif kind == "delta":
                yield "delta", event.get("text", "")
            elif kind == "reset":
                yield "reset", None
    finally:
        try:
            contexts.close()
        except ValueError:
            pass  # contexto ja descartado junto com a tarefa que o abriu
    yield "final", await _finish_turn(body, user, state or {})


async def _finish_turn(body: ChatRequest, user: dict, graph_result: dict) -> ChatResponse:
    """Grava a troca e monta a resposta a partir do estado final do grafo."""
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
        tool_results=_tool_results(graph_result.get("tool_trace")),
        action=action,
    )


def _tool_results(trace: object) -> list[ToolReadResult]:
    """Leituras estruturadas do rastro de ferramentas, para a interface.

    So passa o que veio com `data`: ferramenta de acao nao tem leitura a
    mostrar, e rastro sem dado viraria card vazio na tela. Entrada malformada e
    descartada em silencio - o rastro e informacao de apoio, e derrubar a
    resposta do chat por causa dele seria trocar o essencial pelo acessorio.
    """
    results: list[ToolReadResult] = []
    for entry in trace or []:
        if not isinstance(entry, dict):
            continue
        data = entry.get("data")
        if not isinstance(data, dict) or not data.get("kind"):
            continue
        try:
            results.append(ToolReadResult(
                tool=str(entry.get("tool") or ""),
                kind=str(data.get("kind")),
                title=str(data.get("title") or ""),
                total=int(data.get("total") or 0),
                truncated=bool(data.get("truncated")),
                items=[item for item in data.get("items") or []
                       if isinstance(item, dict)],
            ))
        except (TypeError, ValueError):
            continue
    return results


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
    """Igual a `chat`, mas devolve a resposta aos pedacos enquanto ela e escrita (SSE).

    O turno passa pelo grafo, como em `/chat/`: ferramentas, agenda, atalhos e busca nas aulas
    valem aqui tambem, e a conversa e gravada. Eventos, um `data:` JSON por linha:

    - `{"reset": true, "done": false}`: o modelo recomecou (outra volta, retentativa); descarte o
      texto parcial.
    - `{"chunk": "...", "done": false}`: mais um pedaco da resposta.
    - `{"chunk": "", "done": true, "content": ..., "llm": ..., "action": ..., "tool_results": ...}`:
      o fim. `content` e o texto final e **substitui** o que foi acumulado.
    - `{"error": "...", "done": true}`: o turno falhou.

    So o modo `single` transmite enquanto escreve; os demais chegam inteiros no fim, divididos em
    pedacos.
    """
    active = await get_ready_llms()
    requested = body.llm.value if body.llm else None
    if not active or (requested and requested not in active):
        resp = await _llm_unavailable_response(requested)

        async def _unavailable():
            # `chunk` fica por compatibilidade com quem le so ele; `content` e o formato do final.
            event = {
                "chunk": resp.content,
                "content": resp.content,
                "llm": resp.llm,
                "is_error": True,
                "done": True,
            }
            yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(_unavailable(), media_type="text/event-stream")

    async def _generate():
        streamed = False
        try:
            async for kind, value in _stream_chat_turn(body, user):
                if kind == "reset":
                    streamed = False
                    yield f"data: {json.dumps({'reset': True, 'done': False})}\n\n"
                elif kind == "delta":
                    streamed = True
                    yield f"data: {json.dumps({'chunk': value, 'done': False})}\n\n"
                else:
                    result: ChatResponse = value
                    reply = next((r for r in result.responses if not r.is_error), None) or (
                        result.responses[0] if result.responses else None
                    )
                    content = reply.content if reply else ""
                    llm = reply.llm if reply else (requested or "")
                    if not streamed:
                        # Nada foi escrito ao vivo (acao, atalho, modo multi): entrega o texto pronto.
                        for piece in text_chunks(content):
                            yield f"data: {json.dumps({'chunk': piece, 'done': False})}\n\n"
                    final = {
                        "chunk": "",
                        "done": True,
                        "content": content,
                        "llm": llm,
                        "is_error": bool(reply.is_error) if reply else False,
                        "action": (
                            result.action.model_dump(mode="json")
                            if hasattr(result.action, "model_dump")
                            else result.action
                        ),
                        "tool_results": [t.model_dump(mode="json") for t in result.tool_results],
                    }
                    yield f"data: {json.dumps(final)}\n\n"
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
