# Integração com Sistema Acadêmico via Scraping

## Overview

Integração com sistemas acadêmicos institucionais (SIGAA, Moodle, Blackboard, etc.) via scraping para sincronizar presença, notas e calendários automaticamente.

**Status:** Parcialmente aplicado para SIA/Estácio - base operacional concluída
**Prioridade:** Alta (Modo Educação)  
**Complexidade:** Alta

## Status de Implementação

**Aplicado em:** 2026-08-25

- [x] Integração específica com SIA/Estácio em `/education/sia`.
- [x] Leitura de telas do SIA por WebView autenticado na interface, contornando o Akamai Bot Manager sem tentar automatizar login server-side.
- [x] Backend faz parse de sessão, períodos, turmas e pauta a partir do HTML recebido da interface.
- [x] Fallback server-side com cookies preservado, mas documentado como sujeito a bloqueio do bot manager.
- [x] Aba/histórico permite abrir `SiaAttendanceImporter` para espelhar a chamada do INTARQ na Pauta Eletrônica.
- [x] Endpoint `/education/sia/lesson/{ref_id}/attendance` reúne presença por chamada ou por aula.
- [x] Suporte a aula com múltiplas turmas, filtrando alunos pela turma da pauta aberta.
- [x] Confirmação de lançamento no SIA marca a chamada como sincronizada (`external_synced_at`, `external_system`, `external_detail`).
- [x] Importação/parse de pauta do SIA para uso no modo educação.

**Ainda roadmap:**

- [ ] Adapter genérico multi-sistema para SIGAA, Moodle, Blackboard e Canvas.
- [ ] Configuração persistente de credenciais por sistema acadêmico.
- [ ] Sync engine batch para presença em período.
- [ ] Mapeamento persistente `INTARQ -> sistema acadêmico` com aprovação manual.
- [ ] Sincronização de notas e calendários.
- [ ] Logs/auditoria genéricos para sync multi-sistema.

> Nota: o fluxo aplicado hoje é SIA/Estácio primeiro, com o navegador embutido operando a pauta real. Os exemplos abaixo de `SIGAAAdapter`, `MoodleAdapter` e `SyncEngine` permanecem como desenho de roadmap para uma camada multi-sistema.

---

## Motivação

Atualmente, após gerar presença automática via QR code no INTARQ:
- 🔴 Professor precisa inserir presença manualmente no sistema acadêmico
- 🔴 Dados de alunos vêm de fonte separada
- 🔴 Calendários não sincronizam

**Problema:** Duplicação de trabalho, inconsistência de dados

**Solução:** Scraping automatizado que:
- ✅ Sincroniza presença INTARQ → Sistema acadêmico
- ✅ Importa lista de alunos (1x por semestre)
- ✅ Sincroniza calendários e prazos
- ✅ Compatível com múltiplos sistemas

---

## Arquitetura

### Suporte a Sistemas

```
┌──────────────────────────────────────┐
│    INTARQ Attendance/Grade Data      │
└─────────────────┬────────────────────┘
                  │
    ┌─────────────┼─────────────────┬──────────────┐
    ▼             ▼                 ▼              ▼
┌────────┐  ┌───────────┐  ┌──────────────┐  ┌──────┐
│ SIGAA  │  │ Moodle    │  │ Blackboard   │  │ Canvas
│ (UFRN) │  │ (Open LMS)│  │ (Blackboard) │  │ (Inst)
└────────┘  └───────────┘  └──────────────┘  └──────┘
    │             │                 │              │
    └─────────────┼─────────────────┼──────────────┘
                  │
          [Sync Engine]
          - Error handling
          - Retry logic
          - Audit logs
          - Webhooks
```

### Data Flow

**Fluxo aplicado hoje (SIA/Estácio):**

```
┌──────────────────────────┐
│  QR Attendance (INTARQ)  │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ SiaAttendanceImporter    │
│ WebView autenticado      │
└────────────┬─────────────┘
             │ HTML / DOM da pauta
             ▼
┌──────────────────────────┐
│ /education/sia/parse_*   │
│ Backend extrai dados     │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Comparação INTARQ x SIA  │
│ por matrícula e turma    │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ Aplicação na pauta SIA   │
│ via DOM do WebView       │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ /education/sia/mark-synced │
│ Marca chamada lançada    │
└──────────────────────────┘
```

**Fluxo multi-sistema planejado:**

```
┌──────────────────────────┐
│  QR Attendance (INTARQ)  │  ← Professor escaneia QR na aula
└────────────┬─────────────┘
             │
             ▼
    ┌────────────────────┐
    │ Format Attendance  │
    │ - Student ID       │
    │ - Course ID        │
    │ - Date/Time        │
    │ - Status (present) │
    └────────┬───────────┘
             │
             ▼
    ┌────────────────────┐
    │ Detect System      │
    │ Type & Credentials │
    └────────┬───────────┘
             │
             ▼
    ┌────────────────────────────┐
    │ Adapter Pattern            │
    │ - SIGAAAdapter             │
    │ - MoodleAdapter            │
    │ - BlackboardAdapter        │
    └────────┬───────────────────┘
             │
             ▼
    ┌────────────────────┐
    │ Upload Attendance  │
    │ (Scraping/API)     │
    └────────┬───────────┘
             │
             ▼
    ┌──────────────────┐
    │ Log & Alert      │
    │ Success/Failure  │
    └──────────────────┘
```

---

## Componentes

### 1. Adapter Pattern (Multi-Sistema)

```python
from abc import ABC, abstractmethod

class AcademicSystemAdapter(ABC):
    """Interface para diferentes sistemas acadêmicos"""
    
    @abstractmethod
    async def authenticate(self, credentials: dict) -> bool:
        """Autentica no sistema"""
        pass
    
    @abstractmethod
    async def get_courses(self) -> List[Course]:
        """Busca cursos do professor"""
        pass
    
    @abstractmethod
    async def get_students(self, course_id: str) -> List[Student]:
        """Busca lista de alunos de um curso"""
        pass
    
    @abstractmethod
    async def upload_attendance(
        self,
        course_id: str,
        attendance_data: List[dict]
    ) -> UploadResult:
        """Envia presença para o sistema"""
        pass
    
    @abstractmethod
    async def get_calendar_events(self) -> List[CalendarEvent]:
        """Busca eventos do calendário"""
        pass
    
    @abstractmethod
    async def upload_grades(
        self,
        course_id: str,
        grades: List[dict]
    ) -> UploadResult:
        """Envia notas (opcional, futuro)"""
        pass
```

### 2. SIGAA Adapter (Brasil - UFRN)

```python
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

class SIGAAAdapter(AcademicSystemAdapter):
    """Adapter para SIGAA (Sistema Integrado de Gestão de Atividades Acadêmicas)"""
    
    def __init__(self, base_url: str = "https://sigaa.ufrn.br"):
        self.base_url = base_url
        self.session = None
        self.driver = None
    
    async def authenticate(self, credentials: dict) -> bool:
        """Autentica via Selenium (SIGAA usa JavaScript)"""
        
        try:
            self.driver = webdriver.Chrome()
            self.driver.get(f"{self.base_url}/sigaa/")
            
            # Aguarda carregamento
            wait = WebDriverWait(self.driver, 10)
            
            # Preenche login
            login_field = wait.until(
                lambda d: d.find_element(By.ID, "username")
            )
            login_field.send_keys(credentials["username"])
            
            # Preenche senha
            password_field = self.driver.find_element(By.ID, "password")
            password_field.send_keys(credentials["password"])
            
            # Clica submit
            submit_button = self.driver.find_element(By.ID, "submit")
            submit_button.click()
            
            # Aguarda redirect pós-login
            await asyncio.sleep(3)
            
            # Verifica se logado com sucesso
            is_authenticated = "Você já está logado" not in self.driver.page_source
            return is_authenticated
            
        except Exception as e:
            print(f"SIGAA auth failed: {e}")
            return False
    
    async def get_courses(self) -> List[dict]:
        """Busca disciplinas do professor"""
        
        # Navega para página de turmas
        self.driver.get(f"{self.base_url}/sigaa/verTurma")
        await asyncio.sleep(2)
        
        # Extrai tabela de turmas
        courses = []
        
        rows = self.driver.find_elements(
            By.CSS_SELECTOR,
            "table.turmas tbody tr"
        )
        
        for row in rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) >= 3:
                courses.append({
                    "id": cells[0].text,
                    "name": cells[1].text,
                    "semester": cells[2].text,
                })
        
        return courses
    
    async def get_students(self, course_id: str) -> List[dict]:
        """Busca lista de alunos"""
        
        # Navega para página de turma
        self.driver.get(
            f"{self.base_url}/sigaa/verTurma?id={course_id}"
        )
        await asyncio.sleep(2)
        
        students = []
        
        # Encontra tabela de alunos
        student_rows = self.driver.find_elements(
            By.CSS_SELECTOR,
            "table.alunos tbody tr"
        )
        
        for row in student_rows:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) >= 2:
                students.append({
                    "sigaa_id": cells[0].text,  # Matrícula
                    "name": cells[1].text,
                    "email": cells[2].text if len(cells) > 2 else None,
                })
        
        return students
    
    async def upload_attendance(
        self,
        course_id: str,
        attendance_data: List[dict]
    ) -> dict:
        """Envia presença para SIGAA"""
        
        try:
            # Navega para página de frequência
            self.driver.get(
                f"{self.base_url}/sigaa/verTurma/"
                f"registrarFrequencia?turmaId={course_id}"
            )
            await asyncio.sleep(2)
            
            # Para cada aluno presente
            for attendance in attendance_data:
                # Localiza checkbox de presença
                checkbox = self.driver.find_element(
                    By.ID,
                    f"presente_{attendance['student_id']}"
                )
                
                # Marca como presente se necessário
                if attendance["status"] == "present" and not checkbox.is_selected():
                    checkbox.click()
            
            # Salva
            save_button = self.driver.find_element(
                By.ID,
                "salvar-frequencia"
            )
            save_button.click()
            
            await asyncio.sleep(2)
            
            # Verifica sucesso
            success = "Frequência registrada" in self.driver.page_source
            
            return {
                "success": success,
                "uploaded_count": len(attendance_data),
                "timestamp": datetime.now()
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now()
            }
```

### 3. Moodle Adapter (Open LMS)

```python
class MoodleAdapter(AcademicSystemAdapter):
    """Adapter para Moodle (via API REST)"""
    
    def __init__(self, base_url: str, api_token: str):
        self.base_url = base_url
        self.api_token = api_token
        self.session = aiohttp.ClientSession()
    
    async def authenticate(self, credentials: dict) -> bool:
        """Testa autenticação da API"""
        
        # Moodle usa tokens em vez de user/pass
        try:
            async with self.session.get(
                f"{self.base_url}/webservice/rest/server.php",
                params={
                    "wstoken": self.api_token,
                    "wsfunction": "core_course_get_courses",
                    "moodlewsrestformat": "json"
                }
            ) as resp:
                return resp.status == 200
        except:
            return False
    
    async def get_courses(self) -> List[dict]:
        """Busca cursos via API"""
        
        async with self.session.get(
            f"{self.base_url}/webservice/rest/server.php",
            params={
                "wstoken": self.api_token,
                "wsfunction": "core_enrol_get_enrolled_users",
                "moodlewsrestformat": "json"
            }
        ) as resp:
            data = await resp.json()
            # Moodle retorna dados estruturados
            return data.get("courses", [])
    
    async def get_students(self, course_id: str) -> List[dict]:
        """Busca alunos de um curso"""
        
        async with self.session.get(
            f"{self.base_url}/webservice/rest/server.php",
            params={
                "wstoken": self.api_token,
                "wsfunction": "core_enrol_get_enrolled_users",
                "courseid": course_id,
                "moodlewsrestformat": "json"
            }
        ) as resp:
            users = await resp.json()
            return [
                {
                    "moodle_id": u["id"],
                    "name": u["fullname"],
                    "email": u.get("email")
                }
                for u in users
            ]
    
    async def upload_attendance(
        self,
        course_id: str,
        attendance_data: List[dict]
    ) -> dict:
        """Registra presença via Attendance plugin"""
        
        try:
            # Moodle Attendance é um plugin separado
            # Requer função webservice customizada
            
            # Prepara dados
            params = {
                "wstoken": self.api_token,
                "wsfunction": "mod_attendance_add_attendance",
                "courseid": course_id,
                "moodlewsrestformat": "json"
            }
            
            # Adiciona cada entrada de presença
            for idx, att in enumerate(attendance_data):
                params[f"sessions[{idx}][userid]"] = att["student_id"]
                params[f"sessions[{idx}][status]"] = "P"  # P = Present
            
            async with self.session.post(
                f"{self.base_url}/webservice/rest/server.php",
                data=params
            ) as resp:
                result = await resp.json()
                return {
                    "success": not result.get("exception"),
                    "uploaded_count": len(attendance_data)
                }
        except Exception as e:
            return {"success": False, "error": str(e)}
```

### 4. Sync Engine

```python
class SyncEngine:
    """Orquestra sincronização com sistema acadêmico"""
    
    def __init__(self, db, adapter_manager):
        self.db = db
        self.adapters = adapter_manager
    
    async def sync_attendance_batch(
        self,
        tutor_id: str,
        course_id: str,
        start_date: date,
        end_date: date
    ) -> SyncResult:
        """Sincroniza presença de um período"""
        
        # 1. Busca config de sistema acadêmico
        config = await self.db.get_academic_system_config(tutor_id)
        
        if not config or not config.get("enabled"):
            return SyncResult(
                success=False,
                error="Academic system not configured"
            )
        
        # 2. Instancia adapter apropriado
        adapter = await self.adapters.get_adapter(
            system_type=config["system_type"],
            credentials=config["credentials"]
        )
        
        # 3. Busca presença do INTARQ neste período
        intarq_attendance = await self.db.get_attendance_records(
            course_id=course_id,
            start_date=start_date,
            end_date=end_date
        )
        
        # 4. Agrupa por aluno
        grouped = self._group_by_student(intarq_attendance)
        
        # 5. Mapeia IDs de INTARQ → sistema acadêmico
        mapped = await self._map_student_ids(
            grouped,
            tutor_id=tutor_id,
            adapter=adapter
        )
        
        # 6. Envia para sistema acadêmico
        result = await adapter.upload_attendance(
            course_id=config["academic_course_id"],
            attendance_data=mapped
        )
        
        # 7. Log & Audit
        await self.db.log_sync(
            tutor_id=tutor_id,
            sync_type="attendance",
            status=result["success"],
            records_count=len(mapped),
            details=result
        )
        
        return result
    
    async def _map_student_ids(
        self,
        intarq_students: dict,
        tutor_id: str,
        adapter: AcademicSystemAdapter
    ) -> List[dict]:
        """Mapeia IDs de alunos entre sistemas"""
        
        # Busca mapping existente no banco
        id_mapping = await self.db.get_student_id_mapping(tutor_id)
        
        # Para alunos sem mapping, tenta match automático
        missing_ids = [
            sid for sid in intarq_students.keys()
            if sid not in id_mapping
        ]
        
        if missing_ids:
            # Auto-match baseado em nome/email
            auto_mapped = await self._auto_match_students(
                intarq_students=intarq_students,
                missing_ids=missing_ids,
                adapter=adapter
            )
            id_mapping.update(auto_mapped)
        
        # Converte para formato do sistema acadêmico
        mapped = []
        for intarq_id, attendance_records in intarq_students.items():
            academic_id = id_mapping.get(intarq_id)
            
            if academic_id:
                for record in attendance_records:
                    mapped.append({
                        "student_id": academic_id,
                        "status": "present",
                        "date": record["date"]
                    })
        
        return mapped
```

### 5. Database Schema

```sql
CREATE TABLE academic_system_configs (
    id VARCHAR(36) PRIMARY KEY,
    tutor_id VARCHAR(36) NOT NULL,
    system_type ENUM('sigaa', 'moodle', 'blackboard', 'canvas'),
    base_url VARCHAR(255),
    credentials_encrypted TEXT,  -- Encrypted JSON
    enabled BOOLEAN DEFAULT FALSE,
    last_sync_at TIMESTAMP,
    sync_status ENUM('idle', 'syncing', 'error'),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE KEY uq_tutor_system (tutor_id, system_type),
    FOREIGN KEY (tutor_id) REFERENCES tutors(id)
);

CREATE TABLE student_id_mapping (
    id VARCHAR(36) PRIMARY KEY,
    tutor_id VARCHAR(36) NOT NULL,
    intarq_student_id VARCHAR(36),
    academic_system_id VARCHAR(100),
    academic_system_type ENUM('sigaa', 'moodle', 'blackboard', 'canvas'),
    student_name VARCHAR(255),
    student_email VARCHAR(255),
    confidence_score FLOAT,  -- Auto-match confidence
    created_at TIMESTAMP,
    UNIQUE KEY uq_mapping (tutor_id, intarq_student_id, academic_system_type),
    FOREIGN KEY (tutor_id) REFERENCES tutors(id)
);

CREATE TABLE sync_logs (
    id VARCHAR(36) PRIMARY KEY,
    tutor_id VARCHAR(36) NOT NULL,
    sync_type ENUM('attendance', 'grades', 'calendar'),
    system_type VARCHAR(50),
    status ENUM('success', 'partial', 'failed'),
    records_attempted INT,
    records_succeeded INT,
    records_failed INT,
    error_message TEXT,
    sync_started_at TIMESTAMP,
    sync_completed_at TIMESTAMP,
    FOREIGN KEY (tutor_id) REFERENCES tutors(id)
);
```

---

## API Endpoints

```python
@router.post("/api/academic-system/configure")
async def configure_academic_system(
    tutor_id: str,
    system_type: str,
    config: dict
):
    """Configura integração com sistema acadêmico"""
    # Valida credenciais
    # Encripta e armazena
    # Retorna status

@router.post("/api/academic-system/sync-attendance")
async def trigger_sync_attendance(
    tutor_id: str,
    course_id: str,
    start_date: date,
    end_date: date
):
    """Dispara sincronização de presença"""
    # Valida config
    # Executa sync
    # Retorna resultado

@router.get("/api/academic-system/sync-logs")
async def get_sync_logs(tutor_id: str, limit: int = 50):
    """Histórico de sincronizações"""
    # Retorna últimas N sincronizações
    # Mostra sucesso/erro

@router.post("/api/academic-system/auto-match-students")
async def trigger_auto_match(tutor_id: str, course_id: str):
    """Tenta fazer match automático de alunos"""
    # Compara nomes/emails
    # Sugere mapeamento
    # Professor aprova
```

---

## Security & Privacy

- ✅ Credenciais armazenadas encrypted
- ✅ API tokens rotacionados periodicamente
- ✅ Audit logs de todas as sincronizações
- ✅ Apenas professor pode autorizar sync
- ✅ HTTPS only, no credentials in logs

---

## Testing Strategy

- [ ] Unit: Adapter parsing, ID mapping
- [ ] Integration: Mock SIGAA/Moodle servers
- [ ] E2E: Teste com sistemas reais (staging)
- [ ] Regression: Não duplica presença

---

## Timeline

**Week 1:** Adapter pattern + SIGAA adapter  
**Week 2:** Moodle + Blackboard adapters  
**Week 3:** Sync engine + ID mapping  
**Week 4:** Frontend UI + configuration flow  
**Week 5:** Testing, security audit, deployment
