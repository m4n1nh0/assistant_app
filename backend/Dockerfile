FROM python:3.14-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv

RUN python -m venv "${VIRTUAL_ENV}"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

WORKDIR /build

COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install --only-binary=:all: -r requirements.txt


FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

# Runtime dependencies for audio processing and the container health check.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

# Modelo de transcricao (Whisper) dentro da imagem. O disco do Railway e descartado a
# cada deploy: sem isso, a primeira gravacao depois de cada atualizacao baixava
# centenas de MB do Hugging Face e falhava (ou travava) ate o download terminar.
# O modelo e o do servico (`WHISPER_MODEL`, o Railway entrega as variaveis ao build);
# se a baixada falhar, a imagem sai assim mesmo e o servidor baixa na subida.
ARG WHISPER_MODEL=small
ENV HF_HOME=/opt/hf-cache
RUN mkdir -p "${HF_HOME}" \
    && (python -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['WHISPER_MODEL'], device='cpu', compute_type='int8')" \
        || echo "AVISO: modelo Whisper nao foi embutido na imagem; sera baixado no servidor") \
    && chown -R app:app "${HF_HOME}"

WORKDIR /app

COPY --chown=app:app . .
RUN mkdir -p logs data && chown -R app:app /app

USER app

EXPOSE 8000

CMD ["python", "run.py"]
