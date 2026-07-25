from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from loguru import logger
import logging
import sys

from .core.config import get_settings
from .core.database import init_db
from .core.database_seed import apply_database_seed, database_seed_requested
from .utils.scheduler import start_scheduler, stop_scheduler
from .routers.chat import router as chat_router
from .routers.websocket import router as ws_router
from .routers.automations import router as automations_router
from .routers.memory import router as memory_router
from .routers.routes import (
    router_auth, router_calendar, router_calendar_public,
    router_notif, router_voice, router_health,
)
from .routers.system import router as system_router
from .routers.tutor import router as tutor_router
from .routers.launcher import router as launcher_router
from .routers.desktop import router as desktop_router
from .routers.computer import router as computer_router
from .services.qdrant_service import ensure_collections

settings = get_settings()


class _HealthAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        return ' /health' not in message and ' /health/' not in message

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

logger.remove()
logger.add(
    sys.stdout,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level=settings.log_level.upper(),
    colorize=True,
)
logger.add("logs/assistant.log", rotation="10 MB", retention="7 days", level="DEBUG")
logging.getLogger("uvicorn.access").addFilter(_HealthAccessLogFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Backend starting...")
    seed_requested = database_seed_requested(settings.database_seed)
    try:
        await init_db()
        logger.info("Database initialized")
        if seed_requested:
            seed_applied = await apply_database_seed(settings.database_seed)
            if seed_applied:
                logger.info(f"Database seed applied: {settings.database_seed}")
            else:
                logger.info(f"Database seed already applied: {settings.database_seed}")
    except Exception as e:
        if seed_requested:
            logger.exception(f"Database seed failed: {e}")
            raise
        logger.warning(f"Database unavailable (funcoes de historico desativadas): {e}")
    try:
        ensure_collections()
        logger.info("Qdrant collections ready")
    except Exception as e:
        logger.warning(f"Qdrant unavailable: {e}")
    start_scheduler()
    logger.info("Scheduler started")
    logger.info(f"Active services: {settings.active_llms}")
    logger.info(f"Listening on {settings.host}:{settings.port}")
    yield
    stop_scheduler()
    logger.info("Backend stopped")


app = FastAPI(
    title="Assistente - Backend",
    description="API REST + WebSocket - Assistente Desktop",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(router_health)
app.include_router(chat_router)
app.include_router(ws_router)
app.include_router(tutor_router)
app.include_router(launcher_router)
app.include_router(memory_router)
app.include_router(automations_router)
app.include_router(system_router)
app.include_router(desktop_router)
app.include_router(computer_router)
app.include_router(router_auth)
app.include_router(router_calendar_public)
app.include_router(router_calendar)
app.include_router(router_notif)
app.include_router(router_voice)
