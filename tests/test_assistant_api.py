import json

from fastapi.testclient import TestClient

from app.assistant import AssistantProviderError, OnboardingAssistant
from app.main import create_app
from app.sessions import MAX_HISTORY_MESSAGES, SESSION_COOKIE_NAME, SessionStore


GUIDE_CONTENT = json.dumps(
    {
        "answer": "Use a simple table and verify the calculated totals.",
        "steps": [
            {"title": "Set up labels", "instructions": "Enter headings in cells and confirm each entry."},
            {"title": "Enter amounts", "instructions": "Select a cell and enter each fictional amount."},
            {"title": "Calculate a total", "instructions": "Use a supported formula and check the result."},
        ],
        "source_ids": ["libreoffice_calc_data_guide_24_8", "libreoffice_calc_guide_24_8"],
        "unsupported": False,
    }
)
CHAT_CONTENT = json.dumps(
    {
        "answer": "Calc's Function Wizard can help find a function and enter its arguments.",
        "source_ids": ["libreoffice_calc_guide_24_8"],
        "unsupported": False,
    }
)


class FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        return self.responses.pop(0)


class FailingProvider:
    def complete(self, _messages: list[dict[str, str]]) -> str:
        raise AssistantProviderError("The model provider timed out. Check its availability and try again.")


def test_guide_uses_selected_role_and_returns_only_server_sources() -> None:
    provider = FakeProvider([GUIDE_CONTENT])
    client = TestClient(create_app(assistant=OnboardingAssistant(provider)))
    client.post("/api/session", json={"role_id": "finance_analyst"})

    response = client.post("/api/guide", json={"task_id": "monthly_budget"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == "Build a monthly budget"
    assert len(payload["steps"]) == 3
    assert {source["id"] for source in payload["sources"]} == {
        "libreoffice_calc_data_guide_24_8",
        "libreoffice_calc_guide_24_8",
    }
    assert all(source["url"].startswith("https://books.libreoffice.org/") for source in payload["sources"])
    assert "Finance analyst" in provider.calls[0][0]["content"]
    assert "monthly_budget" in provider.calls[0][0]["content"]


def test_follow_up_uses_active_task_and_bounded_session_history() -> None:
    responses = [GUIDE_CONTENT, *([CHAT_CONTENT] * 7)]
    provider = FakeProvider(responses)
    store = SessionStore()
    client = TestClient(create_app(session_store=store, assistant=OnboardingAssistant(provider)))
    client.post("/api/session", json={"role_id": "finance_analyst"})
    client.post("/api/guide", json={"task_id": "monthly_budget"})

    for index in range(7):
        response = client.post("/api/chat", json={"message": f"Question {index + 1}"})
        assert response.status_code == 200
        assert response.json()["sources"][0]["id"] == "libreoffice_calc_guide_24_8"

    token = client.cookies.get(SESSION_COOKIE_NAME)
    session = store.get(token)
    assert session is not None
    assert len(session.history) == MAX_HISTORY_MESSAGES
    last_prompt = provider.calls[-1]
    assert "monthly_budget" in last_prompt[0]["content"]
    assert len(last_prompt) == MAX_HISTORY_MESSAGES + 2
    assert last_prompt[1]["content"] == "Question 1"


def test_guide_and_chat_require_a_valid_session() -> None:
    client = TestClient(create_app())

    assert client.post("/api/guide", json={"task_id": "monthly_budget"}).status_code == 401
    assert client.post("/api/chat", json={"message": "How do I enter data?"}).status_code == 401


def test_guide_rejects_a_task_outside_the_selected_role() -> None:
    client = TestClient(create_app())
    client.post("/api/session", json={"role_id": "finance_analyst"})

    response = client.post("/api/guide", json={"task_id": "headcount_tracker"})

    assert response.status_code == 404


def test_chat_rejects_blank_messages() -> None:
    client = TestClient(create_app())
    client.post("/api/session", json={"role_id": "finance_analyst"})

    response = client.post("/api/chat", json={"message": "   "})

    assert response.status_code == 422


def test_unsupported_answers_are_explicit_and_have_no_model_supplied_link() -> None:
    unsupported = json.dumps(
        {
            "answer": "Visit a fake source.",
            "source_ids": ["https://attacker.example/source"],
            "unsupported": False,
        }
    )
    provider = FakeProvider([unsupported])
    client = TestClient(create_app(assistant=OnboardingAssistant(provider)))
    client.post("/api/session", json={"role_id": "finance_analyst"})

    response = client.post("/api/chat", json={"message": "How do I use a feature not in the notes?"})

    assert response.status_code == 200
    assert response.json()["unsupported"] is True
    assert response.json()["sources"] == []
    assert "enough information" in response.json()["answer"]


def test_missing_model_configuration_returns_actionable_api_error(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    client = TestClient(create_app())
    client.post("/api/session", json={"role_id": "finance_analyst"})

    response = client.post("/api/guide", json={"task_id": "monthly_budget"})

    assert response.status_code == 503
    assert "OPENAI_API_KEY and OPENAI_MODEL" in response.json()["detail"]


def test_provider_failure_returns_safe_api_error() -> None:
    client = TestClient(create_app(assistant=OnboardingAssistant(FailingProvider())))
    client.post("/api/session", json={"role_id": "finance_analyst"})

    response = client.post("/api/chat", json={"message": "How do I enter a formula?"})

    assert response.status_code == 503
    assert "timed out" in response.json()["detail"]