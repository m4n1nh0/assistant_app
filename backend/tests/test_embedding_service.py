import asyncio
from types import SimpleNamespace

import pytest

from app.services import embedding_service as service


def run(coro):
    return asyncio.run(coro)


def configure(monkeypatch, **overrides):
    defaults = {
        "embedding_provider": "auto",
        "embedding_model": "",
        "embedding_base_url": "",
        "embedding_api_key": "",
        "embedding_dimensions": 0,
        "localai_base_url": "",
        "localai_v1_base_url": "",
        "localai_api_key": "",
        "ollama_base_url": "http://localhost:11434",
        "openai_api_key": "",
        "qdrant_vector_size": 384,
    }
    defaults.update(overrides)
    monkeypatch.setattr(service, "settings", SimpleNamespace(**defaults))
    service.reset_cache()
    return defaults


@pytest.fixture(autouse=True)
def clean_cache():
    service.reset_cache()
    yield
    service.reset_cache()


# --- Ordem de provedores ---------------------------------------------------


def test_auto_prefers_self_hosted_over_cloud(monkeypatch):
    configure(
        monkeypatch,
        embedding_base_url="http://vllm:8000",
        localai_base_url="http://localai:8080",
        openai_api_key="sk-test",
    )

    assert service._candidate_providers() == [
        "custom", "localai", "ollama", "openai", "hash",
    ]


def test_auto_skips_providers_that_are_not_configured(monkeypatch):
    configure(monkeypatch, ollama_base_url="", openai_api_key="sk-test")

    assert service._candidate_providers() == ["openai", "hash"]


def test_explicit_provider_is_used_alone(monkeypatch):
    configure(monkeypatch, embedding_provider="ollama", openai_api_key="sk-test")

    assert service._candidate_providers() == ["ollama"]


def test_hash_is_always_the_last_resort(monkeypatch):
    configure(monkeypatch, ollama_base_url="", openai_api_key="")

    assert service._candidate_providers() == ["hash"]


def test_default_model_per_provider(monkeypatch):
    configure(monkeypatch)

    assert service._model_for("ollama") == "nomic-embed-text"
    assert service._model_for("openai") == "text-embedding-3-small"


def test_configured_model_overrides_provider_default(monkeypatch):
    configure(monkeypatch, embedding_model="bge-m3")

    assert service._model_for("ollama") == "bge-m3"


def test_custom_base_url_gets_v1_suffix_once(monkeypatch):
    configure(monkeypatch, embedding_base_url="http://vllm:8000")
    assert service._custom_base_url() == "http://vllm:8000/v1"

    configure(monkeypatch, embedding_base_url="http://vllm:8000/v1/")
    assert service._custom_base_url() == "http://vllm:8000/v1"


# --- Fallback --------------------------------------------------------------


def test_falls_back_to_hash_when_every_provider_fails(monkeypatch):
    configure(monkeypatch, embedding_dimensions=0, qdrant_vector_size=8)

    async def _fail(provider, texts):
        if provider == "hash":
            return [service.hash_embedding(text, 8) for text in texts]
        raise service.EmbeddingError("offline")

    monkeypatch.setattr(service, "_embed_with", _fail)

    vectors = run(service.embed_texts(["aula de historia"]))

    assert len(vectors) == 1
    assert len(vectors[0]) == 8


def test_working_provider_is_reused_on_the_next_call(monkeypatch):
    configure(monkeypatch, localai_base_url="http://localai:8080")
    attempts = []

    async def _embed(provider, texts):
        attempts.append(provider)
        if provider == "localai":
            raise service.EmbeddingError("cold start")
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(service, "_embed_with", _embed)

    run(service.embed_texts(["primeiro"]))
    run(service.embed_texts(["segundo"]))

    # A segunda chamada nao tenta o LocalAI de novo dentro da janela de falha.
    assert attempts == ["localai", "ollama", "ollama"]


def test_raises_when_no_provider_answers(monkeypatch):
    configure(monkeypatch)

    async def _fail(provider, texts):
        raise service.EmbeddingError("offline")

    monkeypatch.setattr(service, "_embed_with", _fail)

    with pytest.raises(service.EmbeddingError):
        run(service.embed_texts(["texto"]))


def test_blank_text_is_replaced_before_embedding(monkeypatch):
    configure(monkeypatch)
    seen = []

    async def _embed(provider, texts):
        seen.extend(texts)
        return [[1.0] for _ in texts]

    monkeypatch.setattr(service, "_embed_with", _embed)

    run(service.embed_texts(["   "]))

    assert seen and seen[0].strip()


# --- Dimensoes -------------------------------------------------------------


def test_configured_dimensions_skip_the_probe_call(monkeypatch):
    configure(monkeypatch, embedding_dimensions=1024)

    async def _fail(provider, texts):
        raise AssertionError("nao deveria consultar o provedor")

    monkeypatch.setattr(service, "_embed_with", _fail)

    assert run(service.resolve_dimensions()) == 1024


def test_dimensions_are_detected_from_the_provider(monkeypatch):
    configure(monkeypatch)

    async def _embed(provider, texts):
        return [[0.0] * 768 for _ in texts]

    monkeypatch.setattr(service, "_embed_with", _embed)

    assert run(service.resolve_dimensions()) == 768


def test_describe_flags_hash_as_non_semantic(monkeypatch):
    configure(monkeypatch, ollama_base_url="", qdrant_vector_size=16)

    info = run(service.describe())

    assert info["ok"] is True
    assert info["provider"] == "hash"
    assert info["semantic"] is False
    assert info["dimensions"] == 16


def test_describe_reports_failure_without_raising(monkeypatch):
    configure(monkeypatch)

    async def _fail(provider, texts):
        raise service.EmbeddingError("sem provedor")

    monkeypatch.setattr(service, "_embed_with", _fail)

    info = run(service.describe())

    assert info["ok"] is False
    assert "sem provedor" in info["error"]


# --- Hash offline ----------------------------------------------------------


def test_hash_embedding_is_deterministic_and_normalised():
    first = service.hash_embedding("aula de matematica", 32)
    second = service.hash_embedding("aula de matematica", 32)

    assert first == second
    assert len(first) == 32
    assert abs(sum(value * value for value in first) - 1.0) < 1e-9


def test_hash_embedding_handles_empty_text():
    vector = service.hash_embedding("", 16)

    assert len(vector) == 16
