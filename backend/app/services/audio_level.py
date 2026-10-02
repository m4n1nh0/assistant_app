"""Nivel do audio gravado, para dizer por que um bloco voltou sem fala.

"Nenhuma fala reconhecida" cobre casos que pedem providencias opostas: o microfone
que captou so silencio (mudo, dispositivo errado, fone Bluetooth que caiu) e o audio
com som que o reconhecimento nao entendeu (fala distante, baixa, sala com eco). Sem
medir o sinal, o professor recebe a mesma frase nos dois e nao sabe o que mexer.
"""

from __future__ import annotations

import io
import wave
from array import array
from typing import Optional

#: Pico abaixo disso (fracao do maximo de 16 bits, ~ -46 dBFS) e silencio de
#: dispositivo: nem fala sussurrada ao lado do microfone fica tao baixa.
SILENCE_PEAK = 0.005

#: Pico abaixo disso e voz que o reconhecimento tende a perder: longe do microfone
#: ou com o ganho baixo.
LOW_PEAK = 0.03


def wav_peak(data: bytes) -> Optional[float]:
    """Maior amplitude do WAV de 16 bits, de 0.0 a 1.0.

    `None` quando o formato nao e esse (o app grava m4a so se o WAV nao existir):
    sem medida, nada e afirmado sobre o nivel.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as arquivo:
            if arquivo.getsampwidth() != 2:
                return None
            frames = arquivo.readframes(arquivo.getnframes())
    except (wave.Error, EOFError):
        return None

    amostras = array("h")
    amostras.frombytes(frames[: len(frames) - len(frames) % 2])
    if not amostras:
        return 0.0
    # O sinal cru do arquivo esta em little-endian; array usa a ordem da maquina.
    if _big_endian():
        amostras.byteswap()
    return max(max(amostras), -min(amostras)) / 32768.0


def _big_endian() -> bool:
    import sys

    return sys.byteorder == "big"


def silence_reason(peak: Optional[float]) -> Optional[str]:
    """Explicacao quando o bloco veio mudo; `None` se ha som ou nao se mediu."""
    if peak is not None and peak < SILENCE_PEAK:
        return (
            "o microfone captou so silencio neste bloco. Confira se ele nao "
            "esta no mudo e se e o microfone certo em Configuracoes > Sistema"
        )
    return None


def low_level_hint(peak: Optional[float]) -> str:
    """Complemento para fala nao reconhecida quando o som estava fraco."""
    if peak is not None and SILENCE_PEAK <= peak < LOW_PEAK:
        return (
            " O som chegou muito baixo: aproxime o microfone de quem fala ou "
            "aumente o volume de entrada no Windows."
        )
    return ""
