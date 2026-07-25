import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
import uuid
from sqlalchemy import Column, String, DateTime, Boolean, Text, Integer, JSON, Float
from datetime import datetime, timezone
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
    session   = Column(String(120), nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    metadata_ = Column("metadata", JSON, default=dict)


class CalendarEventModel(Base):
    __tablename__ = "calendar_events"
    id           = Column(String(255), primary_key=True)
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
    password_hash = Column(String(255), nullable=False)
    created_at    = Column(DateTime, default=lambda: datetime.now(timezone.utc))


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
    assistant_name = Column(String(180), nullable=False, default="Assistente")
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
    secret_ref = Column(String(255), nullable=False)
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


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

