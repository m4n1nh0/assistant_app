"""Contratos de API: todo payload que entra ou sai do backend em Pydantic.

Este e o unico lugar onde o formato trocado com a interface Flutter e declarado -
os routers so validam contra estes modelos, e o OpenAPI em `/docs` e gerado
deles. Os modelos ORM ficam em `app.core.database`; aqui nao ha persistencia.

A nomenclatura segue o papel do modelo no ciclo da requisicao:

| Sufixo | Papel |
| --- | --- |
| `...Request` | corpo recebido do cliente |
| `...Response` | corpo devolvido pela rota |
| `...Create` / `...Update` | escrita de um recurso (POST / PATCH) |
| `...Action` | acao que o assistente pede a interface para executar na maquina |
| `...Enum` | dominio fechado de valores aceitos |

Os modelos estao agrupados por dominio, na ordem: chat, autenticacao e contas,
configuracao, calendario, notificacao e voz, WebSocket, status de LLM, desktop e
acoes locais, memoria, automacoes, atalhos, alunos e presenca, modo educacao
(disciplina, turma, aula, resumo, pontos) e quiz.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal, Union
from datetime import date, datetime
from enum import Enum


class LLMEnum(str, Enum):
    """Provedores de LLM que o backend sabe chamar.

    O valor e a chave usada em `LLM_CALLERS`/`LLM_STREAMERS` de
    `app.services.llm_service` e tambem no que a interface guarda como preferencia.
    """
    claude = "claude"
    gpt    = "gpt"
    together = "together"
    openrouter = "openrouter"
    deepseek = "deepseek"
    gemini = "gemini"
    grok   = "grok"
    localai = "localai"
    llama  = "llama"
    hf     = "hf"


class ResponseModeEnum(str, Enum):
    """Como uma pergunta e distribuida entre os provedores.

    `single` usa um provedor; `multi` pergunta a varios e devolve as respostas lado
    a lado; `chain` encadeia, passando a saida de um como entrada do proximo.
    """
    single = "single"
    multi  = "multi"
    chain  = "chain"


class Message(BaseModel):
    """Uma fala do historico de chat, com papel e conteudo."""
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    """Pergunta enviada ao chat, com historico e preferencia de provedor.

    `llm` nulo deixa a escolha com o roteamento; `stream` pede resposta incremental
    por SSE em vez do corpo unico.
    """
    message: str
    history: List[Message] = Field(default_factory=list)
    llm: Optional[LLMEnum] = None
    mode: ResponseModeEnum = ResponseModeEnum.single
    session_id: str = "default"
    stream: bool = False


class ChatLogRequest(BaseModel):
    """Troca respondida fora do backend (agente conectado local) que precisa
    entrar no histórico para manter memória e contexto completos."""

    message: str
    response: str
    llm: str = Field(min_length=1, max_length=40)
    session_id: str = "default"


class LLMResponse(BaseModel):
    """Resposta normalizada de um unico provedor.

    Todos os provedores sao traduzidos para este formato, entao quem consome nao
    precisa saber o formato nativo de cada API.
    """
    llm: str
    content: str
    is_error: bool = False
    duration_ms: int = 0
    tokens_used: Optional[int] = None


class ChatResponse(BaseModel):
    """Resposta do chat, com o texto e qual provedor efetivamente atendeu."""
    session_id: str
    mode: str
    responses: List[LLMResponse]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    action: Optional[Union["LaunchAction", "ShortcutRegistrationAction", "ComputerAction", "CodingAction", "CalendarCreateAction", "EducationOpenAction"]] = None


class LoginRequest(BaseModel):
    """Credenciais de login: usuario ou email, mais a senha."""
    username: str
    password: str


class RegisterRequest(BaseModel):
    """Dados do cadastro, com o token de convite quando exigido."""
    username: str
    password: str
    registration_token: str = ""


class ChangePasswordRequest(BaseModel):
    """Troca de senha da conta autenticada, conferindo a senha atual."""
    current_password: str
    new_password: str


class PasswordRecoveryRequest(BaseModel):
    """Pedido de recuperacao, identificando a conta por usuario ou email."""
    identifier: str = Field(max_length=255)


class PasswordRecoveryConfirmRequest(BaseModel):
    """Token de recuperacao e a nova senha."""
    token: str = Field(max_length=512)
    new_password: str = Field(max_length=1024)


class PublicMessageResponse(BaseModel):
    """Resposta neutra de rota publica.

    Usada onde o conteudo nao pode variar conforme a conta existir ou nao.
    """
    success: bool = True
    message: str


class AuthResponse(BaseModel):
    """Resultado da autenticacao, com o token de sessao quando ela vale."""
    success: bool
    token: Optional[str] = None
    message: str = ""
    expires_in: int = 86400


class AuthStatusResponse(BaseModel):
    """Estado do cadastro da instalacao, consultado antes do login.

    Diz se ainda falta criar o primeiro administrador, se o cadastro exige convite e
    se ha canal de email configurado para entregar o token.
    """
    needs_setup: bool
    invite_registration_enabled: bool = True
    registration_requires_token: bool = False
    registration_delivery_configured: bool = False
    admin_email_hint: Optional[str] = None


class RegistrationTokenResponse(BaseModel):
    """Resultado do pedido de token do primeiro cadastro."""
    success: bool
    message: str
    admin_email_hint: Optional[str] = None


class AdminInviteRequest(BaseModel):
    """Email do usuario a convidar."""
    email: str


class AdminInviteResponse(BaseModel):
    """Resultado do convite, com o email mascarado e o vencimento."""
    success: bool
    message: str
    email_hint: str
    expires_at: datetime


class AdminUserResponse(BaseModel):
    """Conta listada no painel do administrador."""
    id: str
    username: str
    email: Optional[str] = None
    role: str
    tutor_id: Optional[str] = None
    is_active: bool
    created_at: datetime


class LLMConfig(BaseModel):
    """Chaves e modelos dos provedores de LLM.

    Continua existindo para o caminho legado de configuracao; a preferencia por
    usuario mora em `TutorSettingModel` e as chaves cifradas em `CredentialModel`.
    """
    claude_api_key: str = ""
    openai_api_key: str = ""
    together_api_key: str = ""
    openrouter_api_key: str = ""
    deepseek_api_key: str = ""
    gemini_api_key: str = ""
    grok_api_key: str = ""
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


class AuthConfig(BaseModel):
    """Metodos de desbloqueio local da interface: PIN, voz e face."""
    pin_hash: str = ""
    voice_passphrase: str = ""
    face_enabled: bool = False
    pin_enabled: bool = False
    voice_enabled: bool = False


class NotifConfig(BaseModel):
    """Preferencias de notificacao: canais, antecedencia e fallback.

    `reminder_minutes` aceita de 5 a 1440 minutos. `fallback_enabled` autoriza tentar
    o segundo canal quando o primeiro falha.
    """
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_enabled: bool = False
    wa_provider: str = "callmebot"
    wa_number: str = ""
    wa_token: str = ""
    wa_sid: str = ""
    wa_enabled: bool = False
    notify_15min: bool = True
    reminder_minutes: int = Field(default=15, ge=5, le=1440)
    notify_on_time: bool = True
    fallback_enabled: bool = True
    include_link: bool = True


class CalendarConfig(BaseModel):
    """Credenciais e estado de conexao dos calendarios Google e Microsoft."""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""
    google_enabled: bool = False
    ms_client_id: str = ""
    ms_client_secret: str = ""
    ms_tenant_id: str = "common"
    ms_refresh_token: str = ""
    ms_enabled: bool = False


class GenderEnum(str, Enum):
    """Genero da persona da assistente, usado na concordancia e na voz."""
    f = "f"
    m = "m"


class AssistantConfig(BaseModel):
    """Persona da assistente: nome, genero, idioma e modo de resposta.

    E a configuracao que personaliza a assistente de cada usuario sem mexer na marca
    do produto.
    """
    assistant_name: str = "Assistant"
    gender: GenderEnum = GenderEnum.f
    user_name: str = ""
    personality: str = ""
    language: str = "pt-BR"
    response_mode: ResponseModeEnum = ResponseModeEnum.single
    tts_enabled: bool = True


class FullConfig(BaseModel):
    """Configuracao completa devolvida a interface, agregando os blocos acima."""
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    notif: NotifConfig = Field(default_factory=NotifConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)


class CalendarEvent(BaseModel):
    """Evento de calendario ja normalizado, independente do provedor de origem."""
    id: str
    title: str
    start_time: datetime
    end_time: Optional[datetime] = None
    source: Literal["google", "teams", "outlook"]
    meeting_url: Optional[str] = None
    description: Optional[str] = None
    notified_15: bool = False
    notified_0:  bool = False


class CalendarEventCreateRequest(BaseModel):
    """Criacao de evento em uma conta de calendario conectada."""
    provider: Literal["google", "microsoft"]
    account_id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=300)
    start_time: datetime
    end_time: datetime
    timezone: str = Field(default="America/Sao_Paulo", min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=4000)
    location: Optional[str] = Field(default=None, max_length=500)
    confirmed: bool = False


class ClassAgendaCreateRequest(BaseModel):
    """Geracao da agenda de aulas de uma ou mais turmas.

    Cria no calendario a serie recorrente correspondente aos horarios da turma.
    """
    provider: Literal["google", "microsoft"]
    account_id: str = Field(min_length=1, max_length=120)
    class_ids: List[str] = Field(min_length=1, max_length=100)
    date_from: date
    date_to: date
    timezone: str = Field(default="America/Sao_Paulo", min_length=1, max_length=80)
    confirmed: bool = False


class ClassAgendaCreateResponse(BaseModel):
    """Resultado da geracao: series criadas, puladas e falhas."""
    class_count: int = 0
    created_series: int = 0
    skipped_series: int = 0
    failed_series: int = 0
    errors: List[str] = Field(default_factory=list)


class EventsResponse(BaseModel):
    """Lista de eventos com total e instante da ultima sincronizacao."""
    events: List[CalendarEvent]
    total: int
    synced_at: datetime = Field(default_factory=datetime.utcnow)


class NotifRequest(BaseModel):
    """Envio avulso de notificacao pelos canais escolhidos."""
    message: str
    event_id: Optional[str] = None
    channels: List[Literal["telegram", "whatsapp"]] = ["telegram", "whatsapp"]


class NotifResult(BaseModel):
    """Resultado por canal, com o erro de cada um quando houver."""
    telegram_ok: bool = False
    whatsapp_ok: bool = False
    telegram_error: Optional[str] = None
    whatsapp_error: Optional[str] = None

    @property
    def any_ok(self) -> bool:
        """Diz se ao menos um canal entregou a notificacao."""
        return self.telegram_ok or self.whatsapp_ok


class TTSRequest(BaseModel):
    """Texto a sintetizar, com idioma e velocidade."""
    text: str
    language: str = "pt-BR"
    speed: float = 1.0


class STTResponse(BaseModel):
    """Transcricao do audio, com confianca e idioma reconhecido."""
    transcript: str
    confidence: float = 1.0
    language: str = ""


class WSMessage(BaseModel):
    """Envelope generico do WebSocket: tipo do evento mais payload."""
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    session_id: str = "default"


class WSChatPayload(BaseModel):
    """Payload de mensagem de chat recebida pelo WebSocket."""
    message: str
    mode: ResponseModeEnum = ResponseModeEnum.single
    llm: Optional[str] = None
    stream: bool = True


class LLMStatus(BaseModel):
    """Estado de um provedor de LLM em um instante.

    Distingue tres coisas que costumam ser confundidas: `configured` (ha chave),
    `online` (a API respondeu) e `available` (da para usar agora). `balance` so vem
    preenchido nos provedores que expoem consulta de saldo.
    """
    id: str
    label: str
    configured: bool = False
    online: bool = False
    available: bool = False
    has_balance_check: bool = False
    balance_ok: Optional[bool] = None
    balance: Optional[str] = None
    currency: Optional[str] = None
    status: str = "missing_key"
    error: Optional[str] = None
    checked_at: datetime = Field(default_factory=datetime.utcnow)


class UserLLMProviderUpdate(BaseModel):
    """Alteracao de um provedor de LLM do usuario.

    `clear_api_key` apaga a chave salva; `api_key` vazio mantem a atual, o que
    permite editar o modelo sem reenviar o segredo.
    """
    id: str = Field(min_length=1, max_length=40)
    enabled: bool = True
    model: str = Field(default="", max_length=240)
    api_key: str = Field(default="", max_length=4096)
    clear_api_key: bool = False


class UserLLMConfigUpdate(BaseModel):
    """Lote de alteracoes de provedores enviado pela interface."""
    providers: List[UserLLMProviderUpdate] = Field(default_factory=list, max_length=8)


class HealthResponse(BaseModel):
    """Diagnostico do backend consumido pela interface e pelo healthcheck.

    Reune provedores ativos e disponiveis, status detalhado por provedor, fontes de
    calendario conectadas, canais de notificacao, uptime e uso de armazenamento.
    """
    status: str = "ok"
    version: str = "1.0.0"
    active_llms: List[str] = Field(default_factory=list)
    available_llms: List[str] = Field(default_factory=list)
    llm_labels: Dict[str, str] = Field(default_factory=dict)
    llm_status: Dict[str, LLMStatus] = Field(default_factory=dict)
    calendar_sources: List[str] = Field(default_factory=list)
    notifications: Dict[str, bool] = Field(default_factory=dict)
    uptime_seconds: float = 0
    storage: Dict[str, Any] = Field(default_factory=dict)


class DesktopWindowInfo(BaseModel):
    """Uma janela aberta: identificacao, titulo e processo dono."""
    id: str
    handle: int
    title: str
    process_id: int
    process_name: str = ""
    executable_path: str = ""
    class_name: str = ""
    is_active: bool = False
    bounds: Dict[str, int] = Field(default_factory=dict)


class DesktopWindowsResponse(BaseModel):
    """Janelas abertas, com a plataforma e se ela e suportada."""
    platform: str
    supported: bool
    active_window_id: Optional[str] = None
    windows: List[DesktopWindowInfo] = Field(default_factory=list)


class DesktopWindowContextResponse(BaseModel):
    """Texto extraido de uma janela, pronto para virar contexto de prompt.

    `truncated` avisa que o conteudo passou do limite e foi cortado.
    """
    window: DesktopWindowInfo
    text: str = ""
    extraction_method: str = "metadata"
    warning: Optional[str] = None
    truncated: bool = False
    context_prompt: str = ""


class ComputerActionInfo(BaseModel):
    """Acao de computador disponivel, com risco e se pede confirmacao."""
    id: str
    name: str
    description: str = ""
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_confirmation: bool = False


class ComputerActionRunRequest(BaseModel):
    """Pedido de execucao de uma acao, com os argumentos dela."""
    tutor_id: str = "default"
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ComputerActionCommandOutput(BaseModel):
    """Saida de um comando: codigo de retorno, stdout, stderr e duracao."""
    label: str
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0


class ComputerActionRunResponse(BaseModel):
    """Resultado da acao executada pela interface."""
    action: ComputerActionInfo
    status: Literal["executed", "failed"]
    summary: str = ""
    outputs: List[ComputerActionCommandOutput] = Field(default_factory=list)
    duration_ms: int = 0


class ScriptShell(str, Enum):
    """Shells aceitos na execucao de script."""
    powershell = "powershell"
    pwsh = "pwsh"
    cmd = "cmd"
    bash = "bash"
    sh = "sh"
    zsh = "zsh"


class ScriptShellsResponse(BaseModel):
    """Shells disponiveis e qual e o padrao da plataforma."""
    default_shell: str
    available_shells: List[str] = Field(default_factory=list)


class ScriptSnippetCreate(BaseModel):
    """Novo script salvo, com shell, diretorio e limite de tempo."""
    tutor_id: str = "default"
    name: str
    shell: ScriptShell
    script: str
    working_directory: Optional[str] = None
    timeout_seconds: int = Field(default=30, ge=1, le=180)
    allow_high_risk: bool = False
    description: Optional[str] = None


class ScriptSnippetUpdate(BaseModel):
    """Alteracao de um script salvo."""
    name: Optional[str] = None
    shell: Optional[ScriptShell] = None
    script: Optional[str] = None
    working_directory: Optional[str] = None
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=180)
    allow_high_risk: Optional[bool] = None
    description: Optional[str] = None


class ScriptSnippetResponse(BaseModel):
    """Script salvo como devolvido a interface."""
    id: str
    tutor_id: str
    name: str
    shell: ScriptShell
    script: str
    working_directory: Optional[str] = None
    timeout_seconds: int = 30
    allow_high_risk: bool = False
    description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class TutorProfileRequest(BaseModel):
    """Criacao ou atualizacao do perfil de dados do usuario."""
    id: Optional[str] = None
    display_name: str
    email: Optional[str] = None
    timezone: str = "America/Sao_Paulo"
    locale: str = "pt-BR"
    notes: str = ""
    assistant_name: str = "Assistant"
    gender: GenderEnum = GenderEnum.f
    personality: str = ""
    response_mode: ResponseModeEnum = ResponseModeEnum.single
    tts_enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)


class TutorProfileResponse(BaseModel):
    """Perfil de dados do usuario."""
    tutor_id: str
    display_name: str
    email: Optional[str] = None
    timezone: str
    locale: str
    notes: str = ""
    assistant_name: str
    gender: GenderEnum = GenderEnum.f
    personality: str = ""
    response_mode: str
    tts_enabled: bool
    config: Dict[str, Any] = Field(default_factory=dict)


class TutorSettingRequest(BaseModel):
    """Gravacao de uma preferencia do usuario, com escopo."""
    key: str
    value: Dict[str, Any] = Field(default_factory=dict)
    scope: str = "general"


class TutorSettingResponse(BaseModel):
    """Preferencia do usuario como esta salva."""
    id: str
    tutor_id: str
    key: str
    value: Dict[str, Any] = Field(default_factory=dict)
    scope: str


class MemoryReviewCreate(BaseModel):
    """Fato candidato a memoria de longo prazo, enviado para revisao."""
    tutor_id: str
    category: Literal[
        "tutor_preferences",
        "behavior_guidelines",
        "approved_instructions",
        "automation_knowledge",
    ]
    content: str
    source: str = "assistant"
    confidence: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryReviewResponse(BaseModel):
    """Fato em revisao, com categoria, origem e situacao."""
    id: str
    tutor_id: str
    category: str
    content: str
    source: str
    status: str
    confidence: float
    qdrant_point_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    reviewer_note: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None


class MemoryDecisionRequest(BaseModel):
    """Decisao sobre um fato em revisao, com nota opcional."""
    reviewer_note: str = ""


class MemoryVoiceDecisionRequest(BaseModel):
    """Decisao falada sobre um fato, ainda por interpretar."""
    transcript: str
    reviewer_note: str = ""


class MemoryVoiceDecisionResponse(BaseModel):
    """O que foi entendido da fala e o efeito na memoria."""
    decision: Literal["approved", "rejected", "unclear"]
    message: str
    memory: MemoryReviewResponse


class MemorySearchResponse(BaseModel):
    """Resultado da busca semantica na memoria, ja ordenado por relevancia."""
    id: str
    score: float
    category: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AutomationApproveRequest(BaseModel):
    """Aprovacao de automacao, com gatilho, instrucoes e agendamento."""
    tutor_id: str
    title: str
    description: str = ""
    trigger: str
    instructions: str
    schedule: Dict[str, Any] = Field(default_factory=dict)
    risk_level: Literal["low", "medium", "high"] = "low"
    enabled: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AutomationResponse(BaseModel):
    """Automacao aprovada, com gatilho, agendamento e nivel de risco."""
    id: str
    tutor_id: str
    title: str
    description: str = ""
    trigger: str
    instructions: str
    schedule: Dict[str, Any] = Field(default_factory=dict)
    risk_level: str
    enabled: bool
    approved_at: datetime
    last_run_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AutomationUpdateRequest(BaseModel):
    """Alteracao de automacao ja aprovada."""
    enabled: Optional[bool] = None
    schedule: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class ShortcutType(str, Enum):
    """Tipo de alvo do atalho: aplicativo, URL ou comando."""
    app = "app"
    url = "url"
    command = "command"


class ShortcutCreate(BaseModel):
    """Novo atalho, com alvo e apelidos de voz."""
    tutor_id: str
    name: str
    type: ShortcutType
    target: str
    aliases: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class ShortcutUpdate(BaseModel):
    """Alteracao de um atalho."""
    name: Optional[str] = None
    type: Optional[ShortcutType] = None
    target: Optional[str] = None
    aliases: Optional[List[str]] = None
    description: Optional[str] = None


class ShortcutResponse(BaseModel):
    """Atalho como devolvido a interface, com contadores de uso."""
    id: str
    tutor_id: str
    name: str
    type: ShortcutType
    target: str
    aliases: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    use_count: int = 0
    last_used_at: Optional[datetime] = None
    created_at: datetime


class ShortcutLaunchRequest(BaseModel):
    """Registro de uma execucao de atalho feita pela interface."""
    status: Literal["executed", "failed"] = "executed"
    source: str = "interface"
    platform: Optional[str] = None
    request: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class ShortcutLaunchResponse(BaseModel):
    """Execucao de atalho registrada no historico."""
    id: str
    tutor_id: str
    shortcut_id: Optional[str] = None
    shortcut_name: str
    target_type: str
    target: str
    status: str
    source: str
    platform: Optional[str] = None
    request: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    launched_at: datetime


class LaunchAction(BaseModel):
    """Pedido de abertura de app, URL ou comando ja registrado como atalho."""
    type: Literal["launch", "open_project"] = "launch"
    shortcut_id: str
    name: str
    target: str
    target_type: ShortcutType
    browser: str = ""


class ShortcutRegistrationAction(BaseModel):
    """Pedido do assistente para cadastrar um novo atalho."""
    type: Literal["register_shortcut"] = "register_shortcut"
    name: str
    query: str = ""
    target: str = ""
    target_type: ShortcutType = ShortcutType.app
    aliases: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    open_after_register: bool = False


class ComputerAction(BaseModel):
    """Acao no computador que o assistente pede a interface para executar."""
    type: Literal["computer_action"] = "computer_action"
    action_id: str
    name: str
    description: str = ""
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_confirmation: bool = False
    arguments: Dict[str, Any] = Field(default_factory=dict)


class CodingAction(BaseModel):
    """Alteracao de codigo proposta pelo assistente para um workspace local."""
    type: Literal["coding_action"] = "coding_action"
    action_id: str
    name: str
    description: str = ""
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_confirmation: bool = True
    arguments: Dict[str, Any] = Field(default_factory=dict)


class CalendarCreateAction(BaseModel):
    """Pedido de criacao de evento nascido da conversa."""
    type: Literal["calendar_create"] = "calendar_create"
    title: str
    start_time: datetime
    end_time: datetime
    timezone: str = "America/Sao_Paulo"
    provider: Literal["auto", "google", "microsoft"] = "auto"
    description: Optional[str] = None
    location: Optional[str] = None
    requires_confirmation: bool = True


class EducationOpenAction(BaseModel):
    """Pedido para a interface abrir o modo educacao em um contexto."""
    type: Literal["education_open"] = "education_open"
    destination: Literal["lesson", "attendance"] = "lesson"
    reason: str = ""
    requires_confirmation: bool = True


class ActionAuditRequest(BaseModel):
    """Linha de auditoria enviada pela interface apos executar uma acao."""
    tutor_id: str
    automation_id: Optional[str] = None
    action_type: str
    status: Literal["planned", "executed", "failed", "skipped"]
    request: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)


class ActionAuditResponse(BaseModel):
    """Linha do log de auditoria."""
    id: str
    tutor_id: str
    automation_id: Optional[str] = None
    action_type: str
    status: str
    request: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


# --- Modo educacao --------------------------------------------------------


class StudentCreate(BaseModel):
    """Cadastro de aluno em uma turma."""
    name: str
    class_id: Optional[str] = None
    class_group: str = ""
    discipline: str = ""
    external_id: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    active: bool = True


class StudentUpdate(BaseModel):
    """Alteracao de dados de um aluno."""
    name: Optional[str] = None
    class_id: Optional[str] = None
    class_group: Optional[str] = None
    discipline: Optional[str] = None
    external_id: Optional[str] = None
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None
    active: Optional[bool] = None


class StudentResponse(BaseModel):
    """Aluno como devolvido a interface."""
    id: str
    tutor_id: str
    name: str
    class_id: Optional[str] = None
    class_group: str = ""
    discipline: str = ""
    external_id: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    active: bool
    created_at: datetime


class StudentImportItem(BaseModel):
    """Um aluno dentro de uma importacao em lote."""
    enrollment: str
    name: str


class StudentImportRequest(BaseModel):
    """Importacao em lote de alunos para uma turma."""
    class_id: Optional[str] = None
    class_group: str = ""
    discipline: str = ""
    students: List[StudentImportItem] = Field(min_length=1, max_length=1000)


class StudentImportResponse(BaseModel):
    """Resultado da importacao: criados, atualizados e total."""
    created: int
    updated: int
    total: int


class StudentBulkDeleteRequest(BaseModel):
    """Remocao em lote de alunos de uma turma."""
    class_id: str
    student_ids: List[str] = Field(min_length=1, max_length=1000)


class StudentBulkDeleteResponse(BaseModel):
    """Quantos alunos foram pedidos e quantos foram removidos."""
    requested: int
    deleted: int


class AttendanceSessionCreate(BaseModel):
    # `class_id` mantem clientes antigos; novos clientes enviam `class_ids`.
    """Abertura de chamada, para uma ou mais turmas ao mesmo tempo.

    `duration_minutes` define por quanto tempo o QR Code aceita check-in.
    """
    class_id: Optional[str] = None
    class_ids: List[str] = Field(default_factory=list, max_length=20)
    attendance_date: Optional[str] = None
    duration_minutes: int = Field(default=15, ge=1, le=180)
    title: str = Field(default="", max_length=255)
    lesson_id: Optional[str] = None


class AttendanceRecordCreate(BaseModel):
    """Presenca informada pela matricula do aluno."""
    enrollment: str = Field(min_length=1, max_length=80)


class AttendanceRecordResponse(BaseModel):
    """Presenca registrada, com origem e horario do check-in."""
    id: str
    student_id: str
    enrollment: str
    student_name: str
    source: str
    checked_in_at: datetime
    class_id: str = ""
    class_label: str = ""
    discipline: str = ""


class AttendanceStudentResponse(BaseModel):
    """Aluno dentro do resultado de uma chamada."""
    student_id: str
    enrollment: str
    student_name: str
    class_id: str = ""
    class_label: str = ""
    discipline: str = ""


class AttendanceClassResponse(BaseModel):
    """Turma dentro de uma chamada, com o total esperado."""
    class_id: str
    class_label: str
    discipline: str = ""
    semester: str = ""
    expected_count: int = 0


class AttendanceSessionResponse(BaseModel):
    """Chamada de uma aula, com alunos, turmas e totais.

    Uma sessao pode cobrir mais de uma turma - dai `AttendanceClassResponse` sair
    como lista dentro dela.
    """
    id: str
    class_id: str
    class_label: str
    class_ids: List[str] = Field(default_factory=list)
    classes: List[AttendanceClassResponse] = Field(default_factory=list)
    discipline: str
    semester: str = ""
    attendance_date: str
    title: str = ""
    lesson_id: Optional[str] = None
    opened_at: datetime
    expires_at: datetime
    closed_at: Optional[datetime] = None
    open: bool
    check_in_url: str = ""
    check_in_path: str = ""
    expected_count: int = 0
    present_count: int = 0
    records: List[AttendanceRecordResponse] = Field(default_factory=list)
    absent_students: List[AttendanceStudentResponse] = Field(default_factory=list)


class AttendanceReportResponse(BaseModel):
    """Consolidado de presenca por aluno em um intervalo."""
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    class_id: Optional[str] = None
    session_count: int = 0
    expected_total: int = 0
    present_total: int = 0
    sessions: List[AttendanceSessionResponse] = Field(default_factory=list)


class LessonCreate(BaseModel):
    """Abertura de uma aula, ligada a disciplina, semestre e turmas."""
    discipline: str
    semester: str = ""
    title: str = ""
    class_group: str = ""
    # Turmas atendidas. Mais de uma significa aula reunida.
    class_ids: List[str] = Field(default_factory=list)
    teacher: Optional[str] = None
    started_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DisciplineCreate(BaseModel):
    """Cadastro de disciplina."""
    code: str = ""
    name: str = ""
    semester: str = ""


class DisciplineUpdate(BaseModel):
    """Alteracao de disciplina."""
    code: Optional[str] = None
    name: Optional[str] = None
    semester: Optional[str] = None
    active: Optional[bool] = None


class DisciplineResponse(BaseModel):
    """Disciplina como devolvida a interface."""
    id: str
    code: str
    name: str
    label: str
    semester: str
    active: bool = True
    class_count: int = 0


class ClassScheduleItem(BaseModel):
    """Dia da semana da turma. 0 = segunda, 6 = domingo."""

    weekday: int = Field(ge=0, le=6)
    start_time: str = ""
    end_time: str = ""


class ClassGroupCreate(BaseModel):
    """Cadastro de turma, com os horarios semanais."""
    code: str = ""
    name: str = ""
    discipline_id: Optional[str] = None
    discipline: str = ""
    schedules: List[ClassScheduleItem] = Field(default_factory=list)


class ClassGroupUpdate(BaseModel):
    """Alteracao de turma e dos horarios dela."""
    code: Optional[str] = None
    name: Optional[str] = None
    discipline_id: Optional[str] = None
    discipline: Optional[str] = None
    active: Optional[bool] = None
    schedules: Optional[List[ClassScheduleItem]] = None


class ClassGroupResponse(BaseModel):
    """Turma como devolvida a interface."""
    id: str
    code: str
    name: str
    discipline_id: Optional[str] = None
    discipline: str
    semester: str = ""
    label: str
    active: bool = True
    student_count: int = 0
    schedules: List[ClassScheduleItem] = Field(default_factory=list)
    schedule_label: str = ""


class LessonUpdate(BaseModel):
    """Alteracao de dados de uma aula."""
    discipline: Optional[str] = None
    title: Optional[str] = None
    class_group: Optional[str] = None
    class_ids: Optional[List[str]] = None
    teacher: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class LessonSegmentResponse(BaseModel):
    """Um trecho transcrito da aula, na ordem em que foi gravado."""
    id: str
    lesson_id: str
    sequence: int
    text: str
    confidence: float
    duration_ms: int
    indexed: bool
    created_at: datetime


class LessonSegmentUpdate(BaseModel):
    """Correcao manual do texto de um trecho."""
    text: str = Field(min_length=1, max_length=20000)


class SemesterUpdate(BaseModel):
    """Ativacao ou desativacao de um semestre."""
    active: bool


class SemesterResponse(BaseModel):
    """Semestre com a contagem de disciplinas e turmas."""
    code: str
    active: bool
    discipline_count: int = 0
    class_count: int = 0


class LessonPointResponse(BaseModel):
    """Ponto extra creditado a um aluno, com o motivo."""
    id: str
    lesson_id: str
    student_id: Optional[str] = None
    student_name: str
    points: float
    reason: Optional[str] = None
    discipline: str
    lesson_date: datetime
    source: str
    confidence: float
    quote: Optional[str] = None
    created_at: datetime


class LessonPointCreate(BaseModel):
    """Credito manual de ponto extra a um aluno."""
    student_name: str
    points: float
    reason: Optional[str] = None
    student_id: Optional[str] = None


class LessonResponse(BaseModel):
    """Aula gravada: identificacao, disciplina, turmas e estado do processamento."""
    id: str
    tutor_id: str
    discipline: str
    semester: str = ""
    title: str = ""
    class_group: str = ""
    class_ids: List[str] = Field(default_factory=list)
    class_labels: List[str] = Field(default_factory=list)
    teacher: Optional[str] = None
    status: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    summary: Optional[str] = None
    summary_llm: Optional[str] = None
    summary_at: Optional[datetime] = None
    summary_style: Optional[str] = None
    segment_count: int = 0
    transcript_chars: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LessonDetailResponse(LessonResponse):
    """A aula com o conteudo pesado junto: transcricao, segmentos e pontos."""
    segments: List[LessonSegmentResponse] = Field(default_factory=list)
    points: List[LessonPointResponse] = Field(default_factory=list)


class LessonSegmentIngestRequest(BaseModel):
    """Ingestao de um bloco ja transcrito pelo cliente."""
    text: str
    confidence: float = 1.0
    duration_ms: int = 0
    extract_points: bool = True


class LessonSegmentIngestResponse(BaseModel):
    """Resultado do envio de um bloco de aula.

    Diz se o trecho foi indexado, e se nao, por que; traz tambem os pontos extras
    detectados naquele bloco.
    """
    segment: Optional[LessonSegmentResponse] = None
    indexed: bool = False
    skipped_reason: Optional[str] = None
    points: List[LessonPointResponse] = Field(default_factory=list)
    lesson: LessonResponse


class LessonSummaryRequest(BaseModel):
    """Pedido de resumo de uma aula ja transcrita."""
    llm: Optional[str] = None
    focus: str = ""
    close_lesson: bool = False
    # "standard" cabe em uma tela; "detailed" reconstroi o desenvolvimento da
    # aula. O servico normaliza: valor desconhecido vira o comum, e um cliente
    # antigo que nao manda o campo continua recebendo o resumo de sempre.
    style: str = "standard"


class ExternalLessonSummaryRequest(BaseModel):
    """Resumo gerado fora do backend, por um agente conectado do usuario.

    Codex e Claude Code rodam na maquina do usuario; o texto nasce la e este
    endpoint e o que o guarda na aula, como o `/chat/log` faz com a conversa.
    """
    summary: str
    llm: str
    style: str = "standard"
    close_lesson: bool = False


class LessonSummaryPromptResponse(BaseModel):
    """Prompt de resumo pronto, para agente conectado executar fora do backend.

    Existe para o caminho em que o resumo roda em um agente na maquina do usuario,
    com janela de contexto muito maior que a dos provedores locais.
    """
    lesson_id: str
    style: str
    system_prompt: str
    prompt: str
    used_segments: int
    transcript_chars: int


class LessonSummaryResponse(BaseModel):
    """Resumo gerado, com provedor usado e quantos trechos entraram."""
    lesson_id: str
    summary: str
    llm: str
    generated_at: datetime
    used_segments: int
    style: str = "standard"
    points: List[LessonPointResponse] = Field(default_factory=list)


class LessonSearchResult(BaseModel):
    """Trecho de aula encontrado na busca semantica, com aula de origem e score."""
    id: str
    score: float
    lesson_id: str
    discipline: str
    lesson_date: str
    sequence: int
    content: str


class PointsReportEntry(BaseModel):
    """Uma linha do relatorio de pontos: aluno, total e origem."""
    student_name: str
    student_id: Optional[str] = None
    total_points: float
    discipline: str
    class_group: str = ""
    lesson_date: str
    entries: List[LessonPointResponse] = Field(default_factory=list)


class PointsReportResponse(BaseModel):
    """Relatorio de pontos por aluno no periodo, usado no PDF academico."""
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    discipline: Optional[str] = None
    class_group: Optional[str] = None
    total_points: float = 0.0
    students: List[PointsReportEntry] = Field(default_factory=list)


class EmbeddingStatusResponse(BaseModel):
    """Provedor de embedding em uso e se a busca e semantica.

    `semantic` falso significa que caiu no hash offline: a busca casa palavra exata
    e nao entende sinonimo.
    """
    ok: bool
    provider: str
    model: Optional[str] = None
    dimensions: Optional[int] = None
    semantic: bool = False
    error: Optional[str] = None


class LessonIndexStatusResponse(BaseModel):
    """Distancia entre a transcricao guardada no MySQL e o indice do Qdrant."""
    segments: int = 0
    pending: int = 0
    embedding: str = ""
    semantic: bool = False


class LessonReindexRequest(BaseModel):
    """Pedido de reindexacao dos trechos de aula no Qdrant."""
    lesson_id: Optional[str] = None
    # Regrava tambem o que ja tem vetor - usado ao trocar de modelo.
    force: bool = False
    limit: int = Field(default=600, ge=1, le=5000)


class LessonReindexResponse(BaseModel):
    """Resultado da reindexacao: indexados, falhas e pendentes."""
    indexed: int = 0
    failed: int = 0
    pending: int = 0
    embedding: str = ""
    error: Optional[str] = None


# --- Quiz Schemas ---

class QuestionOption(BaseModel):
    """Uma alternativa da questao, com o texto e se e a correta."""
    label: str
    texto: str
    correta: bool = False


class QuestionCreate(BaseModel):
    """Questao de quiz, com alternativas, gabarito e justificativa."""
    tipo: Literal["multipla_escolha", "verdadeiro_falso", "aberta", "preenchimento"]
    dificuldade: Literal["facil", "medio", "dificil"] = "medio"
    enunciado: str
    opcoes: Optional[List[QuestionOption]] = None
    resposta_correta: Optional[str] = None
    justificativa: str
    conceitos_relacionados: Optional[List[str]] = None
    topico_origem: Optional[str] = None


class QuestionResponse(QuestionCreate):
    """Questao salva, com o `grounding_score` da verificacao.

    O score mede o quanto a questao se apoia no conteudo da aula - e a defesa contra
    questao inventada pelo modelo.
    """
    id: str
    quiz_id: str
    grounding_score: float = 0.0
    verificado: bool = False
    created_at: datetime


class QuizCreateRequest(BaseModel):
    """Criacao de um quiz a partir de uma aula ou de perguntas informadas."""
    lesson_id: str
    tipo_quiz: Literal["revisao", "diagnostico", "pratica"] = "pratica"
    quantidade_questoes: int = Field(default=10, ge=1, le=50)
    tipos_questao: List[
        Literal["multipla_escolha", "verdadeiro_falso", "aberta"]
    ] = Field(default_factory=lambda: ["multipla_escolha"])
    dificuldade: Literal["mista", "facil", "medio", "dificil"] = "mista"
    llm: Optional[str] = None


class QuizResponse(BaseModel):
    """Quiz com suas questoes, no formato consumido pelo player do aluno."""
    id: str
    lesson_id: str
    titulo: str
    tipo_quiz: str
    status: str = "open"
    total_questoes: int
    tempo_estimado: int
    questoes: List[QuestionResponse] = []
    live_phase: str = "lobby"
    current_question_id: Optional[str] = None
    question_started_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    created_at: datetime


class QuizGenerateResponse(BaseModel):
    """Resultado da geracao automatica de quiz a partir da transcricao."""
    quiz_id: str
    titulo: str
    questoes: List[QuestionResponse]
    tempo_estimado_resposta: int
    status: str = "draft"
    message: str = ""


class StudentAnswerRequest(BaseModel):
    """Resposta de um aluno a uma questao durante o quiz."""
    question_id: str
    resposta: Optional[str] = None
    tempo_resposta: Optional[int] = None


class StudentAnswerResponse(BaseModel):
    """Resposta do aluno, com acerto e tempo gasto."""
    id: str
    question_id: str
    resposta: Optional[str]
    correta: Optional[bool]
    tempo_resposta: Optional[int]
    pontuacao: int = 0
    respondido_em: datetime
