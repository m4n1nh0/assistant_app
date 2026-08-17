"""Dados de demonstração usados pelo seed versionado do banco."""

import json
from datetime import datetime, timezone, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import (
    ActionAuditLogModel,
    ApprovedAutomationModel,
    AssistantProfileModel,
    CalendarEventModel,
    ConfigModel,
    ConversationModel,
    MemoryReviewModel,
    ShortcutModel,
    TutorModel,
    TutorSettingModel,
)

SEED_NAME = "demo-v1"
SEED_MARKER_KEY = f"system:database-seed:{SEED_NAME}"

# ── IDs fixos para os dados de demonstração ───────────────────────────────────
TUTOR_ID       = "default"
PROFILE_ID     = "demo-profile-default"
AUTOMATION_IDS = [f"dev-auto-{i:04d}" for i in range(1, 4)]
SESSION_ID     = "demo-session-default"
SETTING_IDS    = [f"dev-setting-{i:04d}" for i in range(1, 5)]
MESSAGE_IDS    = [f"dev-msg-{i:04d}" for i in range(8)]
EVENT_IDS      = [f"dev-evt-{i:04d}" for i in range(1, 5)]
MEMORY_IDS     = [f"dev-mem-{i:04d}" for i in range(1, 5)]
AUDIT_IDS      = [f"dev-audit-{i:04d}" for i in range(1, 5)]
SHORTCUT_IDS   = [f"dev-sc-{i:04d}" for i in range(1, 6)]

now = datetime.now(timezone.utc)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dt(delta_hours: float) -> datetime:
    return now + timedelta(hours=delta_hours)


async def _insert_config(db: AsyncSession, key: str, value: dict) -> None:
    existing = await db.get(ConfigModel, key)
    if existing is None:
        db.add(ConfigModel(key=key, value=json.dumps(value, ensure_ascii=False)))


# ── Seeder functions ──────────────────────────────────────────────────────────

async def seed_tutor(db: AsyncSession) -> None:
    existing = await db.get(TutorModel, TUTOR_ID)
    if not existing:
        db.add(TutorModel(
            id=TUTOR_ID,
            display_name="Usuário Demo",
            email="demo@assistant.local",
            timezone="America/Sao_Paulo",
            locale="pt-BR",
            notes="Perfil de demonstração para testes.",
        ))
        print("  ✓ Tutor criado")
    else:
        print("  · Tutor já existe, ignorando")


async def seed_assistant_profile(db: AsyncSession) -> None:
    result = await db.execute(
        select(AssistantProfileModel).where(
            AssistantProfileModel.tutor_id == TUTOR_ID
        )
    )
    existing = result.scalars().first()
    if not existing:
        db.add(AssistantProfileModel(
            id=PROFILE_ID,
            tutor_id=TUTOR_ID,
            assistant_name="Dani",
            gender="f",
            personality=(
                "Você é Dani, uma assistente pessoal direta e eficiente. "
                "Prefere respostas curtas e práticas. Usa linguagem natural em pt-BR. "
                "É empática, organizada e antecipa as necessidades do usuário."
            ),
            language="pt-BR",
            response_mode="single",
            tts_enabled=True,
            config={"theme": "dark", "font_size": 14},
        ))
        print("  ✓ Perfil do assistente criado")
    else:
        print("  · Perfil já existe, ignorando")


async def seed_tutor_settings(db: AsyncSession) -> None:
    settings_data = [
        {"key": "ui_theme",       "scope": "general", "value": {"theme": "dark", "accent": "#7c3aed"}},
        {"key": "hotkeys",        "scope": "general", "value": {"toggle_listen": "ctrl+space", "send_message": "enter"}},
        {"key": "tts_voice",      "scope": "voice",   "value": {"voice_id": "pt-BR-FranciscaNeural", "rate": 1.0, "pitch": 0}},
        {"key": "notifications",  "scope": "general", "value": {"sound": True, "desktop": True, "calendar_alerts": True}},
    ]
    for index, s in enumerate(settings_data):
        stmt = select(TutorSettingModel).where(
            TutorSettingModel.tutor_id == TUTOR_ID,
            TutorSettingModel.key == s["key"],
        )
        existing = (await db.execute(stmt)).scalars().first()
        if not existing:
            db.add(TutorSettingModel(
                id=SETTING_IDS[index],
                tutor_id=TUTOR_ID,
                key=s["key"],
                scope=s["scope"],
                value=s["value"],
            ))
    print("  ✓ Configurações do tutor inseridas")


async def seed_config(db: AsyncSession) -> None:
    await _insert_config(db, "assistant", {
        "_seed": SEED_NAME,
        "tutor_id": TUTOR_ID,
        "assistant_name": "Dani",
        "gender": "f",
        "user_name": "Usuário Demo",
        "personality": (
            "Você é Dani, uma assistente pessoal direta e eficiente. "
            "Prefere respostas curtas e práticas. Usa linguagem natural em pt-BR. "
            "É empática, organizada e antecipa as necessidades do usuário."
        ),
        "language": "pt-BR",
        "response_mode": "single",
        "tts_enabled": True,
    })
    await _insert_config(db, "notif", {
        "_seed": SEED_NAME,
        "telegram_enabled": False,
        "wa_enabled": False,
        "notify_15min": True,
        "reminder_minutes": 15,
        "notify_on_time": True,
    })
    print("  ✓ Config inserida")


async def seed_conversations(db: AsyncSession) -> None:
    stmt = select(ConversationModel).where(ConversationModel.session == SESSION_ID)
    existing = (await db.execute(stmt)).scalars().all()
    if existing:
        print("  · Conversas já existem, ignorando")
        return

    messages = [
        ("user",      "Olá! O que você consegue fazer?",              "claude"),
        ("assistant", "Oi! Sou a Dani, sua assistente. Posso ajudar com agenda, lembretes, automações e muito mais. O que precisa?", "claude"),
        ("user",      "Me lembra da reunião de amanhã às 9h.",        "claude"),
        ("assistant", "Anotado! Vou te avisar 15 minutos antes e na hora da reunião.", "claude"),
        ("user",      "Qual é a previsão do tempo hoje?",             "llama"),
        ("assistant", "Não tenho acesso à internet em tempo real, mas posso te ajudar a configurar uma integração para isso.", "llama"),
        ("user",      "Cria uma automação para me lembrar de beber água a cada hora.",  "claude"),
        ("assistant", "Feito! Criei um lembrete de hidratação das 8h às 20h, de hora em hora, nos dias úteis.", "claude"),
    ]

    for i, (role, content, llm) in enumerate(messages):
        db.add(ConversationModel(
            id=MESSAGE_IDS[i],
            role=role,
            content=content,
            llm=llm,
            session=SESSION_ID,
            timestamp=now - timedelta(minutes=(len(messages) - i) * 3),
            metadata_={"seed": SEED_NAME},
        ))
    print(f"  ✓ {len(messages)} mensagens de conversa inseridas")


async def seed_calendar_events(db: AsyncSession) -> None:
    events = [
        {
            "id": "dev-evt-0001",
            "title": "Daily — Dev Team",
            "start_time": _dt(1),
            "end_time": _dt(1.5),
            "source": "google",
            "meeting_url": "https://meet.google.com/dev-daily-link",
            "description": "Daily standup da equipe de desenvolvimento.",
            "notified_15": False,
            "notified_0": False,
        },
        {
            "id": "dev-evt-0002",
            "title": "1:1 com Product",
            "start_time": _dt(3),
            "end_time": _dt(4),
            "source": "google",
            "meeting_url": "https://meet.google.com/dev-one-on-one",
            "description": None,
            "notified_15": False,
            "notified_0": False,
        },
        {
            "id": "dev-evt-0003",
            "title": "Sprint Review",
            "start_time": _dt(25),
            "end_time": _dt(26.5),
            "source": "outlook",
            "meeting_url": "https://teams.microsoft.com/dev-sprint-review",
            "description": "Revisão do sprint atual com stakeholders.",
            "notified_15": False,
            "notified_0": False,
        },
        {
            "id": "dev-evt-0004",
            "title": "Almoço com cliente",
            "start_time": _dt(-48),
            "end_time": _dt(-47),
            "source": "google",
            "meeting_url": None,
            "description": "Evento passado — não deve aparecer nas próximas.",
            "notified_15": True,
            "notified_0": True,
        },
    ]

    for e in events:
        existing = await db.get(CalendarEventModel, e["id"])
        if not existing:
            db.add(CalendarEventModel(**e, raw={"seed": SEED_NAME}))

    print(f"  ✓ {len(events)} eventos de calendário inseridos")


async def seed_memory_reviews(db: AsyncSession) -> None:
    reviews = [
        {
            "id": "dev-mem-0001",
            "tutor_id": TUTOR_ID,
            "category": "tutor_preferences",
            "content": "O usuário prefere respostas curtas e diretas, sem introduções longas.",
            "source": "assistant",
            "status": "pending",
            "confidence": 0.92,
        },
        {
            "id": "dev-mem-0002",
            "tutor_id": TUTOR_ID,
            "category": "behavior_guidelines",
            "content": "Nunca enviar notificações depois das 22h.",
            "source": "user",
            "status": "approved",
            "confidence": 1.0,
            "reviewer_note": "Confirmado pelo usuário explicitamente.",
            "reviewed_at": now - timedelta(days=2),
        },
        {
            "id": "dev-mem-0003",
            "tutor_id": TUTOR_ID,
            "category": "automation_knowledge",
            "content": "O usuário usa GitHub Actions para CI/CD nos projetos pessoais.",
            "source": "assistant",
            "status": "approved",
            "confidence": 0.60,
            "reviewer_note": "Informação imprecisa, foi descartada.",
            "reviewed_at": now - timedelta(days=1),
        },
        {
            "id": "dev-mem-0004",
            "tutor_id": TUTOR_ID,
            "category": "approved_instructions",
            "content": "Ao criar lembretes de reunião, sempre incluir o link da videochamada.",
            "source": "user",
            "status": "pending",
            "confidence": 0.98,
        },
    ]

    for r in reviews:
        existing = await db.get(MemoryReviewModel, r["id"])
        if not existing:
            db.add(MemoryReviewModel(**r, metadata_={"seed": SEED_NAME}))

    print(f"  ✓ {len(reviews)} memórias inseridas")


async def seed_automations(db: AsyncSession) -> None:
    automations = [
        {
            "id": AUTOMATION_IDS[0],
            "tutor_id": TUTOR_ID,
            "title": "Lembrete de hidratação",
            "description": "Notifica para beber água a cada hora durante o horário de trabalho.",
            "trigger": "schedule",
            "instructions": "Enviar mensagem: 'Hora de beber água! 💧' via Telegram.",
            "schedule": {"cron": "0 8-20 * * 1-5"},
            "risk_level": "low",
            "enabled": True,
            "metadata_": {"category": "saúde", "seed": SEED_NAME},
        },
        {
            "id": AUTOMATION_IDS[1],
            "tutor_id": TUTOR_ID,
            "title": "Resumo diário de agenda",
            "description": "Envia um resumo dos compromissos do dia às 7h30.",
            "trigger": "schedule",
            "instructions": "Buscar eventos do Google Calendar do dia e enviar resumo formatado via Telegram.",
            "schedule": {"cron": "30 7 * * 1-5"},
            "risk_level": "low",
            "enabled": True,
            "metadata_": {"category": "produtividade", "seed": SEED_NAME},
        },
        {
            "id": AUTOMATION_IDS[2],
            "tutor_id": TUTOR_ID,
            "title": "Backup semanal de notas",
            "description": "Exporta memórias aprovadas para arquivo JSON toda sexta às 18h.",
            "trigger": "schedule",
            "instructions": "Exportar todas as memórias com status=approved para /data/backup/memories_{date}.json",
            "schedule": {"cron": "0 18 * * 5"},
            "risk_level": "medium",
            "enabled": False,
            "metadata_": {"category": "backup", "seed": SEED_NAME},
        },
    ]

    for a in automations:
        existing = await db.get(ApprovedAutomationModel, a["id"])
        if not existing:
            db.add(ApprovedAutomationModel(**a))

    print(f"  ✓ {len(automations)} automações inseridas")


async def seed_audit_log(db: AsyncSession) -> None:
    logs = [
        {
            "id": "dev-audit-0001",
            "tutor_id": TUTOR_ID,
            "automation_id": AUTOMATION_IDS[0],
            "action_type": "telegram_notify",
            "status": "executed",
            "request": {"message": "Hora de beber água! 💧"},
            "result": {"ok": True, "message_id": 12345},
            "created_at": now - timedelta(hours=1),
        },
        {
            "id": "dev-audit-0002",
            "tutor_id": TUTOR_ID,
            "automation_id": AUTOMATION_IDS[1],
            "action_type": "calendar_summary",
            "status": "executed",
            "request": {"date": str(now.date())},
            "result": {"events_found": 3, "summary_sent": True},
            "created_at": _dt(-7.5),
        },
        {
            "id": "dev-audit-0003",
            "tutor_id": TUTOR_ID,
            "automation_id": None,
            "action_type": "memory_approved",
            "status": "executed",
            "request": {"memory_id": "dev-mem-0002"},
            "result": {"qdrant_indexed": False},
            "created_at": now - timedelta(days=2),
        },
        {
            "id": "dev-audit-0004",
            "tutor_id": TUTOR_ID,
            "automation_id": AUTOMATION_IDS[0],
            "action_type": "telegram_notify",
            "status": "failed",
            "request": {"message": "Hora de beber água! 💧"},
            "result": {"error": "Connection timeout"},
            "created_at": now - timedelta(hours=2),
        },
    ]

    for log in logs:
        existing = await db.get(ActionAuditLogModel, log["id"])
        if not existing:
            db.add(ActionAuditLogModel(**log))

    print(f"  ✓ {len(logs)} registros de auditoria inseridos")


async def seed_shortcuts(db: AsyncSession) -> None:
    shortcuts = [
        {
            "id": "dev-sc-0001",
            "tutor_id": TUTOR_ID,
            "name": "Spotify",
            "type": "url",
            "target": "https://open.spotify.com",
            "aliases": ["spotify", "música", "musica", "player"],
            "description": "Player de música",
        },
        {
            "id": "dev-sc-0002",
            "tutor_id": TUTOR_ID,
            "name": "VS Code",
            "type": "url",
            "target": "https://vscode.dev",
            "aliases": ["vscode", "vs code", "editor", "código", "codigo"],
            "description": "Editor de código",
        },
        {
            "id": "dev-sc-0003",
            "tutor_id": TUTOR_ID,
            "name": "YouTube",
            "type": "url",
            "target": "https://youtube.com",
            "aliases": ["youtube", "yt", "vídeos", "videos"],
            "description": "Plataforma de vídeos",
        },
        {
            "id": "dev-sc-0004",
            "tutor_id": TUTOR_ID,
            "name": "GitHub",
            "type": "url",
            "target": "https://github.com",
            "aliases": ["github", "git", "repositório", "repositorio"],
            "description": "Repositórios de código",
        },
        {
            "id": "dev-sc-0005",
            "tutor_id": TUTOR_ID,
            "name": "WhatsApp Web",
            "type": "url",
            "target": "https://web.whatsapp.com",
            "aliases": ["whatsapp", "zap", "mensagens"],
            "description": "WhatsApp no navegador",
        },
    ]

    for s in shortcuts:
        existing = await db.get(ShortcutModel, s["id"])
        if not existing:
            db.add(ShortcutModel(**s))

    print(f"  ✓ {len(shortcuts)} atalhos inseridos")


# ── Limpeza segura dos dados de demonstração ──────────────────────────────────

async def reset_demo_data(db: AsyncSession) -> None:
    print("  ⚠ Apagando somente os dados de demonstração...")
    await db.execute(delete(ActionAuditLogModel).where(ActionAuditLogModel.id.in_(AUDIT_IDS)))
    await db.execute(delete(ApprovedAutomationModel).where(ApprovedAutomationModel.id.in_(AUTOMATION_IDS)))
    await db.execute(delete(MemoryReviewModel).where(MemoryReviewModel.id.in_(MEMORY_IDS)))
    await db.execute(delete(TutorSettingModel).where(TutorSettingModel.id.in_(SETTING_IDS)))
    await db.execute(delete(AssistantProfileModel).where(AssistantProfileModel.id == PROFILE_ID))
    await db.execute(delete(ConversationModel).where(ConversationModel.id.in_(MESSAGE_IDS)))
    await db.execute(delete(CalendarEventModel).where(CalendarEventModel.id.in_(EVENT_IDS)))
    await db.execute(delete(ShortcutModel).where(ShortcutModel.id.in_(SHORTCUT_IDS)))

    tutor = await db.get(TutorModel, TUTOR_ID)
    if tutor is not None and tutor.email == "demo@assistant.local":
        await db.delete(tutor)

    for key in ("assistant", "notif"):
        row = await db.get(ConfigModel, key)
        if row is None:
            continue
        try:
            value = json.loads(row.value)
        except (TypeError, json.JSONDecodeError):
            value = {}
        if value.get("_seed") == SEED_NAME:
            await db.delete(row)

    marker = await db.get(ConfigModel, SEED_MARKER_KEY)
    if marker is not None:
        await db.delete(marker)
    print("  ✓ Reset concluído")


async def seed_demo_data(db: AsyncSession) -> None:
    """Adiciona os dados demo à transação atual sem efetuar commit."""
    global now
    now = datetime.now(timezone.utc)

    print("\n🌱 Seed de demonstração iniciando...\n")
    print("── Tutor")
    await seed_tutor(db)
    print("── Perfil do assistente")
    await seed_assistant_profile(db)
    print("── Configurações do tutor")
    await seed_tutor_settings(db)
    print("── Config global")
    await seed_config(db)
    print("── Conversas")
    await seed_conversations(db)
    print("── Calendário")
    await seed_calendar_events(db)
    print("── Memórias")
    await seed_memory_reviews(db)
    print("── Automações")
    await seed_automations(db)
    print("── Auditoria")
    await seed_audit_log(db)
    print("── Atalhos")
    await seed_shortcuts(db)
