from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal, Union
from datetime import date, datetime
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
    action: Optional[Union["LaunchAction", "ShortcutRegistrationAction", "ComputerAction", "CodingAction", "CalendarCreateAction", "EducationOpenAction"]] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    registration_token: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordRecoveryRequest(BaseModel):
    identifier: str = Field(max_length=255)


class PasswordRecoveryConfirmRequest(BaseModel):
    token: str = Field(max_length=512)
    new_password: str = Field(max_length=1024)


class PublicMessageResponse(BaseModel):
    success: bool = True
    message: str


class AuthResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    message: str = ""
    expires_in: int = 86400


class AuthStatusResponse(BaseModel):
    needs_setup: bool
    invite_registration_enabled: bool = True
    registration_requires_token: bool = False
    registration_delivery_configured: bool = False
    admin_email_hint: Optional[str] = None


class RegistrationTokenResponse(BaseModel):
    success: bool
    message: str
    admin_email_hint: Optional[str] = None


class AdminInviteRequest(BaseModel):
    email: str


class AdminInviteResponse(BaseModel):
    success: bool
    message: str
    email_hint: str
    expires_at: datetime


class AdminUserResponse(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    role: str
    tutor_id: Optional[str] = None
    is_active: bool
    created_at: datetime


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
    reminder_minutes: int = Field(default=15, ge=5, le=1440)
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
    assistant_name: str = "Assistant"
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


class CalendarEventCreateRequest(BaseModel):
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
    provider: Literal["google", "microsoft"]
    account_id: str = Field(min_length=1, max_length=120)
    class_ids: List[str] = Field(min_length=1, max_length=100)
    date_from: date
    date_to: date
    timezone: str = Field(default="America/Sao_Paulo", min_length=1, max_length=80)
    confirmed: bool = False


class ClassAgendaCreateResponse(BaseModel):
    class_count: int = 0
    created_series: int = 0
    skipped_series: int = 0
    failed_series: int = 0
    errors: List[str] = Field(default_factory=list)


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
    assistant_name: str = "Assistant"
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


class CalendarCreateAction(BaseModel):
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
    type: Literal["education_open"] = "education_open"
    destination: Literal["lesson", "attendance"] = "lesson"
    reason: str = ""
    requires_confirmation: bool = True


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


# --- Modo educacao --------------------------------------------------------


class StudentCreate(BaseModel):
    name: str
    class_id: Optional[str] = None
    class_group: str = ""
    discipline: str = ""
    external_id: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    active: bool = True


class StudentUpdate(BaseModel):
    name: Optional[str] = None
    class_id: Optional[str] = None
    class_group: Optional[str] = None
    discipline: Optional[str] = None
    external_id: Optional[str] = None
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None
    active: Optional[bool] = None


class StudentResponse(BaseModel):
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
    enrollment: str
    name: str


class StudentImportRequest(BaseModel):
    class_id: Optional[str] = None
    class_group: str = ""
    discipline: str = ""
    students: List[StudentImportItem] = Field(min_length=1, max_length=1000)


class StudentImportResponse(BaseModel):
    created: int
    updated: int
    total: int


class StudentBulkDeleteRequest(BaseModel):
    class_id: str
    student_ids: List[str] = Field(min_length=1, max_length=1000)


class StudentBulkDeleteResponse(BaseModel):
    requested: int
    deleted: int


class AttendanceSessionCreate(BaseModel):
    # `class_id` mantem clientes antigos; novos clientes enviam `class_ids`.
    class_id: Optional[str] = None
    class_ids: List[str] = Field(default_factory=list, max_length=20)
    attendance_date: Optional[str] = None
    duration_minutes: int = Field(default=15, ge=1, le=180)
    title: str = Field(default="", max_length=255)
    lesson_id: Optional[str] = None


class AttendanceRecordCreate(BaseModel):
    enrollment: str = Field(min_length=1, max_length=80)


class AttendanceRecordResponse(BaseModel):
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
    student_id: str
    enrollment: str
    student_name: str
    class_id: str = ""
    class_label: str = ""
    discipline: str = ""


class AttendanceClassResponse(BaseModel):
    class_id: str
    class_label: str
    discipline: str = ""
    semester: str = ""
    expected_count: int = 0


class AttendanceSessionResponse(BaseModel):
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
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    class_id: Optional[str] = None
    session_count: int = 0
    expected_total: int = 0
    present_total: int = 0
    sessions: List[AttendanceSessionResponse] = Field(default_factory=list)


class LessonCreate(BaseModel):
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
    code: str = ""
    name: str = ""
    semester: str = ""


class DisciplineUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    semester: Optional[str] = None
    active: Optional[bool] = None


class DisciplineResponse(BaseModel):
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
    code: str = ""
    name: str = ""
    discipline_id: Optional[str] = None
    discipline: str = ""
    schedules: List[ClassScheduleItem] = Field(default_factory=list)


class ClassGroupUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    discipline_id: Optional[str] = None
    discipline: Optional[str] = None
    active: Optional[bool] = None
    schedules: Optional[List[ClassScheduleItem]] = None


class ClassGroupResponse(BaseModel):
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
    discipline: Optional[str] = None
    title: Optional[str] = None
    class_group: Optional[str] = None
    class_ids: Optional[List[str]] = None
    teacher: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class LessonSegmentResponse(BaseModel):
    id: str
    lesson_id: str
    sequence: int
    text: str
    confidence: float
    duration_ms: int
    indexed: bool
    created_at: datetime


class LessonSegmentUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class SemesterUpdate(BaseModel):
    active: bool


class SemesterResponse(BaseModel):
    code: str
    active: bool
    discipline_count: int = 0
    class_count: int = 0


class LessonPointResponse(BaseModel):
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
    student_name: str
    points: float
    reason: Optional[str] = None
    student_id: Optional[str] = None


class LessonResponse(BaseModel):
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
    segment_count: int = 0
    transcript_chars: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LessonDetailResponse(LessonResponse):
    segments: List[LessonSegmentResponse] = Field(default_factory=list)
    points: List[LessonPointResponse] = Field(default_factory=list)


class LessonSegmentIngestRequest(BaseModel):
    """Ingestao de um bloco ja transcrito pelo cliente."""
    text: str
    confidence: float = 1.0
    duration_ms: int = 0
    extract_points: bool = True


class LessonSegmentIngestResponse(BaseModel):
    segment: Optional[LessonSegmentResponse] = None
    indexed: bool = False
    skipped_reason: Optional[str] = None
    points: List[LessonPointResponse] = Field(default_factory=list)
    lesson: LessonResponse


class LessonSummaryRequest(BaseModel):
    llm: Optional[str] = None
    focus: str = ""
    close_lesson: bool = False


class LessonSummaryResponse(BaseModel):
    lesson_id: str
    summary: str
    llm: str
    generated_at: datetime
    used_segments: int
    points: List[LessonPointResponse] = Field(default_factory=list)


class LessonSearchResult(BaseModel):
    id: str
    score: float
    lesson_id: str
    discipline: str
    lesson_date: str
    sequence: int
    content: str


class PointsReportEntry(BaseModel):
    student_name: str
    student_id: Optional[str] = None
    total_points: float
    discipline: str
    class_group: str = ""
    lesson_date: str
    entries: List[LessonPointResponse] = Field(default_factory=list)


class PointsReportResponse(BaseModel):
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    discipline: Optional[str] = None
    class_group: Optional[str] = None
    total_points: float = 0.0
    students: List[PointsReportEntry] = Field(default_factory=list)


class EmbeddingStatusResponse(BaseModel):
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
    lesson_id: Optional[str] = None
    # Regrava tambem o que ja tem vetor - usado ao trocar de modelo.
    force: bool = False
    limit: int = Field(default=600, ge=1, le=5000)


class LessonReindexResponse(BaseModel):
    indexed: int = 0
    failed: int = 0
    pending: int = 0
    embedding: str = ""
    error: Optional[str] = None
