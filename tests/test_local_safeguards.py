from fastapi.testclient import TestClient

from app.main import create_app
from app.updates import UpdateExecutionResult, UpdateService


class NeverRunExecutor:
    def execute(self) -> UpdateExecutionResult:
        raise AssertionError("Creating a proposal must not execute the update.")


def test_local_ui_and_same_origin_state_changes_are_available() -> None:
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    page = client.get("/")
    session = client.post(
        "/api/session",
        json={"role_id": "finance_analyst"},
        headers={"Origin": "http://127.0.0.1"},
    )

    assert page.status_code == 200
    assert "Excel to LibreOffice Calc onboarding" in page.text
    assert session.status_code == 201


def test_non_loopback_host_is_rejected() -> None:
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.get("/api/roles", headers={"Host": "demo.example"})

    assert response.status_code == 403
    assert "local connections only" in response.json()["detail"]


def test_cross_origin_state_change_is_rejected() -> None:
    client = TestClient(create_app(), base_url="http://127.0.0.1")

    response = client.post(
        "/api/session",
        json={"role_id": "finance_analyst"},
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert "Cross-origin" in response.json()["detail"]


def test_session_context_restores_pending_update_state() -> None:
    client = TestClient(
        create_app(update_service=UpdateService(NeverRunExecutor())),
        base_url="http://127.0.0.1",
    )
    client.post("/api/session", json={"role_id": "finance_analyst"})
    proposal_response = client.post("/api/updates/proposals")
    assert proposal_response.status_code == 201
    proposal = proposal_response.json()

    session_response = client.get("/api/session")
    assert session_response.status_code == 200
    session = session_response.json()

    assert session["context"]["pending_update"]["id"] == proposal["id"]
    assert session["context"]["pending_update"]["status"] == "pending"