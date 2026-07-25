from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal, Union
from datetime import datetime
from enum import Enum


class LLMEnum(str, Enum):
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
    single = "single"
    multi  = "multi"
    chain  = "chain"


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[Message] = Field(default_factory=list)
    llm: Optional[LLMEnum] = None
    mode: ResponseModeEnum = ResponseModeEnum.single
    session_id: str = "default"
    stream: bool = False


class LLMResponse(BaseModel):
    llm: str
    content: str
    is_error: bool = False
    duration_ms: int = 0
    tokens_used: Optional[int] = None


class ChatResponse(BaseModel):
    session_id: str
    mode: str
    responses: List[LLMResponse]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    action: Optional[Union["LaunchAction", "ShortcutRegistrationAction", "ComputerAction", "CodingAction"]] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AuthResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    message: str = ""
    expires_in: int = 86400


class AuthStatusResponse(BaseModel):
    needs_setup: bool


class LLMConfig(BaseModel):
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
    pin_hash: str = ""
    voice_passphrase: str = ""
    face_enabled: bool = False
    pin_enabled: bool = False
    voice_enabled: bool = False


class NotifConfig(BaseModel):
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_enabled: bool = False
    wa_provider: str = "callmebot"
    wa_number: str = ""
    wa_token: str = ""
    wa_sid: str = ""
    wa_enabled: bool = False
    notify_15min: bool = True
    notify_on_time: bool = True
    fallback_enabled: bool = True
    include_link: bool = True


class CalendarConfig(BaseModel):
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
    f = "f"
    m = "m"


class AssistantConfig(BaseModel):
    assistant_name: str = "Assistente"
    gender: GenderEnum = GenderEnum.f
    user_name: str = ""
    personality: str = ""
    language: str = "pt-BR"
    response_mode: ResponseModeEnum = ResponseModeEnum.single
    tts_enabled: bool = True


class FullConfig(BaseModel):
    assistant: AssistantConfig = Field(default_factory=AssistantConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    notif: NotifConfig = Field(default_factory=NotifConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)


class CalendarEvent(BaseModel):
    id: str
    title: str
    start_time: datetime
    end_time: Optional[datetime] = None
    source: Literal["google", "teams", "outlook"]
    meeting_url: Optional[str] = None
    description: Optional[str] = None
    notified_15: bool = False
    notified_0:  bool = False


class EventsResponse(BaseModel):
    events: List[CalendarEvent]
    total: int
    synced_at: datetime = Field(default_factory=datetime.utcnow)


class NotifRequest(BaseModel):
    message: str
    event_id: Optional[str] = None
    channels: List[Literal["telegram", "whatsapp"]] = ["telegram", "whatsapp"]


class NotifResult(BaseModel):
    telegram_ok: bool = False
    whatsapp_ok: bool = False
    telegram_error: Optional[str] = None
    whatsapp_error: Optional[str] = None

    @property
    def any_ok(self) -> bool:
        return self.telegram_ok or self.whatsapp_ok


class TTSRequest(BaseModel):
    text: str
    language: str = "pt-BR"
    speed: float = 1.0


class STTResponse(BaseModel):
    transcript: str
    confidence: float = 1.0
    language: str = ""


class WSMessage(BaseModel):
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    session_id: str = "default"


class WSChatPayload(BaseModel):
    message: str
    mode: ResponseModeEnum = ResponseModeEnum.single
    llm: Optional[str] = None
    stream: bool = True


class LLMStatus(BaseModel):
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


class HealthResponse(BaseModel):
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
    platform: str
    supported: bool
    active_window_id: Optional[str] = None
    windows: List[DesktopWindowInfo] = Field(default_factory=list)


class DesktopWindowContextResponse(BaseModel):
    window: DesktopWindowInfo
    text: str = ""
    extraction_method: str = "metadata"
    warning: Optional[str] = None
    truncated: bool = False
    context_prompt: str = ""


class ComputerActionInfo(BaseModel):
    id: str
    name: str
    description: str = ""
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_confirmation: bool = False


class ComputerActionRunRequest(BaseModel):
    tutor_id: str = "default"
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ComputerActionCommandOutput(BaseModel):
    label: str
    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0


class ComputerActionRunResponse(BaseModel):
    action: ComputerActionInfo
    status: Literal["executed", "failed"]
    summary: str = ""
    outputs: List[ComputerActionCommandOutput] = Field(default_factory=list)
    duration_ms: int = 0


class ScriptShell(str, Enum):
    powershell = "powershell"
    pwsh = "pwsh"
    cmd = "cmd"
    bash = "bash"
    sh = "sh"
    zsh = "zsh"


class ScriptShellsResponse(BaseModel):
    default_shell: str
    available_shells: List[str] = Field(default_factory=list)


class ScriptSnippetCreate(BaseModel):
    tutor_id: str = "default"
    name: str
    shell: ScriptShell
    script: str
    working_directory: Optional[str] = None
    timeout_seconds: int = Field(default=30, ge=1, le=180)
    allow_high_risk: bool = False
    description: Optional[str] = None


class ScriptSnippetUpdate(BaseModel):
    name: Optional[str] = None
    shell: Optional[ScriptShell] = None
    script: Optional[str] = None
    working_directory: Optional[str] = None
    timeout_seconds: Optional[int] = Field(default=None, ge=1, le=180)
    allow_high_risk: Optional[bool] = None
    description: Optional[str] = None


class ScriptSnippetResponse(BaseModel):
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
    id: Optional[str] = None
    display_name: str
    email: Optional[str] = None
    timezone: str = "America/Sao_Paulo"
    locale: str = "pt-BR"
    notes: str = ""
    assistant_name: str = "Assistente"
    gender: GenderEnum = GenderEnum.f
    personality: str = ""
    response_mode: ResponseModeEnum = ResponseModeEnum.single
    tts_enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)


class TutorProfileResponse(BaseModel):
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
    key: str
    value: Dict[str, Any] = Field(default_factory=dict)
    scope: str = "general"


class TutorSettingResponse(BaseModel):
    id: str
    tutor_id: str
    key: str
    value: Dict[str, Any] = Field(default_factory=dict)
    scope: str


class MemoryReviewCreate(BaseModel):
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
    reviewer_note: str = ""


class MemoryVoiceDecisionRequest(BaseModel):
    transcript: str
    reviewer_note: str = ""


class MemoryVoiceDecisionResponse(BaseModel):
    decision: Literal["approved", "rejected", "unclear"]
    message: str
    memory: MemoryReviewResponse


class MemorySearchResponse(BaseModel):
    id: str
    score: float
    category: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AutomationApproveRequest(BaseModel):
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
    enabled: Optional[bool] = None
    schedule: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class ShortcutType(str, Enum):
    app = "app"
    url = "url"
    command = "command"


class ShortcutCreate(BaseModel):
    tutor_id: str
    name: str
    type: ShortcutType
    target: str
    aliases: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class ShortcutUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[ShortcutType] = None
    target: Optional[str] = None
    aliases: Optional[List[str]] = None
    description: Optional[str] = None


class ShortcutResponse(BaseModel):
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
    status: Literal["executed", "failed"] = "executed"
    source: str = "interface"
    platform: Optional[str] = None
    request: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class ShortcutLaunchResponse(BaseModel):
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
    type: Literal["launch", "open_project"] = "launch"
    shortcut_id: str
    name: str
    target: str
    target_type: ShortcutType
    browser: str = ""


class ShortcutRegistrationAction(BaseModel):
    type: Literal["register_shortcut"] = "register_shortcut"
    name: str
    query: str = ""
    target: str = ""
    target_type: ShortcutType = ShortcutType.app
    aliases: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    open_after_register: bool = False


class ComputerAction(BaseModel):
    type: Literal["computer_action"] = "computer_action"
    action_id: str
    name: str
    description: str = ""
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_confirmation: bool = False
    arguments: Dict[str, Any] = Field(default_factory=dict)


class CodingAction(BaseModel):
    type: Literal["coding_action"] = "coding_action"
    action_id: str
    name: str
    description: str = ""
    risk_level: Literal["low", "medium", "high"] = "low"
    requires_confirmation: bool = True
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ActionAuditRequest(BaseModel):
    tutor_id: str
    automation_id: Optional[str] = None
    action_type: str
    status: Literal["planned", "executed", "failed", "skipped"]
    request: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)


class ActionAuditResponse(BaseModel):
    id: str
    tutor_id: str
    automation_id: Optional[str] = None
    action_type: str
    status: str
    request: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
