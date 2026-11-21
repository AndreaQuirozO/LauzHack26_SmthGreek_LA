from fastapi.testclient import TestClient

from app.main import create_app
from app.updates import UPDATE_CATALOG, UpdateExecutionResult, UpdateService


class FakeExecutor:
    def __init__(self, result: UpdateExecutionResult | None = None) -> None:
        self.calls = 0
        self.result = result or UpdateExecutionResult(
            "succeeded",
            UPDATE_CATALOG.proposed_version,
            "Verified inside the disposable demo container.",
        )

    def execute(self) -> UpdateExecutionResult:
        self.calls += 1
        return self.result


def create_client(executor: FakeExecutor) -> TestClient:
    return TestClient(create_app(update_service=UpdateService(executor)))


def create_proposal(client: TestClient) -> dict:
    client.post("/api/session", json={"role_id": "finance_analyst"})
    response = client.post("/api/updates/proposals")
    assert response.status_code == 201
    return response.json()


def test_proposal_describes_fixed_demo_versions_without_executing(monkeypatch) -> None:
    monkeypatch.delenv("DEMO_ADMIN_SECRET", raising=False)
    executor = FakeExecutor()
    client = create_client(executor)

    proposal = create_proposal(client)

    assert proposal["package"] == "certifi"
    assert proposal["current_version"] == "2024.8.30"
    assert proposal["proposed_version"] == "2026.11.20"
    assert proposal["status"] == "pending"
    assert "not a reading of this computer" in proposal["explanation"]
    assert executor.calls == 0
    assert client.post("/api/updates/proposals").status_code == 409
    assert executor.calls == 0


def test_missing_or_invalid_admin_secret_does_not_consume_proposal(monkeypatch) -> None:
    executor = FakeExecutor()
    client = create_client(executor)
    proposal = create_proposal(client)
    monkeypatch.delenv("DEMO_ADMIN_SECRET", raising=False)

    missing = client.post(f"/api/updates/{proposal['id']}/approve")

    assert missing.status_code == 503
    assert "DEMO_ADMIN_SECRET" in missing.json()["detail"]
    monkeypatch.setenv("DEMO_ADMIN_SECRET", "authorized-secret")
    invalid = client.post(
        f"/api/updates/{proposal['id']}/approve",
        headers={"X-Demo-Admin-Secret": "wrong-secret"},
    )
    assert invalid.status_code == 403
    assert executor.calls == 0


def test_approval_is_session_bound_single_use_and_reports_verified_version(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_ADMIN_SECRET", "authorized-secret")
    executor = FakeExecutor()
    client = create_client(executor)
    proposal = create_proposal(client)

    response = client.post(
        f"/api/updates/{proposal['id']}/approve",
        headers={"X-Demo-Admin-Secret": "authorized-secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert response.json()["verified_version"] == "2026.11.20"
    assert response.json()["current_version"] == "2024.8.30"
    assert executor.calls == 1
    replay = client.post(
        f"/api/updates/{proposal['id']}/approve",
        headers={"X-Demo-Admin-Secret": "authorized-secret"},
    )
    assert replay.status_code == 409
    assert executor.calls == 1

    other_client = create_client(FakeExecutor())
    other_client.post("/api/session", json={"role_id": "hr_coordinator"})
    mismatch = other_client.post(
        f"/api/updates/{proposal['id']}/approve",
        headers={"X-Demo-Admin-Secret": "authorized-secret"},
    )
    assert mismatch.status_code == 404


def test_execution_failure_is_reported_without_claiming_success(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_ADMIN_SECRET", "authorized-secret")
    executor = FakeExecutor(UpdateExecutionResult("failed", None, "Docker is unavailable."))
    client = create_client(executor)
    proposal = create_proposal(client)

    response = client.post(
        f"/api/updates/{proposal['id']}/approve",
        headers={"X-Demo-Admin-Secret": "authorized-secret"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["verified_version"] is None
    assert response.json()["message"] == "Docker is unavailable."