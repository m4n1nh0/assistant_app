import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from starlette.requests import Request

from app.routers import attendance
from app.main import _safe_request_path


def run(coro):
    return asyncio.run(coro)


class _Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


class QueryDb:
    def __init__(self, *results):
        self.results = list(results)
        self.queries = []
        self.added = []
        self.commits = 0

    async def execute(self, query):
        self.queries.append(query)
        return _Result(self.results.pop(0) if self.results else [])

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _item):
        return None


def _session(**changes):
    values = {
        "id": "attendance-1",
        "closed_at": None,
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def _request(accept_language=""):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/education/attendance/check-in/token",
            "query_string": b"",
            "headers": [(b"accept-language", accept_language.encode("ascii"))],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
        }
    )


def test_dynamic_token_is_hashed_before_storage_or_lookup():
    token = "temporary-secret-token"

    assert attendance._token_hash(token) != token
    assert len(attendance._token_hash(token)) == 64
    assert attendance._token_hash(token) == attendance._token_hash(token)
    assert _safe_request_path(f"/education/attendance/check-in/{token}").endswith(
        "/[token]"
    )
    assert token not in _safe_request_path(
        f"/education/attendance/check-in/{token}"
    )


def test_session_closes_by_expiration_or_explicit_close():
    assert attendance._session_is_open(_session()) is True
    assert attendance._session_is_open(
        _session(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    ) is False
    assert attendance._session_is_open(
        _session(closed_at=datetime.now(timezone.utc))
    ) is False


def test_public_page_escapes_content_and_never_echoes_html():
    response = attendance._check_in_page(
        title="<script>alert(1)</script>",
        message="Turma <b>teste</b>",
        language="pt",
        open_for_check_in=True,
    )
    html = response.body.decode("utf-8")

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "Turma &lt;b&gt;teste&lt;/b&gt;" in html


def test_public_language_follows_browser_and_explicit_selection():
    request = _request("fr-FR;q=0.9, es-ES;q=0.8, en;q=0.7")

    assert attendance._public_language(request) == "es"
    assert attendance._public_language(request, "en-US") == "en"
    assert attendance._public_language(_request("de-DE")) == "pt"


def test_public_page_renders_spanish_and_keeps_all_language_choices():
    response = attendance._check_in_page(
        title="Confirmar asistencia",
        message="Ingrese su matrícula.",
        language="es",
        open_for_check_in=True,
    )
    html = response.body.decode("utf-8")

    assert '<html lang="es">' in html
    assert "CONFIRMAR ASISTENCIA" in html
    assert "Ingrese su matrícula" in html
    assert '?lang=pt' in html
    assert '?lang=es' in html
    assert '?lang=en' in html
    assert 'action="?lang=es"' in html
    assert response.headers["content-language"] == "es"
    assert response.headers["cache-control"] == "no-store"


def test_public_page_renders_english_privacy_and_form_labels():
    response = attendance._check_in_page(
        title="Confirm attendance",
        message="Enter your student ID.",
        language="en",
        open_for_check_in=True,
    )
    html = response.body.decode("utf-8")

    assert '<html lang="en">' in html
    assert "Student ID" in html
    assert "CONFIRM ATTENDANCE" in html
    assert "used only to confirm attendance" in html


def test_duplicate_check_in_is_idempotent():
    roster = SimpleNamespace(
        student_id="student-1",
        enrollment="2026001",
        student_name="Ana",
    )
    existing = SimpleNamespace(id="record-1", student_id="student-1")
    db = QueryDb([roster], [existing])

    record, created = run(
        attendance._register_attendance(
            _session(),
            "2026001",
            "qr",
            db,
        )
    )

    assert record is existing
    assert created is False
    assert db.added == []
    assert db.commits == 0


def test_attendance_list_is_scoped_to_authenticated_tutor():
    db = QueryDb([])

    assert run(
        attendance.list_attendance_sessions(
            user={"tutor_id": "tutor-1"},
            db=db,
        )
    ) == []

    sql = str(db.queries[0].compile(compile_kwargs={"literal_binds": True}))
    assert "attendance_sessions.tutor_id = 'tutor-1'" in sql


def test_record_table_prevents_duplicate_student_in_the_same_session():
    constraints = {
        constraint.name
        for constraint in attendance.AttendanceRecordModel.__table__.constraints
    }

    assert "uq_attendance_record_session_student" in constraints
