"""Geração de QR Code para compartilhamento de quizzes."""

import io
from typing import Optional

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import QuizModel, get_db
from ..core.security import get_current_user

router = APIRouter(prefix="/education/quiz", tags=["quiz-qrcode"])


def _public_base_url(request: Request, base_url: Optional[str] = None) -> str:
    """Base publica usada nos links do quiz.

    O cliente pode sobrescrever por query string em deploys com proxy; sem isso,
    usamos a propria URL da requisicao.
    """
    raw = (base_url or str(request.base_url)).strip()
    return raw.rstrip("/")


def _generate_qrcode(data: str, size: int = 10) -> bytes:
    """Gera QR Code a partir de uma string."""

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=size,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # Converte para bytes
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    return img_bytes.getvalue()


def _generate_qrcode_svg(data: str) -> bytes:
    """Gera QR Code SVG a partir de uma string."""

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
        image_factory=qrcode.image.svg.SvgImage,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img_bytes = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(img_bytes)
    img_bytes.seek(0)
    return img_bytes.getvalue()


@router.get("/{quiz_id}/qrcode")
async def quiz_qrcode(
    request: Request,
    quiz_id: str,
    user: dict = Depends(get_current_user),
    base_url: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Gera QR Code do quiz para compartilhar com alunos.

    QR Code aponta para: {base_url}/education/quiz/{quiz_id}/play
    """

    # Valida que o quiz existe e pertence ao professor
    stmt = select(QuizModel).where(QuizModel.id == quiz_id)
    quiz = (await db.execute(stmt)).scalar_one_or_none()

    if not quiz or quiz.tutor_id != user["tutor_id"]:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    # Gera URL do quiz
    base_url = _public_base_url(request, base_url)
    quiz_url = f"{base_url}/education/quiz/{quiz_id}/play"

    # Gera QR Code
    qr_bytes = _generate_qrcode(quiz_url)

    return StreamingResponse(
        io.BytesIO(qr_bytes),
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="quiz-{quiz_id}.png"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/{quiz_id}/qrcode/svg")
async def quiz_qrcode_svg(
    request: Request,
    quiz_id: str,
    user: dict = Depends(get_current_user),
    base_url: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Gera QR Code em SVG (escalável)."""

    # Valida que o quiz existe e pertence ao professor
    stmt = select(QuizModel).where(QuizModel.id == quiz_id)
    quiz = (await db.execute(stmt)).scalar_one_or_none()

    if not quiz or quiz.tutor_id != user["tutor_id"]:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    # Gera URL do quiz
    base_url = _public_base_url(request, base_url)
    quiz_url = f"{base_url}/education/quiz/{quiz_id}/play"

    svg_content = _generate_qrcode_svg(quiz_url)

    return StreamingResponse(
        io.BytesIO(svg_content),
        media_type="image/svg+xml",
        headers={
            "Content-Disposition": f'inline; filename="quiz-{quiz_id}.svg"',
        },
    )


@router.get("/{quiz_id}/share-info")
async def quiz_share_info(
    request: Request,
    quiz_id: str,
    user: dict = Depends(get_current_user),
    base_url: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Retorna informações para compartilhamento do quiz."""

    # Valida que o quiz existe e pertence ao professor
    stmt = select(QuizModel).where(QuizModel.id == quiz_id)
    quiz = (await db.execute(stmt)).scalar_one_or_none()

    if not quiz or quiz.tutor_id != user["tutor_id"]:
        raise HTTPException(status_code=404, detail="Quiz não encontrado")

    base_url = _public_base_url(request, base_url)
    quiz_url = f"{base_url}/education/quiz/{quiz_id}/play"

    return {
        "quiz_id": quiz_id,
        "title": quiz.titulo,
        "url": quiz_url,
        "qrcode_url": f"{base_url}/education/quiz/{quiz_id}/qrcode",
        "qrcode_svg_url": f"{base_url}/education/quiz/{quiz_id}/qrcode/svg",
        "share_text": f"Responda meu quiz: {quiz.titulo}\n\n{quiz_url}",
        "created_at": quiz.created_at.isoformat() if quiz.created_at else None,
    }
