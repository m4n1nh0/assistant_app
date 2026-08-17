from app.services.education_action_service import build_education_open_action


def test_recognizes_lesson_start_and_education_mode_requests():
    for message in (
        "Dani, vamos iniciar a aula",
        "Abra o modo educação",
        "Vou começar minha aula agora",
    ):
        action = build_education_open_action(message)
        assert action is not None
        assert action.destination == "lesson"
        assert action.requires_confirmation is True


def test_recognizes_attendance_without_confusing_phone_calls():
    action = build_education_open_action("Dani, faça a chamada dos alunos")

    assert action is not None
    assert action.destination == "attendance"
    assert build_education_open_action("Faça uma chamada para o João") is None


def test_study_questions_do_not_open_the_education_interface():
    assert build_education_open_action("O que vimos na aula passada?") is None
