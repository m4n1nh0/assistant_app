import json
import asyncio
import uuid
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from ..core.config import get_settings
from ..core.database import AsyncSessionLocal, ConfigModel, scoped_config_key
from ..core.security import resolve_token_user
from ..models.schemas import ResponseModeEnum, Message
from ..services import llm_service, notification_service
from ..services.calendar_service import fetch_all_account_events
from ..services.chat_graph_service import run_chat_graph
from ..services.llm_status_service import get_ready_llms
from ..services.llm_routing_service import pick_auto_llm
from ..services.runtime_config_service import load_notif_config
from ..services.microsoft_identity_service import hydrate_microsoft_account
from ..services.voice_service import transcribe_audio, text_to_speech

router = APIRouter(tags=["WebSocket"])
settings = get_settings()


def _json_value(row: ConfigModel | None, fallback):
    if row is None or not row.value:
        return fallback
    try:
        return json.loads(row.value)
    except Exception:
        return fallback


async def _load_account_store(db, key: str) -> list[dict]:
    data = _json_value(await db.get(ConfigModel, key), {"accounts": []})
    if isinstance(data, list):
        accounts = data
    elif isinstance(data, dict):
        accounts = data.get("accounts", [])
    else:
        accounts = []
    return [item for item in accounts if isinstance(item, dict)]


async def _load_calendar_accounts(
    user_id: str,
) -> tuple[list[dict], list[dict]]:
    async with AsyncSessionLocal() as db:
        google_accounts = await _load_account_store(
            db, scoped_config_key(user_id, "calendar_google_accounts")
        )
        microsoft_accounts = await _load_account_store(
            db, scoped_config_key(user_id, "calendar_microsoft_accounts")
        )

        google_legacy = _json_value(
            await db.get(
                ConfigModel,
                scoped_config_key(user_id, "calendar_google"),
            ),
            {},
        )
        if google_legacy.get("refresh_token"):
            google_accounts.append({
                "id": "google_legacy",
                "label": google_legacy.get("label") or "Google Calendar",
                "client_id": google_legacy.get("client_id", ""),
                "client_secret": google_legacy.get("client_secret", ""),
                "refresh_token": google_legacy.get("refresh_token", ""),
            })

        microsoft_legacy = _json_value(
            await db.get(
                ConfigModel,
                scoped_config_key(user_id, "calendar_microsoft"),
            ),
            {},
        )
        if microsoft_legacy.get("refresh_token"):
            microsoft_accounts.append({
                "id": "microsoft_legacy",
                "label": microsoft_legacy.get("label") or "Microsoft Calendar",
                "client_id": microsoft_legacy.get("client_id", ""),
                "client_secret": microsoft_legacy.get("client_secret", ""),
                "tenant_id": microsoft_legacy.get("tenant_id", "common"),
                "refresh_token": microsoft_legacy.get("refresh_token", ""),
            })

    return (
        [account for account in google_accounts if account.get("refresh_token")],
        [
            hydrated
            for account in microsoft_accounts
            if (hydrated := hydrate_microsoft_account(account)).get("refresh_token")
        ],
    )


class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, WebSocket] = {}
        self.groups: Dict[str, Set[str]] = {}
        self.connection_users: Dict[str, str] = {}

    async def connect(self, ws: WebSocket, session_id: str, user_id: str):
        await ws.accept()
        self.active[session_id] = ws
        self.connection_users[session_id] = user_id
        logger.info(f"WS connected: {session_id}")

    def disconnect(self, session_id: str):
        self.active.pop(session_id, None)
        self.connection_users.pop(session_id, None)
        logger.info(f"WS disconnected: {session_id}")

    async def send(self, session_id: str, data: dict):
        ws = self.active.get(session_id)
        if ws:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False, default=str))
            except Exception as e:
                logger.warning(f"WS send error ({session_id}): {e}")
                self.disconnect(session_id)

    async def broadcast(self, data: dict):
        dead = []
        for sid, ws in self.active.items():
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False, default=str))
            except Exception:
                dead.append(sid)
        for sid in dead:
            self.disconnect(sid)

    async def broadcast_user(self, user_id: str, data: dict):
        dead = []
        for sid, ws in self.active.items():
            if self.connection_users.get(sid) != user_id:
                continue
            try:
                await ws.send_text(
                    json.dumps(data, ensure_ascii=False, default=str)
                )
            except Exception:
                dead.append(sid)
        for sid in dead:
            self.disconnect(sid)


manager = ConnectionManager()


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(ws: WebSocket, session_id: str, token: str = ""):
    try:
        async with AsyncSessionLocal() as db:
            user = await resolve_token_user(token, db)
    except Exception:
        await ws.close(code=4401, reason="Não autenticado")
        return

    connection_id = f"{user['uid']}:{session_id}"
    await manager.connect(ws, connection_id, user["uid"])

    await manager.send(connection_id, {
        "type": "status",
        "payload": {
            "connected": True,
            "session_id": session_id,
            "active_llms": settings.active_llms,
            "server": "assistente-backend v1.0",
        },
    })

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(connection_id, "JSON inválido")
                continue

            msg_type = msg.get("type", "")
            payload  = msg.get("payload", {})

            match msg_type:
                case "chat":
                    await _handle_chat(
                        connection_id,
                        payload,
                        user.get("tutor_id") or "default",
                        user["uid"],
                    )
                case "chat_stream":
                    await _handle_chat_stream(connection_id, payload)
                case "voice_transcribe":
                    await _handle_voice_transcribe(connection_id, payload)
                case "tts":
                    await _handle_tts(connection_id, payload)
                case "calendar_sync":
                    await _handle_calendar_sync(
                        connection_id, payload, user["uid"]
                    )
                case "notify":
                    await _handle_notify(connection_id, payload, user["uid"])
                case "ping":
                    await manager.send(
                        connection_id, {"type": "pong", "payload": {}}
                    )
                case _:
                    await _send_error(
                        connection_id, f"Tipo desconhecido: {msg_type}"
                    )

    except WebSocketDisconnect:
        manager.disconnect(connection_id)
    except Exception as e:
        logger.error(f"WS error ({session_id}): {e}")
        manager.disconnect(connection_id)


def _build_system(payload: dict) -> str:
    name = payload.get("assistant_name", "Assistente")
    user = payload.get("user_name", "")
    personality = payload.get("personality", "")
    language = payload.get("language", "pt-BR")
    base = personality or f"Você é {name}, um assistente pessoal direto, prático e confiável."
    u = f"\nO usuário se chama {user}." if user else ""
    lang = "português brasileiro" if language == "pt-BR" else "English"
    return f"{base}{u}\nResponda em {lang}. Seja direto, prático e útil."


def _parse_history(raw: list) -> list[Message]:
    msgs = []
    for m in raw:
        try:
            msgs.append(Message(role=m["role"], content=m["content"]))
        except Exception:
            pass
    return msgs


async def _handle_chat(
    session_id: str,
    payload: dict,
    tutor_id: str = "default",
    user_id: str = "",
):
    message  = payload.get("message", "").strip()
    mode_str = payload.get("mode", "single")
    llm_id   = payload.get("llm")
    history  = _parse_history(payload.get("history", []))
    sys_p    = _build_system(payload)
    active   = await get_ready_llms()

    if not message:
        await _send_error(session_id, "Mensagem vazia")
        return

    await manager.send(session_id, {"type": "thinking", "payload": {"llms": [llm_id] if llm_id else active}})

    try:
        mode = ResponseModeEnum(mode_str)
        graph_result = await run_chat_graph(
            message=message,
            history=history,
            mode=mode,
            requested_llm=llm_id,
            active_llms=active,
            system_prompt=sys_p,
            tutor_id=tutor_id,
            user_id=user_id,
            timezone=payload.get("timezone") or "America/Sao_Paulo",
        )
        responses = graph_result["responses"]
        action = graph_result.get("action")
        action_payload = (
            action.model_dump()
            if hasattr(action, "model_dump")
            else action
        )

        await manager.send(session_id, {
            "type": "chat_response",
            "payload": {
                "mode": mode_str,
                "responses": [r.model_dump() for r in responses],
                "action": action_payload,
            },
        })
    except Exception as e:
        await _send_error(session_id, str(e))


async def _handle_chat_stream(session_id: str, payload: dict):
    message = payload.get("message", "").strip()
    llm_id  = payload.get("llm")
    history = _parse_history(payload.get("history", []))
    sys_p   = _build_system(payload)
    active  = await get_ready_llms()

    llm = llm_id or (await pick_auto_llm(active) if active else "claude")
    streamer = await llm_service.get_streamer(llm)

    if not streamer:
        r = await llm_service.dispatch_single(llm, message, history, sys_p)
        await manager.send(session_id, {
            "type": "stream_chunk",
            "payload": {"chunk": r.content, "llm": llm, "done": False},
        })
        await manager.send(session_id, {
            "type": "stream_end",
            "payload": {"llm": llm, "done": True},
        })
        return

    full = ""
    try:
        async for chunk in streamer(message, history, sys_p):
            full += chunk
            await manager.send(session_id, {
                "type": "stream_chunk",
                "payload": {"chunk": chunk, "llm": llm, "done": False},
            })
        await manager.send(session_id, {
            "type": "stream_end",
            "payload": {"llm": llm, "full_response": full, "done": True},
        })
    except Exception as e:
        await _send_error(session_id, str(e))


async def _handle_voice_transcribe(session_id: str, payload: dict):
    import base64
    audio_b64 = payload.get("audio_b64", "")
    language  = payload.get("language", "pt")

    if not audio_b64:
        await _send_error(session_id, "Áudio não fornecido")
        return

    try:
        audio_bytes = base64.b64decode(audio_b64)
        result = await transcribe_audio(audio_bytes, language)
        await manager.send(session_id, {
            "type": "transcription",
            "payload": result.model_dump(),
        })
    except Exception as e:
        await _send_error(session_id, f"Transcrição falhou: {e}")


async def _handle_tts(session_id: str, payload: dict):
    import base64
    text     = payload.get("text", "")[:600]
    language = payload.get("language", "pt-BR")
    speed    = payload.get("speed")

    if not text:
        return
    try:
        audio_bytes = await text_to_speech(text, language, speed)
        audio_b64 = base64.b64encode(audio_bytes).decode()
        await manager.send(session_id, {
            "type": "tts_audio",
            "payload": {"audio_b64": audio_b64, "format": "mp3"},
        })
    except Exception as e:
        await _send_error(session_id, f"TTS falhou: {e}")


async def _handle_calendar_sync(
    session_id: str,
    payload: dict,
    user_id: str,
):
    google_accounts, microsoft_accounts = await _load_calendar_accounts(user_id)
    try:
        events = await fetch_all_account_events(google_accounts, microsoft_accounts)
        await manager.send(session_id, {
            "type": "calendar_events",
            "payload": {
                "events": [e.model_dump() for e in events],
                "total": len(events),
            },
        })
    except Exception as e:
        await _send_error(session_id, f"Calendar sync falhou: {e}")


async def _handle_notify(
    session_id: str,
    payload: dict,
    user_id: str,
):
    message  = payload.get("message", "")
    channels = payload.get("channels", ["telegram", "whatsapp"])

    cfg = await load_notif_config(user_id=user_id)
    result = await notification_service.send_notification(message, cfg, channels)
    await manager.send(session_id, {
        "type": "notify_result",
        "payload": result.model_dump(),
    })


async def _send_error(session_id: str, detail: str):
    await manager.send(session_id, {"type": "error", "payload": {"detail": detail}})


async def broadcast_event_reminder(
    user_id: str,
    event_title: str,
    minutes_left: int,
):
    await manager.broadcast_user(user_id, {
        "type": "event_reminder",
        "payload": {"title": event_title, "minutes_left": minutes_left},
    })
