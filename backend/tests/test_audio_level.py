"""Por que um bloco de aula voltou sem fala: silencio do microfone ou fala nao entendida."""

from __future__ import annotations

import io
import math
import struct
import wave

import pytest

from app.services.audio_level import (
    LOW_PEAK,
    SILENCE_PEAK,
    low_level_hint,
    silence_reason,
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
    assert silence_reason(wav_peak(dados)) is None
    assert low_level_hint(wav_peak(dados)) == ""


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
def test_silencio_de_dispositivo_vira_orientacao_sobre_o_microfone():
    motivo = silence_reason(wav_peak(wav(0.0)))
    assert motivo and "so silencio" in motivo and "microfone" in motivo
    assert silence_reason(SILENCE_PEAK / 2) is not None


@pytest.mark.unit
def test_voz_normal_nao_e_tratada_como_mudo_nem_como_fraca():
    pico = wav_peak(wav(0.3))
    assert silence_reason(pico) is None
    assert low_level_hint(pico) == ""


@pytest.mark.unit
def test_som_fraco_mas_presente_sugere_aproximar_o_microfone():
    pico = (SILENCE_PEAK + LOW_PEAK) / 2
    assert silence_reason(pico) is None
    assert "aproxime o microfone" in low_level_hint(pico)
