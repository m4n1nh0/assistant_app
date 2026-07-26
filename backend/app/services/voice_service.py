import io
import math
import os
import tempfile
from loguru import logger
from ..core.config import get_settings
from ..models.schemas import STTResponse

settings = get_settings()

_whisper_model = None


def _register_cuda_libraries() -> None:
    """Puts the pip-installed CUDA DLLs on PATH so CTranslate2 can find them.

    On Windows the model loads fine without this, but the first transcribe()
    dies with "cublas64_12.dll is not found" — CTranslate2 resolves those
    libraries through PATH, and the nvidia-* wheels install them inside
    site-packages instead.
    """
    if os.name != "nt":
        return

    import glob
    import site

    roots = list(site.getsitepackages())
    user_site = site.getusersitepackages()
    if isinstance(user_site, str):
        roots.append(user_site)

    found = set()
    for root in roots:
        pattern = os.path.join(root, "nvidia", "*", "bin", "*.dll")
        found.update(os.path.dirname(dll) for dll in glob.glob(pattern))

    missing = [d for d in sorted(found) if d not in os.environ.get("PATH", "")]
    if missing:
        os.environ["PATH"] = os.pathsep.join(missing + [os.environ.get("PATH", "")])


def _load_whisper():
    global _whisper_model
    if _whisper_model is None:
        try:
            if settings.whisper_device.strip().lower().startswith("cuda"):
                _register_cuda_libraries()
            from faster_whisper import WhisperModel
            logger.info(
                f"Loading Whisper model: {settings.whisper_model} "
                f"({settings.whisper_device}/{settings.whisper_compute_type})"
            )
            _whisper_model = WhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
            )
            logger.info("Whisper loaded")
        except ImportError:
            logger.warning("faster-whisper not installed - STT unavailable")
    return _whisper_model


async def transcribe_audio(audio_bytes: bytes, language: str = "pt") -> STTResponse:
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_transcribe, audio_bytes, language)


def _sync_transcribe(audio_bytes: bytes, language: str) -> STTResponse:
    if not audio_bytes:
        return STTResponse(transcript="", confidence=0.0)

    provider = settings.stt_provider.strip().lower()
    should_try_openai = provider in {"auto", "openai"} and bool(settings.openai_api_key)
    if should_try_openai:
        try:
            return _sync_openai_transcribe(audio_bytes, language)
        except Exception as e:
            logger.warning(f"OpenAI STT unavailable, falling back to local Whisper: {e}")

    model = _load_whisper()
    if model is None:
        return STTResponse(transcript="", confidence=0.0)

    suffix = _detect_audio_suffix(audio_bytes)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        whisper_language = _whisper_language(language)
        vad_parameters = {
            "min_silence_duration_ms": settings.whisper_vad_min_silence_ms,
        }
        segments_iter, info = model.transcribe(
            tmp_path,
            language=whisper_language,
            beam_size=max(1, settings.whisper_beam_size),
            best_of=max(1, settings.whisper_best_of),
            vad_filter=settings.whisper_vad_filter,
            vad_parameters=vad_parameters if settings.whisper_vad_filter else None,
            condition_on_previous_text=False,
            # Mesma dica de contexto usada no caminho da OpenAI: ancora nomes de
            # apps e palavras de ativacao que o modelo costuma transcrever errado.
            initial_prompt=_stt_prompt(whisper_language or "pt"),
            temperature=0.0,
            no_speech_threshold=0.55,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
        )
        segments = list(segments_iter)
        transcript = " ".join(seg.text.strip() for seg in segments).strip()
        return STTResponse(
            transcript=transcript,
            confidence=_transcription_confidence(segments, transcript),
            language=info.language or whisper_language or "",
        )
    except Exception as e:
        logger.error(f"Whisper transcription error: {e}")
        return STTResponse(transcript="", confidence=0.0)
    finally:
        os.unlink(tmp_path)


async def text_to_speech(
    text: str,
    language: str = "pt-BR",
    speed: float | None = None,
) -> bytes:
    import asyncio
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_tts, text, language, speed)


def _sync_tts(text: str, language: str, speed: float | None = None) -> bytes:
    speech_text = _prepare_tts_text(text)
    if not speech_text:
        return b""

    provider = settings.tts_provider.strip().lower()
    should_try_openai = provider in {"auto", "openai"} and bool(settings.openai_api_key)
    if should_try_openai:
        try:
            return _sync_openai_tts(speech_text, language, speed)
        except Exception as e:
            logger.warning(f"OpenAI TTS unavailable, falling back to gTTS: {e}")

    try:
        from gtts import gTTS
        buf = io.BytesIO()
        lang_code = _gtts_language(language)
        tts = gTTS(text=speech_text[:600], lang=lang_code, tld="com.br", slow=False)
        tts.write_to_fp(buf)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return b""


def _sync_openai_tts(text: str, language: str, speed: float | None) -> bytes:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.audio.speech.create(
        model=settings.openai_tts_model,
        voice=settings.openai_tts_voice,
        input=text[:1200],
        instructions=_openai_tts_instructions(language),
        response_format="mp3",
        speed=_tts_speed(speed),
    )
    return response.read()


def _sync_openai_transcribe(audio_bytes: bytes, language: str) -> STTResponse:
    from openai import OpenAI

    suffix = _detect_audio_suffix(audio_bytes)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        whisper_language = _whisper_language(language)
        kwargs = {
            "file": open(tmp_path, "rb"),
            "model": settings.openai_stt_model,
            "response_format": "json",
            "temperature": 0,
        }
        if whisper_language:
            kwargs["language"] = whisper_language
            kwargs["prompt"] = _stt_prompt(whisper_language)

        with kwargs["file"] as audio_file:
            kwargs["file"] = audio_file
            result = client.audio.transcriptions.create(**kwargs)

        transcript = result if isinstance(result, str) else getattr(result, "text", "")
        transcript = (transcript or "").strip()
        return STTResponse(
            transcript=transcript,
            confidence=1.0 if transcript else 0.0,
            language=whisper_language or "",
        )
    finally:
        os.unlink(tmp_path)


def _detect_audio_suffix(audio_bytes: bytes) -> str:
    header = audio_bytes[:16]
    if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
        return ".wav"
    if header.startswith(b"ID3") or header[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
        return ".mp3"
    if header.startswith(b"OggS"):
        return ".ogg"
    if header.startswith(b"fLaC"):
        return ".flac"
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        return ".webm"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return ".m4a"
    return ".wav"


def _whisper_language(language: str) -> str | None:
    lang = (language or "").replace("_", "-").split("-")[0].strip().lower()
    return lang or None


def _transcription_confidence(segments: list, transcript: str) -> float:
    if not transcript:
        return 0.0

    log_probs = [
        math.exp(float(seg.avg_logprob))
        for seg in segments
        if getattr(seg, "avg_logprob", None) is not None
    ]
    if log_probs:
        return round(max(0.0, min(1.0, sum(log_probs) / len(log_probs))), 3)

    speech_probs = [
        1.0 - float(seg.no_speech_prob)
        for seg in segments
        if getattr(seg, "no_speech_prob", None) is not None
    ]
    if speech_probs:
        return round(max(0.0, min(1.0, sum(speech_probs) / len(speech_probs))), 3)

    return 1.0


def _prepare_tts_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def _gtts_language(language: str) -> str:
    return _whisper_language(language) or "pt"


def _tts_speed(speed: float | None) -> float:
    value = speed if speed is not None else settings.openai_tts_speed
    try:
        return max(0.25, min(4.0, float(value)))
    except (TypeError, ValueError):
        return 0.95


def _openai_tts_instructions(language: str) -> str:
    if _whisper_language(language) == "pt":
        return (
            "Fale em portugues brasileiro com voz feminina adulta, natural e acolhedora. "
            "Use ritmo conversacional, articulacao clara e pouca entonacao robotica."
        )
    return (
        "Speak with an adult feminine voice that sounds natural, warm, clear, "
        "and conversational rather than robotic."
    )


def _stt_prompt(language: str) -> str:
    """Ancora o vocabulario que o usuario realmente fala com a assistente.

    Sem essa lista, os termos tecnicos em ingles sao os que mais erram no meio
    de uma frase em portugues: "vscode" vira "fscode"/"Viscode" e "backend"
    vira "backing". Citar as palavras exatas aqui corrige a maioria desses
    casos, e pesa mais do que aumentar o modelo.
    """
    if language == "pt":
        return (
            "Transcreva em portugues brasileiro comandos falados para um "
            "assistente de desenvolvimento. Vocabulario recorrente: VS Code, "
            "vscode, PyCharm, backend, frontend, deploy, commit, branch, "
            "Railway, Docker, Redis, endpoint, log, script, workspace, "
            "assistant app. Palavras de ativacao: Dani, Dany. "
            "Use pontuacao simples e nao traduza nomes de programas."
        )
    return (
        "Transcribe spoken commands for a development assistant. Recurring "
        "vocabulary: VS Code, PyCharm, backend, frontend, deploy, commit, "
        "branch, Railway, Docker, Redis, endpoint, log, script, workspace. "
        "Wake words: Dani, Dany. Keep program names untranslated."
    )
