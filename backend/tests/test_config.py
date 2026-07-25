from app.core.config import Settings


def test_railway_local_urls_accept_bare_internal_hostnames():
    settings = Settings(
        _env_file=None,
        ollama_base_url=(
            "ollama-7c414367-1ecc-440a-99b9-5125eb1185e9."
            "railway.internal:11434"
        ),
        localai_base_url="localai.railway.internal",
        localai_model="",
    )

    assert settings.ollama_base_url == (
        "http://ollama-7c414367-1ecc-440a-99b9-5125eb1185e9."
        "railway.internal:11434"
    )
    assert settings.localai_base_url == "http://localai.railway.internal:8080"
    assert settings.localai_v1_base_url == (
        "http://localai.railway.internal:8080/v1"
    )
    assert "localai" in settings.active_llms


def test_localai_v1_path_is_not_duplicated():
    settings = Settings(
        _env_file=None,
        localai_base_url="https://localai.example.com/v1/",
    )

    assert settings.localai_v1_base_url == "https://localai.example.com/v1"
