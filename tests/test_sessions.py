from fastapi.testclient import TestClient

from app.main import create_app
from app.sessions import SessionStore


def test_roles_and_session_creation_return_the_selected_role() -> None:
    client = TestClient(create_app())

    roles_response = client.get("/api/roles")
    assert roles_response.status_code == 200
    roles = roles_response.json()
    assert {role["id"] for role in roles} == {
        "finance_analyst",
        "hr_coordinator",
        "operations_manager",
    }

    response = client.post("/api/session", json={"role_id": "finance_analyst"})

    assert response.status_code == 201
    assert response.json()["role"]["id"] == "finance_analyst"
    assert response.json()["role"]["tasks"]
    assert response.json()["context"]["status"] == "active"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_unknown_role_is_rejected_without_creating_a_session() -> None:
    client = TestClient(create_app())

    response = client.post("/api/session", json={"role_id": "unknown"})

    assert response.status_code == 404
    assert "set-cookie" not in response.headers
    assert client.get("/api/session").status_code == 401


def test_sessions_are_isolated_between_clients() -> None:
    application = create_app()
    finance_client = TestClient(application)
    hr_client = TestClient(application)

    finance_client.post("/api/session", json={"role_id": "finance_analyst"})
    hr_client.post("/api/session", json={"role_id": "hr_coordinator"})

    assert finance_client.get("/api/session").json()["role"]["id"] == "finance_analyst"
    assert hr_client.get("/api/session").json()["role"]["id"] == "hr_coordinator"
    assert TestClient(application).get("/api/session").status_code == 401


def test_session_expires_after_idle_timeout() -> None:
    now = [100.0]
    store = SessionStore(ttl_seconds=10, clock=lambda: now[0])
    token, session = store.create("finance_analyst")

    assert store.get(token) is session
    now[0] += 10
    assert store.get(token) is None