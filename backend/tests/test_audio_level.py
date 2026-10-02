"""Por que um bloco de aula voltou sem fala: silencio do microfone ou fala nao entendida."""

from __future__ import annotations

import io
import math
import struct
import wave

import pytest

from app.services.audio_level import (
    LOW_PEAK,
    NO_SPEECH,
    SILENCE_PEAK,
    no_speech_reason,
    wav_peak,
)


def wav(amplitude: float, seconds: float = 0.5, rate: int = 16000) -> bytes:
    """WAV mono de 16 bits com um tom da amplitude pedida (fracao do maximo)."""
    total = int(seconds * rate)
    frames = b"".join(
        struct.pack("<h", int(amplitude * 32767 * math.sin(2 * math.pi * 220 * i / rate)))
        for i in range(total)
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(rate)
        arquivo.writeframes(frames)
    return buffer.getvalue()


@pytest.mark.unit
def test_pico_acompanha_a_amplitude_gravada():
    assert wav_peak(wav(0.5)) == pytest.approx(0.5, abs=0.01)
    assert wav_peak(wav(0.1)) == pytest.approx(0.1, abs=0.01)


@pytest.mark.unit
def test_arquivo_so_com_zeros_tem_pico_zero():
    assert wav_peak(wav(0.0)) == 0.0


@pytest.mark.unit
def test_wav_sem_nenhuma_amostra_e_mudo():
    assert wav_peak(wav(0.5, seconds=0.0)) == 0.0


@pytest.mark.unit
@pytest.mark.parametrize("dados", [b"", b"nao e audio", b"ID3\x04\x00mp3 falso"])
def test_formato_que_nao_e_wav_nao_afirma_nada(dados):
    assert wav_peak(dados) is None
    assert no_speech_reason(wav_peak(dados)) == NO_SPEECH


@pytest.mark.unit
def test_wav_de_8_bits_nao_e_medido():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(1)
        arquivo.setframerate(8000)
        arquivo.writeframes(b"\x80" * 100)
    assert wav_peak(buffer.getvalue()) is None


@pytest.mark.unit
def test_dispositivo_sem_sinal_vira_orientacao_sobre_o_microfone():
    motivo = no_speech_reason(wav_peak(wav(0.0)))
    assert "so silencio" in motivo and "microfone" in motivo
    assert "so silencio" in no_speech_reason(SILENCE_PEAK / 2)


@pytest.mark.unit
def test_ruido_de_fundo_de_sala_quieta_nao_e_tratado_como_dispositivo_mudo():
    # Medido num notebook: 3 s de sala quieta davam pico 0.0025.
    motivo = no_speech_reason(0.0025)
    assert "so silencio" not in motivo
    assert "aproxime o microfone" in motivo


@pytest.mark.unit
def test_voz_normal_sem_fala_reconhecida_nao_culpa_o_microfone():
    assert no_speech_reason(wav_peak(wav(0.3))) == NO_SPEECH


@pytest.mark.unit
def test_som_fraco_mas_presente_sugere_aproximar_o_microfone():
    motivo = no_speech_reason((SILENCE_PEAK + LOW_PEAK) / 2)
    assert motivo.startswith(NO_SPEECH)
    assert "aproxime o microfone" in motivo
