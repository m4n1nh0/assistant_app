"""OCR do material didatico: aproveitar o que chega como imagem.

Apostila digitalizada e foto do quadro sao material legitimo, mas chegam sem
camada de texto: o `pypdf` extrai vazio e o upload era recusado. Aqui essas
paginas viram texto.

Roda local, sobre o mesmo onnxruntime que o `faster-whisper` ja instala, pelo
mesmo motivo da transcricao: material de aula nao precisa sair da maquina, e
assim nao ha chave de API nem limite diario de servico de terceiro.

Todo o modulo e opcional. Sem o pacote instalado, `is_available()` responde
falso e quem chama volta a recusar o arquivo com a mensagem de sempre - o boot
do servidor nao depende disso.
"""

from __future__ import annotations

import importlib.util
import io
import threading
from statistics import median

from loguru import logger

from .user_llm_config_service import runtime_settings

settings = runtime_settings

#: Extensoes que o Pillow abre sem plugin extra. HEIC, o formato padrao do
#: iPhone, ficou de fora de proposito: precisaria de pillow-heif, e o proprio
#: celular converte para JPEG ao compartilhar.
IMAGE_EXTENSIONS: tuple[str, ...] = (
    ".bmp",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
)

_engine = None
_load_failed = False
#: Serializa carga e inferencia. O ONNX Runtime nao promete sessao concorrente,
#: e dois uploads simultaneos chegam em threads diferentes (`asyncio.to_thread`).
#: Enfileirar tambem evita que duas apostilas grandes disputem toda a CPU.
_lock = threading.Lock()


def is_available() -> bool:
    """Se vale a pena tentar OCR: ligado, instalado e sem falha anterior."""
    if not getattr(settings, "ocr_enabled", True):
        return False
    if _load_failed:
        return False
    return importlib.util.find_spec("rapidocr") is not None


def _get_engine():
    """Carrega o modelo uma vez. Custa alguns segundos e uns 20 MB em disco."""
    global _engine, _load_failed
    if _engine is not None or _load_failed:
        return _engine

    with _lock:
        if _engine is None and not _load_failed:
            try:
                from rapidocr import RapidOCR

                logger.info("Carregando modelo de OCR (RapidOCR/onnxruntime)")
                _engine = RapidOCR()
                logger.info("OCR pronto")
            except Exception as exc:
                # Marca a falha para nao repetir a tentativa a cada upload.
                _load_failed = True
                logger.warning(f"OCR indisponivel: {exc}")
    return _engine


def _ordered_lines(result) -> list[str]:
    """Poe as linhas reconhecidas na ordem de leitura.

    O detector devolve as caixas na ordem em que as achou, que nao e a ordem em
    que a pagina se le. Sem reordenar, o rodape pode entrar no meio de um
    conceito e o gerador de quiz recebe um texto embaralhado.

    O agrupamento por faixa horizontal - e nao por coordenada exata - existe
    porque letras da mesma linha raramente ficam no mesmo pixel: a tolerancia
    sai da propria altura das caixas, entao vale para qualquer resolucao.
    """
    boxes = getattr(result, "boxes", None)
    txts = getattr(result, "txts", None) or ()
    scores = getattr(result, "scores", None) or ()
    if boxes is None or len(txts) == 0:
        return []

    minimo = float(getattr(settings, "ocr_min_score", 0.5))
    caixas = []
    for box, texto, score in zip(boxes, txts, scores):
        limpo = (texto or "").strip()
        if not limpo or float(score) < minimo:
            continue
        ys = [float(ponto[1]) for ponto in box]
        xs = [float(ponto[0]) for ponto in box]
        caixas.append(
            {
                "topo": min(ys),
                "esquerda": min(xs),
                "altura": max(ys) - min(ys),
                "texto": limpo,
            }
        )

    if not caixas:
        return []

    alturas = [c["altura"] for c in caixas if c["altura"] > 0]
    tolerancia = (median(alturas) * 0.6) if alturas else 0
    if tolerancia > 0:
        caixas.sort(key=lambda c: (round(c["topo"] / tolerancia), c["esquerda"]))
    else:
        caixas.sort(key=lambda c: (c["topo"], c["esquerda"]))

    return [c["texto"] for c in caixas]


def _read(image) -> list[str]:
    """Passa uma imagem PIL pelo modelo e devolve as linhas em ordem."""
    engine = _get_engine()
    if engine is None:
        return []

    import numpy as np

    array = np.array(image.convert("RGB"))
    try:
        with _lock:
            resultado = engine(array)
    except Exception as exc:
        logger.warning(f"OCR falhou na imagem: {exc}")
        return []

    return _ordered_lines(resultado)


def text_from_image(data: bytes) -> str:
    """Texto de uma imagem solta - foto do quadro, pagina fotografada."""
    from PIL import Image

    try:
        imagem = Image.open(io.BytesIO(data))
    except Exception as exc:
        logger.warning(f"Imagem ilegivel para OCR: {exc}")
        return ""

    with imagem:
        return "\n".join(_read(imagem))


def text_from_pdf(data: bytes) -> tuple[list[str], bool]:
    """Rasteriza o PDF e le pagina a pagina.

    Usa o pypdfium2, e nao o PyMuPDF que costuma aparecer nessa tarefa, por
    causa da licenca: o PyMuPDF e AGPL e contaminaria o aplicativo inteiro.

    Returns:
        As linhas de cada pagina e se o teto de paginas cortou o material.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logger.warning("pypdfium2 nao instalado - OCR de PDF indisponivel")
        return [], False

    if _get_engine() is None:
        return [], False

    teto = max(1, int(getattr(settings, "ocr_max_pages", 30)))
    escala = float(getattr(settings, "ocr_dpi", 200)) / 72.0

    try:
        documento = pdfium.PdfDocument(data)
    except Exception as exc:
        logger.warning(f"Nao consegui rasterizar o PDF para OCR: {exc}")
        return [], False

    total = len(documento)
    cortado = total > teto
    if cortado:
        logger.info(f"OCR limitado a {teto} das {total} paginas do material")

    blocos: list[str] = []
    try:
        for numero in range(min(total, teto)):
            try:
                pagina = documento[numero]
                bitmap = pagina.render(scale=escala)
                with bitmap.to_pil() as imagem:
                    blocos.append("\n".join(_read(imagem)))
            except Exception as exc:
                # Uma pagina defeituosa nao pode perder o material inteiro,
                # mesmo tratamento que a leitura normal de PDF ja da.
                logger.warning(f"OCR falhou na pagina {numero + 1}: {exc}")
    finally:
        documento.close()

    return blocos, cortado
