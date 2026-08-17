import math
from types import SimpleNamespace

from app.services import voice_service


def test_detect_audio_suffix_handles_common_recording_formats():
    assert voice_service._detect_audio_suffix(b"RIFFxxxxWAVEdata") == ".wav"
    assert voice_service._detect_audio_suffix(b"\x00\x00\x00\x18ftypM4A ") == ".m4a"
    assert voice_service._detect_audio_suffix(b"ID3\x04\x00\x00") == ".mp3"
    assert voice_service._detect_audio_suffix(b"OggS\x00\x02") == ".ogg"


def test_sync_transcribe_uses_vad_and_beam_search(monkeypatch):
    seen = {}

    class FakeModel:
        def transcribe(self, path, **kwargs):
            seen["path"] = path
            seen["kwargs"] = kwargs
            segments = [
                SimpleNamespace(
                    text=" ola ",
                    avg_logprob=math.log(0.9),
                    no_speech_prob=0.05,
                ),
                SimpleNamespace(
                    text=" mundo",
                    avg_logprob=math.log(0.8),
                    no_speech_prob=0.1,
                ),
            ]
            return segments, SimpleNamespace(language="pt")

    monkeypatch.setattr(voice_service, "_load_whisper", lambda: FakeModel())
    monkeypatch.setattr(voice_service.settings, "stt_provider", "local")
    monkeypatch.setattr(voice_service.settings, "whisper_beam_size", 5)
    monkeypatch.setattr(voice_service.settings, "whisper_best_of", 4)
    monkeypatch.setattr(voice_service.settings, "whisper_vad_filter", True)
    monkeypatch.setattr(voice_service.settings, "whisper_vad_min_silence_ms", 450)

    audio = b"\x00\x00\x00\x18ftypM4A " + (b"\x00" * 32)
    result = voice_service._sync_transcribe(audio, "pt-BR")

    assert result.transcript == "ola mundo"
    assert result.confidence == 0.85
    assert result.language == "pt"
    assert seen["path"].endswith(".m4a")
    assert seen["kwargs"]["language"] == "pt"
    assert seen["kwargs"]["beam_size"] == 5
    assert seen["kwargs"]["best_of"] == 4
    assert seen["kwargs"]["vad_filter"] is True
    assert seen["kwargs"]["vad_parameters"] == {"min_silence_duration_ms": 450}
    assert seen["kwargs"]["condition_on_previous_text"] is False
    # O prompt de vocabulario tambem vale para o Whisper local, nao so para a
    # OpenAI: sem ele, termos como "vscode" saem transcritos errado.
    assert "vscode" in seen["kwargs"]["initial_prompt"].lower()


def test_stt_prompt_anchors_technical_vocabulary():
    pt = voice_service._stt_prompt("pt", assistant_name="Hannah")
    for termo in ("VS Code", "backend", "Railway", "Docker", "Hannah"):
        assert termo in pt
    assert "Dani" not in pt

    en = voice_service._stt_prompt("en")
    assert "VS Code" in en


def test_stt_prompt_uses_lesson_context_for_classroom_audio():
    prompt = voice_service._stt_prompt(
        "pt",
        "ARA0040 - Banco de Dados; normalizacao e PostgreSQL",
    )

    assert "Banco de Dados" in prompt
    assert "PostgreSQL" in prompt
    assert "aula" in prompt


def test_cuda_libraries_are_registered_only_for_cuda_device(monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        voice_service, "_register_cuda_libraries", lambda: chamadas.append(True)
    )
    monkeypatch.setattr(voice_service, "_whisper_model", None)

    class FakeWhisper:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setitem(
        __import__("sys").modules,
        "faster_whisper",
        SimpleNamespace(WhisperModel=FakeWhisper),
    )

    monkeypatch.setattr(voice_service.settings, "whisper_device", "cpu")
    voice_service._load_whisper()
    assert chamadas == []

    monkeypatch.setattr(voice_service, "_whisper_model", None)
    monkeypatch.setattr(voice_service.settings, "whisper_device", "cuda")
    voice_service._load_whisper()
    assert chamadas == [True]


def test_sync_tts_prefers_openai_voice_when_configured(monkeypatch):
    calls = {}

    def fake_openai_tts(text, language, speed):
        calls["text"] = text
        calls["language"] = language
        calls["speed"] = speed
        return b"mp3"

    monkeypatch.setattr(voice_service.settings, "tts_provider", "auto")
    monkeypatch.setattr(voice_service.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(voice_service, "_sync_openai_tts", fake_openai_tts)

    assert voice_service._sync_tts("  ola   mundo  ", "pt-BR", 0.9) == b"mp3"
    assert calls == {"text": "ola mundo", "language": "pt-BR", "speed": 0.9}


def test_sync_transcribe_can_use_openai_when_enabled(monkeypatch):
    calls = {}

    def fake_openai_transcribe(
        audio_bytes,
        language,
        context="",
        assistant_name="",
    ):
        calls["audio_bytes"] = audio_bytes
        calls["language"] = language
        calls["context"] = context
        calls["assistant_name"] = assistant_name
        return voice_service.STTResponse(
            transcript="abrir calendario",
            confidence=1.0,
            language="pt",
        )

    monkeypatch.setattr(voice_service.settings, "stt_provider", "openai")
    monkeypatch.setattr(voice_service.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(voice_service, "_sync_openai_transcribe", fake_openai_transcribe)
    monkeypatch.setattr(
        voice_service,
        "_load_whisper",
        lambda: (_ for _ in ()).throw(AssertionError("local model not expected")),
    )

    result = voice_service._sync_transcribe(
        b"audio",
        "pt-BR",
        assistant_name="Hannah",
    )

    assert result.transcript == "abrir calendario"
    assert calls == {
        "audio_bytes": b"audio",
        "language": "pt-BR",
        "context": "",
        "assistant_name": "Hannah",
    }
