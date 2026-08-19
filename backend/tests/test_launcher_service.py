import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import launcher_service


def run(coro):
    return asyncio.run(coro)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeDb:
    def __init__(self, shortcuts):
        self.shortcuts = shortcuts
        self.execute_calls = 0
        self.added = []
        self.commit_calls = 0

    async def execute(self, _query):
        self.execute_calls += 1
        return FakeResult(self.shortcuts)

    async def get(self, _model, shortcut_id):
        for item in self.shortcuts:
            if item.id == shortcut_id:
                return item
        return None

    def add(self, item):
        self.added.append(item)

    async def commit(self):
        self.commit_calls += 1

    async def refresh(self, _item):
        return None


def shortcut(name, aliases=None, target="C:/app.exe", type_="app", description=None):
    return SimpleNamespace(
        id=f"id-{name}",
        name=name,
        aliases=aliases or [],
        target=target,
        type=type_,
        description=description,
    )


def test_find_shortcut_requires_launch_keyword_before_querying_db():
    db = FakeDb([shortcut("Chrome")])

    result = run(
        launcher_service.find_shortcut_in_message(
            "Chrome e bom para navegar",
            "tutor-1",
            db,
        )
    )

    assert result is None
    assert db.execute_calls == 0


def test_find_shortcut_matches_alias_and_prefers_longest_candidate():
    code = shortcut("Code", aliases=["editor"])
    vscode = shortcut("Visual Studio Code", aliases=["vscode", "code"])
    db = FakeDb([code, vscode])

    result = run(
        launcher_service.find_shortcut_in_message(
            "por favor abra o visual studio code",
            "tutor-1",
            db,
        )
    )

    assert result is vscode
    assert db.execute_calls == 1


def test_find_shortcut_distinguishes_notepad_from_notepad_plus_plus():
    notepad = shortcut("Notepad", aliases=["bloco de notas"])
    notepad_plus = shortcut("Notepad++", aliases=["notepad plus plus"])
    db = FakeDb([notepad, notepad_plus])

    result = run(
        launcher_service.find_shortcut_in_message(
            "abra notepad++",
            "tutor-1",
            db,
        )
    )

    assert result is notepad_plus

    result = run(
        launcher_service.find_shortcut_in_message(
            "abra notepad",
            "tutor-1",
            db,
        )
    )

    assert result is notepad


def test_build_launch_action_preserves_shortcut_payload():
    sc = shortcut(
        "Dashboard",
        target="https://example.test/dashboard",
        type_="url",
    )

    action = launcher_service.build_launch_action(sc)

    assert action.shortcut_id == sc.id
    assert action.name == "Dashboard"
    assert action.target == "https://example.test/dashboard"
    assert action.target_type.value == "url"


def test_build_launch_action_reads_preferred_browser_from_description():
    sc = shortcut(
        "Dashboard",
        target="https://example.test/dashboard",
        type_="url",
        description="Painel principal\n[assistant:url_browser=firefox]",
    )

    action = launcher_service.build_launch_action(sc)

    assert action.browser == "firefox"


def test_build_shortcut_registration_action_for_app_query():
    action = launcher_service.build_shortcut_registration_action(
        "cadastre o Visual Studio Code"
    )

    assert action is not None
    assert action.type == "register_shortcut"
    assert action.name == "Visual Studio Code"
    assert action.query == "Visual Studio Code"
    assert action.target == ""
    assert action.target_type.value == "app"
    assert "visual studio code" in action.aliases


def test_build_shortcut_registration_action_extracts_url_and_name():
    action = launcher_service.build_shortcut_registration_action(
        "registre https://github.com como GitHub"
    )

    assert action is not None
    assert action.name == "GitHub"
    assert action.target == "https://github.com"
    assert action.target_type.value == "url"


def test_asking_for_a_script_is_not_a_shortcut_request():
    # "Crie" sozinho nao e pedido de atalho: o usuario quer o script escrito
    # na resposta, e a frase virava cadastro de atalho com o pedido inteiro
    # no lugar do nome.
    assert launcher_service.build_shortcut_registration_action(
        "Crie um script para backup automatico de arquivos importantes, "
        "multiplataforma."
    ) is None


def test_file_name_in_a_code_request_is_not_a_shortcut_target():
    # `config.json` tem a forma de dominio; so URL escrita por extenso conta
    # como destino de atalho.
    assert launcher_service.build_shortcut_registration_action(
        "crie uma funcao em python que leia config.json"
    ) is None


def test_generic_verb_registers_when_the_message_says_atalho():
    action = launcher_service.build_shortcut_registration_action(
        "Crie um atalho para o Visual Studio Code"
    )

    assert action is not None
    # A palavra "atalho" e consumida como ligacao; o nome comeca depois dela.
    assert action.name == "Visual Studio Code"


def test_generic_verb_registers_when_the_message_says_app():
    action = launcher_service.build_shortcut_registration_action(
        "adicione o app Spotify"
    )

    assert action is not None
    assert action.name == "Spotify"


def test_registration_intent_is_detected_even_with_open_word():
    registration = launcher_service.build_shortcut_registration_action(
        "cadastre o visual studio code para abrir depois"
    )

    assert registration is not None
    assert registration.name == "visual studio code"


def test_record_launch_writes_history_and_updates_success_counter():
    sc = shortcut("Node", target="C:/Program Files/nodejs/node.exe")
    sc.tutor_id = "tutor-1"
    sc.use_count = 2
    sc.last_used_at = None
    db = FakeDb([sc])

    log = run(
        launcher_service.record_launch(
            sc.id,
            db,
            platform="windows",
            request={"message": "abra node"},
        )
    )

    assert log is not None
    assert log.tutor_id == "tutor-1"
    assert log.shortcut_name == "Node"
    assert log.target == "C:/Program Files/nodejs/node.exe"
    assert log.status == "executed"
    assert log.platform == "windows"
    assert sc.use_count == 3
    assert sc.last_used_at is not None
    assert db.added == [log]
    assert db.commit_calls == 1


def test_auto_registration_from_launch_plain_app_name():
    action = launcher_service.build_auto_registration_from_launch(
        "abra o Visual Studio Code"
    )

    assert action is not None
    assert action.type == "register_shortcut"
    assert action.name.lower() == "visual studio code"
    assert action.target == ""
    assert action.target_type.value == "app"
    assert action.open_after_register is True


def test_explicit_registration_does_not_open_immediately():
    action = launcher_service.build_shortcut_registration_action(
        "cadastre o Visual Studio Code"
    )

    assert action is not None
    assert action.open_after_register is False


def test_auto_registration_from_launch_url():
    action = launcher_service.build_auto_registration_from_launch(
        "abre o https://github.com"
    )

    assert action is not None
    assert action.target == "https://github.com"
    assert action.target_type.value == "url"


def test_auto_registration_from_launch_ignores_no_launch_keyword():
    action = launcher_service.build_auto_registration_from_launch(
        "o Chrome e bom para navegar"
    )

    assert action is None


def test_auto_registration_from_launch_ignores_generic_phrases():
    action = launcher_service.build_auto_registration_from_launch(
        "abra uma janela"
    )

    assert action is None


def test_build_project_open_action_for_pycharm_project():
    action = launcher_service.build_project_open_action(
        "abra o projeto assistant_app no pycharm"
    )

    assert action is not None
    assert action.type == "open_project"
    assert action.name == "assistant_app no PyCharm"
    assert action.target_type.value == "command"
    payload = json.loads(action.target)
    assert payload["runner"] == "openProjectInIde"
    assert payload["ide"] == "pycharm"
    assert payload["project_query"] == "assistant_app"


def test_build_project_open_action_ignores_capability_question():
    action = launcher_service.build_project_open_action(
        "consegue abrir algum projeto no pycharm se eu disser o nome?"
    )

    assert action is None


@pytest.mark.parametrize(
    "message",
    [
        "abra o projeto assistant_app no vscode",
        "abra o projeto assistant_app no vs code",
        "abra o projeto assistant_app no visual studio code",
        "abra o projeto assistant_app no code",
    ],
)
def test_build_project_open_action_recognizes_vscode_spellings(message):
    action = launcher_service.build_project_open_action(message)

    assert action is not None
    assert action.name == "assistant_app no VS Code"
    payload = json.loads(action.target)
    assert payload["runner"] == "openProjectInIde"
    assert payload["ide"] == "vscode"
    assert payload["project_query"] == "assistant_app"


def test_build_project_open_action_keeps_ide_mentioned_first():
    action = launcher_service.build_project_open_action(
        "abra o projeto assistant_app no vscode, nao no pycharm"
    )

    assert action is not None
    assert json.loads(action.target)["ide"] == "vscode"


def test_bare_code_word_alone_does_not_trigger_vscode():
    """"code" only means VS Code right after a preposition, otherwise it is prose."""
    action = launcher_service.build_project_open_action(
        "mostrar o code review do projeto assistant_app"
    )

    assert action is None


def test_suggest_launch_command_returns_none_for_empty_name():
    result = run(launcher_service.suggest_launch_command(""))
    assert result is None


def test_suggest_launch_command_finds_where_result(monkeypatch):
    async def fake_where(name):
        if name.lower() in ("notepad", "notepad.exe"):
            return r"C:\Windows\System32\notepad.exe"
        return None

    monkeypatch.setattr(launcher_service, "_where_command", fake_where)
    result = run(launcher_service.suggest_launch_command("notepad"))
    assert result == r"C:\Windows\System32\notepad.exe"


def test_suggest_launch_command_uses_portuguese_alias(monkeypatch):
    async def fake_where(name):
        if name.lower() == "notepad.exe":
            return r"C:\Windows\System32\notepad.exe"
        return None

    monkeypatch.setattr(launcher_service, "_where_command", fake_where)
    monkeypatch.setattr(launcher_service, "_known_windows_path", lambda _name: None)
    monkeypatch.setattr(launcher_service, "_windows_app_path", lambda _name: None)
    result = run(launcher_service.suggest_launch_command("bloco de notas"))
    assert result == r"C:\Windows\System32\notepad.exe"


def test_suggest_launch_command_checks_windows_app_paths(monkeypatch):
    async def fake_where(_name):
        return None

    def fake_app_path(name):
        if name.lower() == "notepad++.exe":
            return r"C:\Program Files\Notepad++\notepad++.exe"
        return None

    monkeypatch.setattr(launcher_service, "_where_command", fake_where)
    monkeypatch.setattr(launcher_service, "_known_windows_path", lambda _name: None)
    monkeypatch.setattr(launcher_service, "_windows_app_path", fake_app_path)
    result = run(launcher_service.suggest_launch_command("notepad++"))
    assert result == r"C:\Program Files\Notepad++\notepad++.exe"


def test_suggest_launch_command_falls_back_to_llm_when_where_fails(monkeypatch):
    async def fake_where(_name):
        return None

    async def fake_llm(_name):
        return "code.exe"

    monkeypatch.setattr(launcher_service, "_where_command", fake_where)
    monkeypatch.setattr(launcher_service, "_known_windows_path", lambda _name: None)
    monkeypatch.setattr(launcher_service, "_windows_app_path", lambda _name: None)
    monkeypatch.setattr(launcher_service, "_llm_suggest_command", fake_llm)
    result = run(launcher_service.suggest_launch_command("vscode"))
    assert result == "code.exe"


def test_record_failed_launch_writes_history_without_incrementing_counter():
    sc = shortcut("Node", target="C:/Program Files/nodejs/node.exe")
    sc.tutor_id = "tutor-1"
    sc.use_count = 2
    sc.last_used_at = None
    db = FakeDb([sc])

    log = run(
        launcher_service.record_launch(
            sc.id,
            db,
            status="failed",
            error="arquivo nao encontrado",
        )
    )

    assert log is not None
    assert log.status == "failed"
    assert log.error == "arquivo nao encontrado"
    assert sc.use_count == 2
    assert sc.last_used_at is None
