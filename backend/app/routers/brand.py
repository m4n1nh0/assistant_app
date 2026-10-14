"""Logo da marca para os e-mails.

Publico e sem login de proposito: quem le o e-mail busca a imagem direto do servidor, e
nao ha nada sensivel nela. O arquivo vive em `static/brand/`.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["Brand"])

_BRAND_DIR = Path(__file__).parent.parent.parent / "static" / "brand"


@router.get("/brand/intarq-icon.png", include_in_schema=False)
async def intarq_icon():
    return FileResponse(
        _BRAND_DIR / "intarq-icon.png",
        media_type="image/png",
        # Logo nao muda: o cliente de e-mail e o proxy podem guardar por uma semana.
        headers={"Cache-Control": "public, max-age=604800"},
    )
