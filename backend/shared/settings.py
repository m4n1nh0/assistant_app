"""Configuracao de processo: o que todo servico le, e o que o MCP le.

O `Settings` da assistant-api tem mais de cem campos - banco, voz, modo
educacao, provedores. Um servico que so precisa subir, observar e falar MCP nao
deveria carregar essa classe, nem por import: e o import dela que puxava `app`
para dentro do mcp-service.

Por isso a configuracao e em camadas. `ServiceSettings` e o que qualquer
processo le; `MCPSettings` acrescenta o MCP; o `Settings` da API herda os dois.
Os nomes das variaveis de ambiente nao mudam - a API continua lendo exatamente o
que lia, e cada servico le so o seu recorte.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).parent.parent / ".env"


class ServiceSettings(BaseSettings):
    """O que todo processo le: rede, log, observabilidade e segredo interno."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    reload: bool = True
    log_level: str = "info"

    # Segredo compartilhado das rotas entre servicos (`X-Internal-Token`). Vazio
    # fecha essas rotas em vez de abri-las: a rota interna da API dispara
    # script na maquina do usuario, e ela esta no mesmo dominio publico.
    internal_service_token: str = ""

    # --- Observabilidade --------------------------------------------------
    otel_enabled: bool = False
    otel_service_name: str = "assistant-api"
    otel_exporter_endpoint: str = ""
    otel_console_export: bool = False
    telemetry_memory_events: int = 2000
    # Precos por milhao de tokens, sobrescrevendo a tabela interna:
    # {"claude": {"input": 3.0, "output": 15.0}, "gpt:gpt-4o": {...}}
    llm_pricing: str = ""

    langsmith_enabled: bool = False
    langsmith_api_key: str = Field(
        "",
        validation_alias=AliasChoices("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"),
    )
    langsmith_project: str = "assistant-app"
    langsmith_endpoint: str = ""


class MCPSettings(ServiceSettings):
    """O recorte do MCP: servidores declarados, transporte e resiliencia."""

    # Servidores MCP em JSON. Aceita mapa {"nome": {...}} ou lista com "name".
    # stdio: {"fs": {"command": "npx", "args": ["-y", "@mcp/server-fs", "/dir"]}}
    # http:  {"docs": {"url": "http://localhost:3000/mcp"}}
    mcp_servers: str = ""

    # --- MCP Service ------------------------------------------------------
    # Servidor MCP stdio sobe subprocesso; por isso `remote` aqui tem ganho real
    # de isolamento, diferente do tool-service.
    mcp_transport: str = "local"
    mcp_service_url: str = ""
    mcp_service_port: int = 8002
    mcp_timeout_seconds: float = 30.0
    mcp_max_retries: int = 2
    mcp_retry_backoff_seconds: float = 0.5
    mcp_circuit_failure_threshold: int = 3
    mcp_circuit_reset_seconds: float = 60.0
    mcp_tools_cache_ttl_seconds: float = 300.0

    @property
    def mcp_service_base_url(self) -> str:
        """Endereco do mcp-service, deduzido da porta quando a URL nao foi dada."""
        return (
            self.mcp_service_url.rstrip("/")
            or f"http://127.0.0.1:{self.mcp_service_port}"
        )

    @property
    def uses_remote_mcp(self) -> bool:
        """Diz se o MCP roda em outro processo."""
        return self.mcp_transport.strip().lower() == "remote"


@lru_cache
def get_service_settings() -> ServiceSettings:
    """Configuracao de processo, lida uma vez."""
    return ServiceSettings()


@lru_cache
def get_mcp_settings() -> MCPSettings:
    """Configuracao do MCP, lida uma vez."""
    return MCPSettings()
