import os
import json
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import uuid
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Boolean,
    Text,
    Integer,
    JSON,
    Float,
    UniqueConstraint,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timezone
from loguru import logger
from .config import get_settings

settings = get_settings()

# Build database_url: prefer DATABASE_URL env var, else construct from MYSQL_* vars
def _get_database_url():
    # First try to use DATABASE_URL directly (if it's set and not empty)
    if settings.database_url and not settings.database_url.startswith("mysql+aiomysql://assistant:assistant@localhost"):
        return settings.database_url
    
    # Otherwise construct from individual MYSQL_* environment variables.
    # Support both the docker-compose naming (MYSQL_HOST) and Railway's
    # native MySQL plugin naming (MYSQLHOST, no underscore).
    mysql_user = os.getenv("MYSQL_USER") or os.getenv("MYSQLUSER", "assistant")
    mysql_password = os.getenv("MYSQL_PASSWORD") or os.getenv("MYSQLPASSWORD", "assistant")
    mysql_host = os.getenv("MYSQL_HOST") or os.getenv("MYSQLHOST", "localhost")
    mysql_port = os.getenv("MYSQL_PORT") or os.getenv("MYSQLPORT", "3306")
    mysql_database = os.getenv("MYSQL_DATABASE") or os.getenv("MYSQLDATABASE", "assistant")
    
    db_url = f"mysql+aiomysql://{mysql_user}:{mysql_password}@{mysql_host}:{mysql_port}/{mysql_database}"
    return db_url

database_url = _get_database_url()

engine = create_async_engine(
    database_url,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


class ConversationModel(Base):
    __tablename__ = "conversations"
    id        = Column(String(64), primary_key=True)
    role      = Column(String(32), nullable=False)
    content   = Column(Text, nullable=False)
    llm       = Column(String(80), nullable=True)
    user_id   = Column(String(64), nullable=True, index=True)
    session   = Column(String(120), nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    metadata_ = Column("metadata", JSON, default=dict)


class CalendarEventModel(Base):
    __tablename__ = "calendar_events"
    id           = Column(String(255), primary_key=True)
    user_id      = Column(String(64), nullable=True, index=True)
    title        = Column(String(255), nullable=False)
    start_time   = Column(DateTime, nullable=False)
    end_time     = Column(DateTime, nullable=True)
    source       = Column(String(32), nullable=False)
    meeting_url  = Column(String(1024), nullable=True)
    description  = Column(Text, nullable=True)
    notified_15  = Column(Boolean, default=False)
    notified_0   = Column(Boolean, default=False)
    raw          = Column(JSON, default=dict)


class ConfigModel(Base):
    __tablename__ = "config"
    key   = Column("config_key", String(180), primary_key=True)
    value = Column(Text, nullable=False)


class UserModel(Base):
    __tablename__ = "users"
    id            = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    username      = Column(String(120), nullable=False, unique=True, index=True)
    email         = Column(String(255), nullable=True, unique=True, index=True)
    role          = Column(String(32), nullable=False, default="user")
    tutor_id      = Column(String(64), nullable=True, index=True)
    is_active     = Column(Boolean, nullable=False, default=True)
    auth_version  = Column(Integer, nullable=False, default=0)
    password_hash = Column(String(255), nullable=False)
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class RegistrationInviteModel(Base):
    __tablename__ = "registration_invites"
    id              = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    token_hash      = Column(String(64), nullable=False, unique=True, index=True)
    recipient_email = Column(String(255), nullable=False)
    role            = Column(String(32), nullable=False, default="user")
    invited_by      = Column(String(64), nullable=True, index=True)
    expires_at      = Column(DateTime, nullable=False, index=True)
    used_at         = Column(DateTime, nullable=True)
    revoked_at      = Column(DateTime, nullable=True)
    created_at      = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )


class PasswordResetTokenModel(Base):
    __tablename__ = "password_reset_tokens"
    id         = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = Column(String(64), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at    = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )


class TutorModel(Base):
    __tablename__ = "tutors"
    id           = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    display_name = Column(String(180), nullable=False)
    email        = Column(String(255), nullable=True, unique=True)
    timezone     = Column(String(80), nullable=False, default="America/Sao_Paulo")
    locale       = Column(String(16), nullable=False, default="pt-BR")
    notes        = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class AssistantProfileModel(Base):
    __tablename__ = "assistant_profiles"
    id             = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id       = Column(String(64), nullable=False, index=True)
    assistant_name = Column(String(180), nullable=False, default="Assistant")
    gender         = Column(String(1), nullable=False, default="f")
    personality    = Column(Text, nullable=True)
    language       = Column(String(16), nullable=False, default="pt-BR")
    response_mode  = Column(String(32), nullable=False, default="single")
    tts_enabled    = Column(Boolean, default=True)
    config         = Column(JSON, default=dict)
    created_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class TutorSettingModel(Base):
    __tablename__ = "tutor_settings"
    id         = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id   = Column(String(64), nullable=False, index=True)
    key        = Column("setting_key", String(180), nullable=False, index=True)
    value      = Column(JSON, default=dict)
    scope      = Column(String(80), nullable=False, default="general")
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class CredentialModel(Base):
    __tablename__ = "credential_refs"
    id         = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id   = Column(String(64), nullable=False, index=True)
    provider   = Column(String(120), nullable=False)
    secret_ref = Column(Text, nullable=False)
    metadata_  = Column("metadata", JSON, default=dict)
    enabled    = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class MemoryReviewModel(Base):
    __tablename__ = "memory_review_queue"
    id              = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id        = Column(String(64), nullable=False, index=True)
    category        = Column(String(80), nullable=False, index=True)
    content         = Column(Text, nullable=False)
    source          = Column(String(120), nullable=False, default="assistant")
    status          = Column(String(32), nullable=False, default="pending", index=True)
    confidence      = Column(Float, nullable=False, default=1.0)
    qdrant_point_id = Column(String(64), nullable=True)
    metadata_       = Column("metadata", JSON, default=dict)
    reviewer_note   = Column(Text, nullable=True)
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    reviewed_at     = Column(DateTime, nullable=True)


class ApprovedAutomationModel(Base):
    __tablename__ = "approved_automations"
    id           = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id     = Column(String(64), nullable=False, index=True)
    title        = Column(String(180), nullable=False)
    description  = Column(Text, nullable=True)
    trigger      = Column(String(120), nullable=False)
    instructions = Column(Text, nullable=False)
    schedule     = Column(JSON, default=dict)
    risk_level   = Column(String(32), nullable=False, default="low")
    enabled      = Column(Boolean, default=True)
    approved_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_run_at  = Column(DateTime, nullable=True)
    metadata_    = Column("metadata", JSON, default=dict)


class ActionAuditLogModel(Base):
    __tablename__ = "action_audit_log"
    id            = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id      = Column(String(64), nullable=False, index=True)
    automation_id = Column(String(64), nullable=True, index=True)
    action_type   = Column(String(120), nullable=False)
    status        = Column(String(32), nullable=False)
    request       = Column(JSON, default=dict)
    result        = Column(JSON, default=dict)
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ShortcutModel(Base):
    __tablename__ = "shortcuts"
    id           = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id     = Column(String(64), nullable=False, index=True)
    name         = Column(String(180), nullable=False)
    type         = Column(String(16), nullable=False)  # "app", "url" or "command"
    target       = Column(String(1024), nullable=False)
    aliases      = Column(JSON, default=list)
    description  = Column(Text, nullable=True)
    use_count    = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ScriptSnippetModel(Base):
    __tablename__ = "script_snippets"
    id                = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id          = Column(String(64), nullable=False, index=True)
    name              = Column(String(180), nullable=False)
    shell             = Column(String(32), nullable=False)
    script            = Column(Text, nullable=False)
    working_directory = Column(String(1024), nullable=True)
    timeout_seconds   = Column(Integer, default=30)
    allow_high_risk   = Column(Boolean, default=False)
    description       = Column(Text, nullable=True)
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class ShortcutLaunchLogModel(Base):
    __tablename__ = "shortcut_launch_logs"
    id            = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id      = Column(String(64), nullable=False, index=True)
    shortcut_id   = Column(String(64), nullable=True, index=True)
    shortcut_name = Column(String(180), nullable=False)
    target_type   = Column(String(16), nullable=False)
    target        = Column(String(1024), nullable=False)
    status        = Column(String(32), nullable=False, default="executed", index=True)
    source        = Column(String(80), nullable=False, default="interface")
    platform      = Column(String(80), nullable=True)
    request       = Column(JSON, default=dict)
    result        = Column(JSON, default=dict)
    error         = Column(Text, nullable=True)
    launched_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class DisciplineModel(Base):
    """Disciplina ministrada: ARA0040 / BANCO DE DADOS."""

    __tablename__ = "disciplines"
    id         = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id   = Column(String(64), nullable=False, index=True)
    code       = Column(String(80), nullable=False, default="")
    name       = Column(String(180), nullable=False, default="")
    semester   = Column(String(16), nullable=False, default="")
    active     = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ClassGroupModel(Base):
    """Turma como entidade: o texto solto em students/lessons vira vinculo.

    `code` e o numero da turma no sistema da instituicao (3001) e `name` a
    distincao que o professor usa em sala (Presencial, Semipresencial). A
    coluna `discipline` segue como copia do rotulo da disciplina vinculada.
    """

    __tablename__ = "class_groups"
    id         = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id   = Column(String(64), nullable=False, index=True)
    code       = Column(String(80), nullable=False, default="")
    name       = Column(String(120), nullable=False, default="")
    discipline_id = Column(String(64), nullable=True, index=True)
    discipline    = Column(String(120), nullable=False, default="", index=True)
    semester      = Column(String(16), nullable=False, default="", index=True)
    active     = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ClassScheduleModel(Base):
    """Dia da semana em que a turma tem aula, com horario opcional.

    Uma turma pode ter mais de uma linha: a mesma disciplina cai na segunda e
    na quinta, e cada dia pode ter mais de uma turma.
    """

    __tablename__ = "class_schedules"
    id             = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_group_id = Column(String(64), nullable=False, index=True)
    weekday        = Column(Integer, nullable=False, default=0)  # 0 = segunda
    start_time     = Column(String(5), nullable=False, default="")
    end_time       = Column(String(5), nullable=False, default="")


class ClassCalendarSeriesModel(Base):
    """Serie semanal criada no calendario externo a partir de um horario."""

    __tablename__ = "class_calendar_series"
    __table_args__ = (
        UniqueConstraint(
            "fingerprint",
            name="uq_class_calendar_series_fingerprint",
        ),
    )
    id                = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    fingerprint       = Column(String(64), nullable=False, index=True)
    user_id           = Column(String(64), nullable=False, index=True)
    tutor_id          = Column(String(64), nullable=False, index=True)
    class_group_id    = Column(String(64), nullable=False, index=True)
    class_schedule_id = Column(String(64), nullable=False, index=True)
    provider          = Column(String(32), nullable=False)
    account_id        = Column(String(120), nullable=False)
    provider_event_id = Column(String(512), nullable=False)
    date_from         = Column(String(10), nullable=False)
    date_to           = Column(String(10), nullable=False)
    timezone_name     = Column(String(80), nullable=False, default="America/Sao_Paulo")
    created_at        = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class LessonClassGroupModel(Base):
    """Turmas atendidas por uma aula. Aula reunida tem mais de uma linha."""

    __tablename__ = "lesson_class_groups"
    id             = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    lesson_id      = Column(String(64), nullable=False, index=True)
    class_group_id = Column(String(64), nullable=False, index=True)


class StudentModel(Base):
    __tablename__ = "students"
    id          = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id    = Column(String(64), nullable=False, index=True)
    name        = Column(String(180), nullable=False)
    # Vinculo com a turma. As duas colunas de texto seguem preenchidas a
    # partir dela, para o que ja consulta por nome continuar funcionando.
    class_id    = Column(String(64), nullable=True, index=True)
    class_group = Column(String(120), nullable=False, default="", index=True)
    discipline     = Column(String(120), nullable=False, default="", index=True)
    external_id = Column(String(80), nullable=True)
    aliases     = Column(JSON, default=list)
    notes       = Column(Text, nullable=True)
    active      = Column(Boolean, nullable=False, default=True)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AttendanceSessionModel(Base):
    """Janela temporaria de chamada com um QR para uma ou mais turmas."""

    __tablename__ = "attendance_sessions"
    id              = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id        = Column(String(64), nullable=False, index=True)
    class_group_id  = Column(String(64), nullable=False, index=True)
    class_label     = Column(String(180), nullable=False, default="")
    discipline      = Column(String(180), nullable=False, default="", index=True)
    semester        = Column(String(16), nullable=False, default="", index=True)
    lesson_id       = Column(String(64), nullable=True, index=True)
    attendance_date = Column(String(10), nullable=False, index=True)
    title           = Column(String(255), nullable=False, default="")
    token_hash      = Column(String(64), nullable=False, unique=True, index=True)
    expected_count  = Column(Integer, nullable=False, default=0)
    opened_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    expires_at      = Column(DateTime, nullable=False, index=True)
    closed_at       = Column(DateTime, nullable=True)


class AttendanceSessionClassModel(Base):
    """Turmas reunidas em uma unica sessao de chamada."""

    __tablename__ = "attendance_session_classes"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "class_group_id",
            name="uq_attendance_session_class",
        ),
    )
    id             = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id     = Column(String(64), nullable=False, index=True)
    class_group_id = Column(String(64), nullable=False, index=True)
    class_label    = Column(String(180), nullable=False, default="")
    discipline     = Column(String(180), nullable=False, default="")
    semester       = Column(String(16), nullable=False, default="")
    expected_count = Column(Integer, nullable=False, default=0)


class AttendanceRecordModel(Base):
    """Presenca confirmada, com copia do nome/matricula para manter o historico."""

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "student_id",
            name="uq_attendance_record_session_student",
        ),
    )
    id            = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id    = Column(String(64), nullable=False, index=True)
    student_id    = Column(String(64), nullable=False, index=True)
    enrollment    = Column(String(80), nullable=False)
    student_name  = Column(String(180), nullable=False)
    source        = Column(String(32), nullable=False, default="qr")
    checked_in_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class AttendanceRosterModel(Base):
    """Foto da lista no momento da chamada, inclusive para calcular faltas depois."""

    __tablename__ = "attendance_rosters"
    id           = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id   = Column(String(64), nullable=False, index=True)
    student_id   = Column(String(64), nullable=False, index=True)
    enrollment   = Column(String(80), nullable=False, default="")
    student_name = Column(String(180), nullable=False)
    class_group_id = Column(String(64), nullable=True, index=True)
    class_label    = Column(String(180), nullable=False, default="")
    discipline     = Column(String(180), nullable=False, default="")


class LessonModel(Base):
    __tablename__ = "lessons"
    id             = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id       = Column(String(64), nullable=False, index=True)
    discipline        = Column(String(120), nullable=False, index=True)
    semester       = Column(String(16), nullable=False, default="", index=True)
    title          = Column(String(255), nullable=False, default="")
    class_group    = Column(String(120), nullable=False, default="", index=True)
    teacher        = Column(String(180), nullable=True)
    status         = Column(String(32), nullable=False, default="recording", index=True)
    started_at     = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    ended_at       = Column(DateTime, nullable=True)
    summary        = Column(Text, nullable=True)
    summary_llm    = Column(String(80), nullable=True)
    summary_at     = Column(DateTime, nullable=True)
    segment_count  = Column(Integer, nullable=False, default=0)
    transcript_chars = Column(Integer, nullable=False, default=0)
    metadata_      = Column("metadata", JSON, default=dict)


class LessonSegmentModel(Base):
    __tablename__ = "lesson_segments"
    id              = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    lesson_id       = Column(String(64), nullable=False, index=True)
    tutor_id        = Column(String(64), nullable=False, index=True)
    sequence        = Column(Integer, nullable=False, default=0)
    text            = Column(Text, nullable=False)
    confidence      = Column(Float, nullable=False, default=0.0)
    duration_ms     = Column(Integer, nullable=False, default=0)
    indexed         = Column(Boolean, nullable=False, default=False)
    qdrant_point_id = Column(String(64), nullable=True)
    # `provedor:modelo` que gerou o vetor. Guardado aqui, e nao so no Qdrant,
    # para a reindexacao saber o que esta atrasado sem varrer o indice.
    embedding_model = Column(String(120), nullable=True)
    created_at      = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class LessonPointModel(Base):
    __tablename__ = "lesson_points"
    id           = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    tutor_id     = Column(String(64), nullable=False, index=True)
    lesson_id    = Column(String(64), nullable=False, index=True)
    segment_id   = Column(String(64), nullable=True)
    student_id   = Column(String(64), nullable=True, index=True)
    student_name = Column(String(180), nullable=False)
    points       = Column(Float, nullable=False, default=0.0)
    reason       = Column(Text, nullable=True)
    discipline      = Column(String(120), nullable=False, default="", index=True)
    lesson_date  = Column(DateTime, nullable=False, index=True)
    source       = Column(String(32), nullable=False, default="extracted")
    confidence   = Column(Float, nullable=False, default=0.0)
    quote        = Column(Text, nullable=True)
    created_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))


async def init_db():
    async with engine.begin() as conn:
        # Antes do create_all: senao ele cria as tabelas novas vazias ao lado
        # das antigas e o rename nao acha mais o que renomear.
        await conn.run_sync(_rename_subject_to_discipline)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_compatibility_columns)
        await conn.run_sync(_widen_credential_secret_ref)
    await _backfill_account_ownership()
    await _backfill_class_groups()
    await _backfill_disciplines()
    await _backfill_semesters()


def _rename_subject_to_discipline(sync_conn) -> None:
    """Renomeia o que ja foi gravado como `subject` para `discipline`.

    O modulo chamava disciplina de subject, palavra que tambem significa
    assunto e que colidia com o subject do calendario e do email. Roda uma vez
    por instalacao: se a coluna nova ja existe, nao faz nada.
    """
    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())

    if "subjects" in tables and "disciplines" not in tables:
        sync_conn.execute(text("ALTER TABLE subjects RENAME TO disciplines"))
        tables.discard("subjects")
        tables.add("disciplines")

    renames = {
        "lessons": [("subject", "discipline")],
        "students": [("subject", "discipline")],
        "lesson_points": [("subject", "discipline")],
        "class_groups": [
            ("subject", "discipline"),
            ("subject_id", "discipline_id"),
        ],
    }
    for table_name, columns in renames.items():
        if table_name not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for old_name, new_name in columns:
            if old_name in existing and new_name not in existing:
                sync_conn.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"RENAME COLUMN {old_name} TO {new_name}"
                    )
                )
                logger.info(f"Coluna renomeada: {table_name}.{old_name} -> {new_name}")


def _add_compatibility_columns(sync_conn) -> None:
    """Adds columns that create_all cannot add to an existing deployment."""
    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())

    additions = {
        "users": {
            "email": "VARCHAR(255) NULL",
            "role": "VARCHAR(32) NOT NULL DEFAULT 'user'",
            "tutor_id": "VARCHAR(64) NULL",
            "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
            "auth_version": "INTEGER NOT NULL DEFAULT 0",
        },
        "registration_invites": {
            "role": "VARCHAR(32) NOT NULL DEFAULT 'user'",
            "invited_by": "VARCHAR(64) NULL",
        },
        "conversations": {
            "user_id": "VARCHAR(64) NULL",
        },
        "calendar_events": {
            "user_id": "VARCHAR(64) NULL",
        },
        "students": {
            "class_id": "VARCHAR(64) NULL",
        },
        "class_groups": {
            "discipline_id": "VARCHAR(64) NULL",
            "semester": "VARCHAR(16) NOT NULL DEFAULT ''",
        },
        "disciplines": {
            "semester": "VARCHAR(16) NOT NULL DEFAULT ''",
        },
        "lessons": {
            "semester": "VARCHAR(16) NOT NULL DEFAULT ''",
        },
        "lesson_segments": {
            "embedding_model": "VARCHAR(120) NULL",
        },
        "attendance_rosters": {
            "class_group_id": "VARCHAR(64) NULL",
            "class_label": "VARCHAR(180) NOT NULL DEFAULT ''",
            "discipline": "VARCHAR(180) NOT NULL DEFAULT ''",
        },
    }
    for table_name, columns in additions.items():
        if table_name not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name, definition in columns.items():
            if column_name not in existing:
                try:
                    sync_conn.execute(
                        text(
                            f"ALTER TABLE {table_name} "
                            f"ADD COLUMN {column_name} {definition}"
                        )
                    )
                except SQLAlchemyError:
                    # Mais de um worker pode iniciar ao mesmo tempo. Nesse
                    # intervalo outro worker pode adicionar a coluna depois
                    # da inspecao acima e antes deste ALTER TABLE. Confirme o
                    # estado atual usando um Inspector novo, sem cache, antes
                    # de decidir se o erro realmente deve interromper o boot.
                    current_columns = {
                        column["name"]
                        for column in inspect(sync_conn).get_columns(table_name)
                    }
                    if column_name not in current_columns:
                        raise
                    logger.info(
                        "Coluna de compatibilidade ja adicionada por outro "
                        f"worker: {table_name}.{column_name}"
                    )

    inspector = inspect(sync_conn)
    if "users" in tables:
        indexes = inspector.get_indexes("users")
        has_unique_email = any(
            index.get("unique")
            and index.get("column_names") == ["email"]
            for index in indexes
        )
        if not has_unique_email:
            sync_conn.execute(
                text(
                    "CREATE UNIQUE INDEX uq_users_email "
                    "ON users (email)"
                )
            )


def _widen_credential_secret_ref(sync_conn) -> None:
    """Encrypted provider tokens can exceed the old VARCHAR(255) envelope."""
    if sync_conn.dialect.name not in {"mysql", "mariadb"}:
        return
    inspector = inspect(sync_conn)
    if "credential_refs" not in inspector.get_table_names():
        return
    column = next(
        (
            item
            for item in inspector.get_columns("credential_refs")
            if item["name"] == "secret_ref"
        ),
        None,
    )
    length = getattr(column.get("type"), "length", None) if column else None
    if length is not None:
        try:
            sync_conn.execute(
                text(
                    "ALTER TABLE credential_refs "
                    "MODIFY COLUMN secret_ref TEXT NOT NULL"
                )
            )
        except SQLAlchemyError:
            current = next(
                (
                    item
                    for item in inspect(sync_conn).get_columns("credential_refs")
                    if item["name"] == "secret_ref"
                ),
                None,
            )
            if getattr(current.get("type"), "length", None) is not None:
                raise

def scoped_config_key(user_id: str, key: str) -> str:
    return f"user:{user_id}:{key}"


async def seed_admin_notification_config(
    db: AsyncSession,
    user_id: str,
) -> None:
    """Copies legacy notification env values only to the administrator."""
    key = scoped_config_key(user_id, "notif")
    if await db.get(ConfigModel, key) is not None:
        return
    payload = {
        "telegram_token": settings.telegram_bot_token,
        "telegram_chat_id": settings.telegram_chat_id,
        "telegram_enabled": bool(
            settings.telegram_bot_token and settings.telegram_chat_id
        ),
        "wa_provider": settings.wa_provider,
        "wa_number": settings.wa_number,
        "wa_token": settings.wa_token,
        "wa_sid": settings.wa_sid,
        "wa_enabled": bool(settings.wa_number),
        "notify_15min": True,
        "reminder_minutes": 15,
        "notify_on_time": True,
        "fallback_enabled": True,
        "include_link": True,
    }
    if not payload["telegram_enabled"] and not payload["wa_enabled"]:
        return
    db.add(ConfigModel(key=key, value=json.dumps(payload, ensure_ascii=False)))


def derive_class_groups(students, lessons):
    """Deriva turmas dos textos gravados e devolve (turmas, vinculos de aula).

    Efeito colateral proposital: escreve `class_id` em cada aluno. Aula sem
    turma no texto era o jeito antigo de dizer turmas reunidas, entao ela sai
    ligada a todas as turmas da disciplina.
    """
    groups: dict[tuple, ClassGroupModel] = {}

    def ensure(tutor_id: str, discipline: str, code: str) -> ClassGroupModel:
        key = (tutor_id, discipline, code)
        group = groups.get(key)
        if group is None:
            groups[key] = group = ClassGroupModel(
                id=str(uuid.uuid4()),
                tutor_id=tutor_id,
                code=code,
                name="",
                discipline=discipline,
            )
        return group

    for student in students:
        code = (student.class_group or "").strip()
        discipline = (student.discipline or "").strip()
        if not code and not discipline:
            continue
        student.class_id = ensure(student.tutor_id, discipline, code).id

    links = []
    for lesson in lessons:
        code = (lesson.class_group or "").strip()
        discipline = (lesson.discipline or "").strip()
        for (tutor_id, group_discipline, group_code), group in groups.items():
            if tutor_id != lesson.tutor_id:
                continue
            if discipline and group_discipline and group_discipline != discipline:
                continue
            if code and group_code != code:
                continue
            links.append(
                LessonClassGroupModel(
                    id=str(uuid.uuid4()),
                    lesson_id=lesson.id,
                    class_group_id=group.id,
                )
            )

    return list(groups.values()), links


def derive_disciplines(groups):
    """Cria uma disciplina por texto distinto de `class_groups.discipline`.

    Efeito colateral proposital: aponta cada turma para a disciplina dela.
    """
    disciplines: dict[tuple, DisciplineModel] = {}
    for group in groups:
        code = (group.discipline or "").strip()
        if not code:
            continue
        key = (group.tutor_id, code)
        discipline = disciplines.get(key)
        if discipline is None:
            disciplines[key] = discipline = DisciplineModel(
                id=str(uuid.uuid4()),
                tutor_id=group.tutor_id,
                code=code,
                name="",
            )
        group.discipline_id = discipline.id
    return list(disciplines.values())


def current_semester_code(at: datetime | None = None) -> str:
    """Codigo academico convencional: primeiro ou segundo semestre do ano."""
    moment = at or datetime.now(timezone.utc)
    half = 1 if moment.month <= 6 else 2
    return f"{moment.year}.{half}"


async def _backfill_semesters() -> None:
    """Associa o cadastro anterior ao semestre vigente no primeiro upgrade.

    Turmas herdam a disciplina vinculada e aulas mantem uma copia, como ja
    acontece com o nome da disciplina. Depois de preenchido, o periodo nunca
    muda automaticamente na virada do calendario.
    """
    async with AsyncSessionLocal() as db:
        current = current_semester_code()
        disciplines = list(
            (await db.execute(select(DisciplineModel))).scalars().all()
        )
        by_id = {item.id: item for item in disciplines}
        by_label = {
            (item.tutor_id, " - ".join(
                part for part in ((item.code or "").strip(), (item.name or "").strip())
                if part
            )): item
            for item in disciplines
        }
        changed = 0
        for discipline in disciplines:
            if not (discipline.semester or "").strip():
                discipline.semester = current
                changed += 1

        groups = list((await db.execute(select(ClassGroupModel))).scalars().all())
        for group in groups:
            if (group.semester or "").strip():
                continue
            linked = by_id.get(group.discipline_id)
            group.semester = linked.semester if linked else current
            changed += 1

        lessons = list((await db.execute(select(LessonModel))).scalars().all())
        for lesson in lessons:
            if (lesson.semester or "").strip():
                continue
            linked = by_label.get((lesson.tutor_id, (lesson.discipline or "").strip()))
            lesson.semester = linked.semester if linked else current
            changed += 1

        if changed:
            await db.commit()
            logger.info(
                f"Semestre {current} associado a {changed} registro(s) legado(s)."
            )


async def _backfill_disciplines() -> None:
    """Transforma o texto de disciplina da turma em cadastro proprio."""
    async with AsyncSessionLocal() as db:
        if (await db.execute(select(DisciplineModel.id).limit(1))).first():
            return

        groups = list((await db.execute(select(ClassGroupModel))).scalars().all())
        if not groups:
            return

        disciplines = derive_disciplines(groups)
        for discipline in disciplines:
            db.add(discipline)
        await db.commit()
        logger.info(f"Disciplinas derivadas das turmas: {len(disciplines)}.")


async def _backfill_class_groups() -> None:
    """Transforma a turma escrita em texto no aluno e na aula em vinculo.

    Roda uma unica vez: com a tabela de turmas ja populada, sai na hora.
    """
    async with AsyncSessionLocal() as db:
        if (await db.execute(select(ClassGroupModel.id).limit(1))).first():
            return

        students = list((await db.execute(select(StudentModel))).scalars().all())
        lessons = list((await db.execute(select(LessonModel))).scalars().all())
        if not students and not lessons:
            return

        groups, links = derive_class_groups(students, lessons)
        for item in groups + links:
            db.add(item)
        await db.commit()
        logger.info(
            f"Turmas derivadas do cadastro antigo: {len(groups)} turma(s), "
            f"{len(students)} aluno(s), {len(lessons)} aula(s)."
        )


async def _backfill_account_ownership() -> None:
    """Preserves the current single-user data when multi-user support is enabled."""
    async with AsyncSessionLocal() as db:
        users = list(
            (
                await db.execute(
                    select(UserModel).order_by(UserModel.created_at, UserModel.id)
                )
            )
            .scalars()
            .all()
        )
        if not users:
            return

        admin = users[0]
        admin.role = "admin"
        if not admin.email and settings.registration_admin_email:
            admin.email = settings.registration_admin_email.strip() or None

        tutors = list(
            (
                await db.execute(
                    select(TutorModel).order_by(TutorModel.created_at, TutorModel.id)
                )
            )
            .scalars()
            .all()
        )
        assigned_tutors = {user.tutor_id for user in users if user.tutor_id}
        reusable_tutors = [
            tutor for tutor in tutors if tutor.id not in assigned_tutors
        ]

        for index, user in enumerate(users):
            if not user.role:
                user.role = "admin" if index == 0 else "user"
            if user.is_active is None:
                user.is_active = True
            if user.tutor_id:
                continue
            if reusable_tutors:
                tutor = reusable_tutors.pop(0)
            else:
                tutor = TutorModel(
                    display_name=user.username,
                    email=user.email,
                )
                db.add(tutor)
                await db.flush()
                db.add(AssistantProfileModel(tutor_id=tutor.id))
            user.tutor_id = tutor.id

        await db.flush()

        await db.execute(
            text(
                "UPDATE conversations SET user_id = :user_id "
                "WHERE user_id IS NULL"
            ),
            {"user_id": admin.id},
        )
        await db.execute(
            text(
                "UPDATE calendar_events SET user_id = :user_id "
                "WHERE user_id IS NULL"
            ),
            {"user_id": admin.id},
        )

        legacy_keys = (
            "notif",
            "calendar_google",
            "calendar_microsoft",
            "calendar_google_app",
            "calendar_microsoft_app",
            "calendar_google_accounts",
            "calendar_microsoft_accounts",
        )
        for key in legacy_keys:
            scoped_key = scoped_config_key(admin.id, key)
            if await db.get(ConfigModel, scoped_key) is not None:
                continue
            legacy = await db.get(ConfigModel, key)
            if legacy is not None:
                db.add(ConfigModel(key=scoped_key, value=legacy.value))
        await db.flush()
        await seed_admin_notification_config(db, admin.id)
        await db.commit()


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

