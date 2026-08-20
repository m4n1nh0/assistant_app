"""Rotas web para interface de quiz (HTML/JavaScript)."""

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter(
    tags=["Quiz Web"],
)

# Caminho para arquivos estáticos
STATIC_DIR = Path(__file__).parent.parent.parent / "static"


@router.get("/quiz/dashboard")
async def quiz_dashboard():
    """Página do dashboard de quizzes."""
    return FileResponse(STATIC_DIR / "quiz_dashboard.html", media_type="text/html")


@router.get("/quiz/player")
async def quiz_player():
    """Página do player de quiz (Kahoot-like)."""
    return FileResponse(STATIC_DIR / "quiz_player.html", media_type="text/html")
