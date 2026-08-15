import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import AliasChoices, Field, field_validator
from typing import Dict, List
from functools import lru_cache

_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = True
    log_level: str = "info"
    secret_key: str = "change-me-in-production"
    cors_origins: str = "http://localhost,http://127.0.0.1"

    claude_api_key: str = ""
    openai_api_key: str = ""
    together_api_key: str = ""
    openrouter_api_key: str = ""
    deepseek_api_key: str = ""
    gemini_api_key: str = ""
    grok_api_key: str = Field(
        "",
        validation_alias=AliasChoices("GROK_API_KEY", "GROQ_API_KEY"),
    )
    huggingface_api_key: str = ""
    grok_model: str = "grok-3"
    groq_model: str = "llama-3.3-70b-versatile"
    together_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    openrouter_model: str = "openrouter/auto"
    deepseek_model: str = "deepseek-chat"
    huggingface_model: str = "mistralai/Mistral-7B-Instruct-v0.3"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    localai_base_url: str = ""
    localai_api_key: str = ""
    localai_model: str = ""

    jwt_secret: str = "change-me-jwt"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440
    registration_invite_required: bool = False
    registration_admin_email: str = ""
    registration_token_expire_minutes: int = 30
    registration_token_request_cooldown_seconds: int = 60
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    smtp_use_ssl: bool = False
    brevo_api_key: str = ""
    redis_url: str = "redis://localhost:6379/0"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    wa_provider: str = "callmebot"
    wa_number: str = ""
    wa_token: str = ""
    wa_sid: str = ""

    google_oauth_client_id: str = Field(
        "",
        validation_alias=AliasChoices(
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CALENDAR_CLIENT_ID",
            "GCAL_CLIENT_ID",
        ),
    )
    google_oauth_client_secret: str = Field(
        "",
        validation_alias=AliasChoices(
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_CALENDAR_CLIENT_SECRET",
            "GCAL_CLIENT_SECRET",
        ),
    )
    microsoft_oauth_client_id: str = Field(
        "",
        validation_alias=AliasChoices(
            "MICROSOFT_OAUTH_CLIENT_ID",
            "MICROSOFT_CLIENT_ID",
            "MS_OAUTH_CLIENT_ID",
            "MS_CLIENT_ID",
        ),
    )
    microsoft_oauth_client_secret: str = Field(
        "",
        validation_alias=AliasChoices(
            "MICROSOFT_OAUTH_CLIENT_SECRET",
            "MICROSOFT_CLIENT_SECRET",
            "MS_OAUTH_CLIENT_SECRET",
            "MS_CLIENT_SECRET",
        ),
    )
    microsoft_oauth_tenant_id: str = Field(
        "common",
        validation_alias=AliasChoices(
            "MICROSOFT_OAUTH_TENANT_ID",
            "MICROSOFT_TENANT_ID",
            "MS_OAUTH_TENANT_ID",
            "MS_TENANT_ID",
        ),
    )

    database_url: str = Field(
        default="mysql+aiomysql://assistant:assistant@localhost:3306/assistant",
        validation_alias="DATABASE_URL",
    )
    database_seed: str = Field(
        default="",
        validation_alias="DATABASE_SEED",
    )
    qdrant_url: str = Field(
        default="http://localhost:6333",
        validation_alias="QDRANT_URL",
    )
    qdrant_api_key: str = ""
    qdrant_collection_prefix: str = "assistant"
    qdrant_vector_size: int = 384

    # Embeddings semanticos do modo educacao. "auto" tenta, nesta ordem,
    # endpoint proprio, LocalAI, Ollama, o modelo local em processo, OpenAI e
    # por fim o hash offline.
    embedding_provider: str = "auto"
    embedding_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_dimensions: int = 0

    # Modelo do provedor "local": roda dentro do backend via ONNX, sem chave e
    # sem servidor externo. 384 dimensoes e ~220 MB baixados no primeiro uso.
    embedding_local_model: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    # Onde guardar o modelo baixado. Vazio usa o cache padrao do huggingface;
    # em container efemero vale apontar para um volume, senao cada deploy
    # baixa de novo.
    embedding_cache_dir: str = ""

    # Servidores MCP em JSON. Aceita mapa {"nome": {...}} ou lista com "name".
    # stdio: {"fs": {"command": "npx", "args": ["-y", "@mcp/server-fs", "/dir"]}}
    # http:  {"docs": {"url": "http://localhost:3000/mcp"}}
    mcp_servers: str = ""
    agent_max_tool_iterations: int = 3
    agent_max_handoffs: int = 2

    education_segment_seconds: int = 60
    education_summary_max_chars: int = 24000
    education_min_segment_chars: int = 12
    education_summary_provider_timeout_seconds: int = 180
    education_summary_max_providers: int = 3
    education_summary_allow_paid_fallback: bool = True

    # Janela de contexto dos modelos locais (LocalAI, Ollama), em tokens. O
    # resumo da aula fatia a transcricao por esse numero: mandar uma aula de
    # duas horas inteira para um modelo com janela pequena nao devolve resumo
    # ruim, devolve erro. Se o seu servidor roda com janela maior, aumente aqui
    # - o resumo fica melhor e gasta menos chamadas.
    local_llm_context_tokens: int = 8192

    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 5
    whisper_best_of: int = 5
    whisper_vad_filter: bool = True
    whisper_vad_min_silence_ms: int = 500

    stt_provider: str = "local"
    openai_stt_model: str = "gpt-4o-mini-transcribe"

    tts_provider: str = "auto"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "nova"
    openai_tts_speed: float = 0.95

    @field_validator("ollama_base_url", mode="before")
    @classmethod
    def normalize_ollama_base_url(cls, value: object) -> str:
        return _normalize_http_base_url(value, default_port=11434)

    @field_validator("localai_base_url", mode="before")
    @classmethod
    def normalize_localai_base_url(cls, value: object) -> str:
        return _normalize_http_base_url(value, default_port=8080)

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def localai_v1_base_url(self) -> str:
        base_url = self.localai_base_url.rstrip("/")
        if not base_url or base_url.endswith("/v1"):
            return base_url
        return f"{base_url}/v1"

    @property
    def active_llms(self) -> List[str]:
        active = []
        if self.claude_api_key:                             active.append("claude")
        if self.openai_api_key:                            active.append("gpt")
        if self.together_api_key:                          active.append("together")
        if self.openrouter_api_key:                        active.append("openrouter")
        if self.deepseek_api_key:                          active.append("deepseek")
        if self.gemini_api_key:                            active.append("gemini")
        if self.grok_api_key:                              active.append("grok")
        if self.huggingface_api_key:                       active.append("hf")
        if self.localai_base_url:                          active.append("localai")
        active.append("llama")
        return active

    @property
    def uses_groq_cloud(self) -> bool:
        return self.grok_api_key.strip().startswith("gsk_")

    @property
    def grok_chat_base_url(self) -> str:
        return (
            "https://api.groq.com/openai/v1"
            if self.uses_groq_cloud
            else "https://api.x.ai/v1"
        )

    @property
    def active_grok_model(self) -> str:
        return self.groq_model if self.uses_groq_cloud else self.grok_model

    @property
    def llm_labels(self) -> Dict[str, str]:
        grok_label = (
            f"Groq ({self.groq_model})"
            if self.uses_groq_cloud
            else f"Grok/xAI ({self.grok_model})"
        )
        return {
            "claude": "Claude Sonnet 4.6",
            "gpt": "GPT-4o",
            "together": f"Together ({self.together_model})",
            "openrouter": f"OpenRouter ({self.openrouter_model})",
            "deepseek": _label_model("DeepSeek", self.deepseek_model),
            "gemini": "Gemini 1.5 Flash",
            "grok": grok_label,
            "localai": _label_model("LocalAI", self.localai_model or "automatico"),
            "llama": f"Ollama ({self.ollama_model})",
            "hf": f"Hugging Face ({self.huggingface_model})",
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _label_model(provider: str, model: str) -> str:
    return provider if not model else f"{provider} ({model})"


def _normalize_http_base_url(value: object, *, default_port: int) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""

    had_scheme = "://" in raw
    normalized = raw if had_scheme else f"http://{raw}"

    # Railway private domains need plain HTTP and the service's listening port.
    # Also add the conventional port when a bare hostname was supplied.
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(normalized)
    hostname = (parsed.hostname or "").lower()
    should_add_port = (
        parsed.port is None
        and (
            not had_scheme
            or hostname.endswith(".railway.internal")
            or hostname in {"localhost", "127.0.0.1", "::1"}
        )
    )
    netloc = parsed.netloc
    if should_add_port:
        if ":" in hostname and not netloc.startswith("["):
            netloc = f"[{hostname}]:{default_port}"
        else:
            netloc = f"{netloc}:{default_port}"

    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))

