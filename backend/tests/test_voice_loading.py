"""Carregar o Whisper sem derrubar a gravacao da aula.

Falha real: o modelo de transcricao so era baixado na primeira gravacao depois do deploy
(o disco do servidor e descartado a cada atualizacao). Se o download falhava, a rota
respondia 500; cada bloco de 60 s tentava baixar de novo; e dois blocos juntos abriam
dois carregamentos do mesmo modelo ao mesmo tempo.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.services import voice_service as voice
from app.services.user_llm_config_service import user_llm_context


@pytest.fixture(autouse=True)
def estado_limpo(monkeypatch):
    monkeypatch.setattr(voice, "_whisper_model", None)
    monkeypatch.setattr(voice, "_whisper_failure", None)
    monkeypatch.setattr(voice, "WHISPER_RETRY_SECONDS", 60)
    monkeypatch.setattr(voice.settings, "whisper_device", "cpu")


def instalar_modelo(monkeypatch, construtor):
    monkeypatch.setitem(
        __import__("sys").modules, "faster_whisper", SimpleNamespace(WhisperModel=construtor)
    )


@pytest.mark.unit
def test_falha_no_download_vira_aviso_legivel_e_nao_erro_generico(monkeypatch):
    def quebra(*args, **kwargs):
        raise OSError("falha ao baixar do Hugging Face")

    instalar_modelo(monkeypatch, quebra)

    with pytest.raises(voice.STTUnavailable) as erro:
        voice._load_whisper()

    mensagem = str(erro.value)
    assert "ainda esta carregando" in mensagem
    assert "audio gravado fica guardado" in mensagem
    # O detalhe tecnico vai para o log, nao para a tela do professor.
    assert "Hugging Face" not in mensagem


@pytest.mark.unit
def test_erro_do_reconhecimento_nao_vira_silencio(monkeypatch):
    """Falha real: o av 19 quebrava `transcribe`, e o erro engolido virava "sem fala"."""
    class ModeloQuebrado:
        def transcribe(self, *args, **kwargs):
            raise TypeError("open() got an unexpected keyword argument 'metadata_errors'")

    monkeypatch.setattr(voice, "_load_whisper", lambda: ModeloQuebrado())
    monkeypatch.setattr(voice.settings, "stt_provider", "local")

    with pytest.raises(voice.STTUnavailable) as erro:
        voice._sync_transcribe(b"RIFF....", "pt")

    assert "falhou ao processar este bloco" in str(erro.value)
    assert "TypeError" in str(erro.value)


@pytest.mark.unit
def test_fala_nao_reconhecida_continua_sendo_resposta_vazia(monkeypatch):
    """O que e mesmo silencio nao e erro: volta vazio, e o app marca o bloco."""
    class ModeloMudo:
        def transcribe(self, *args, **kwargs):
            return iter(()), SimpleNamespace(language="pt")

    monkeypatch.setattr(voice, "_load_whisper", lambda: ModeloMudo())
    monkeypatch.setattr(voice.settings, "stt_provider", "local")

    resposta = voice._sync_transcribe(b"RIFF....", "pt")

    assert resposta.transcript == ""


@pytest.mark.unit
def test_requirements_limita_o_av_abaixo_da_19():
    """O av 19 quebra o faster-whisper 1.2.1; o teto precisa continuar no arquivo."""
    from pathlib import Path

    texto = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text(
        encoding="utf-8"
    )
    linhas = [linha.strip() for linha in texto.splitlines()]

    assert any(linha.startswith("av") and "<19" in linha for linha in linhas)


@pytest.mark.unit
def test_falha_fica_guardada_e_nao_dispara_novo_download(monkeypatch):
    tentativas = []

    def quebra(*args, **kwargs):
        tentativas.append(1)
        raise OSError("sem rede")

    instalar_modelo(monkeypatch, quebra)

    for _ in range(5):
        with pytest.raises(voice.STTUnavailable):
            voice._load_whisper()

    assert len(tentativas) == 1


@pytest.mark.unit
def test_depois_do_prazo_tenta_de_novo_e_o_sucesso_limpa_a_falha(monkeypatch):
    estado = {"falha": True, "tentativas": 0}

    class Modelo:
        def __init__(self, *args, **kwargs):
            estado["tentativas"] += 1
            if estado["falha"]:
                raise OSError("sem rede")

    instalar_modelo(monkeypatch, Modelo)
    relogio = {"agora": 1000.0}
    monkeypatch.setattr(voice.time, "monotonic", lambda: relogio["agora"])

    with pytest.raises(voice.STTUnavailable):
        voice._load_whisper()

    relogio["agora"] += voice.WHISPER_RETRY_SECONDS - 1  # ainda dentro do prazo
    with pytest.raises(voice.STTUnavailable):
        voice._load_whisper()
    assert estado["tentativas"] == 1

    estado["falha"] = False
    relogio["agora"] += 2  # passou do prazo
    modelo = voice._load_whisper()

    assert isinstance(modelo, Modelo) and estado["tentativas"] == 2
    assert voice._whisper_failure is None
    assert voice._load_whisper() is modelo and estado["tentativas"] == 2


@pytest.mark.unit
def test_biblioteca_ausente_tambem_e_aviso_claro(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "faster_whisper", None)  # import falha

    with pytest.raises(voice.STTUnavailable) as erro:
        voice._load_whisper()

    assert "nao esta instalado" in str(erro.value)


@pytest.mark.unit
def test_gravacoes_simultaneas_carregam_o_modelo_uma_vez_so(monkeypatch):
    construcoes = []

    class Lento:
        def __init__(self, *args, **kwargs):
            construcoes.append(threading.get_ident())
            time.sleep(0.2)

    instalar_modelo(monkeypatch, Lento)
    modelos, erros = [], []

    def pedir():
        try:
            modelos.append(voice._load_whisper())
        except Exception as exc:  # pragma: no cover - so aparece se der errado
            erros.append(exc)

    threads = [threading.Thread(target=pedir) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert erros == []
    assert len(construcoes) == 1
    assert len({id(modelo) for modelo in modelos}) == 1 and len(modelos) == 8


@pytest.mark.unit
def test_o_erro_de_carga_chega_a_quem_transcreve(monkeypatch):
    def quebra(*args, **kwargs):
        raise OSError("sem rede")

    instalar_modelo(monkeypatch, quebra)
    monkeypatch.setattr(voice.settings, "stt_provider", "local")

    with pytest.raises(voice.STTUnavailable):
        voice._sync_transcribe(b"RIFF....", "pt")


# --- carregar na subida -----------------------------------------------------------------


@pytest.mark.unit
def test_aquecimento_diz_se_o_modelo_ficou_pronto(monkeypatch):
    instalar_modelo(monkeypatch, lambda *a, **k: object())
    monkeypatch.setattr(voice.settings, "stt_provider", "local")
    assert voice.warm_whisper() is True

    monkeypatch.setattr(voice, "_whisper_model", None)

    def quebra(*args, **kwargs):
        raise OSError("sem rede")

    instalar_modelo(monkeypatch, quebra)
    assert voice.warm_whisper() is False  # nao levanta: a subida nao pode cair


@pytest.mark.unit
def test_com_provedor_externo_configurado_nao_baixa_o_modelo_local(monkeypatch):
    chamadas = []
    instalar_modelo(monkeypatch, lambda *a, **k: chamadas.append(1))
    monkeypatch.setattr(voice.settings, "stt_provider", "openai")
    monkeypatch.setattr(voice.settings, "openai_api_key", "sk-teste")

    assert voice.warm_whisper() is False
    assert chamadas == []


@pytest.mark.unit
def test_subida_do_servidor_sobrevive_a_qualquer_falha_do_aquecimento(monkeypatch):
    from app import main

    for comportamento in (lambda: True, lambda: False, self_raise):
        monkeypatch.setattr(main, "warm_whisper", comportamento)
        asyncio.run(main._warm_voice_model())  # nao levanta


def self_raise():
    raise RuntimeError("explodiu")


# --- o que o professor e o app recebem ---------------------------------------------------


@pytest.mark.integration
def test_rota_de_voz_responde_503_com_a_mensagem_e_pede_para_tentar_depois(monkeypatch):
    from app.routers import routes

    async def indisponivel(*args, **kwargs):
        raise voice.STTUnavailable("O reconhecimento de voz ainda esta carregando.")

    monkeypatch.setattr(routes, "transcribe_audio", indisponivel)
    app = FastAPI()
    app.include_router(routes.router_voice)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u", "tutor_id": "t"}
    app.dependency_overrides[user_llm_context] = lambda: None

    resposta = TestClient(app).post(
        "/voice/transcribe", files={"file": ("a.wav", b"RIFF....", "audio/wav")}
    )

    assert resposta.status_code == 503
    assert resposta.json()["detail"] == "O reconhecimento de voz ainda esta carregando."
    assert resposta.headers["retry-after"] == "60"
