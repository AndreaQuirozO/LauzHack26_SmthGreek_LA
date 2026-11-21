import json
import os
import subprocess
import threading
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

import app.updates as updates
from app.sessions import SessionStore
from app.updates import (
    AdministratorAuthorizationError,
    AdministratorConfigurationError,
    DockerUpdateExecutor,
    DuplicateProposalError,
    ProposalAlreadyConsumedError,
    ProposalNotFoundError,
    UpdateExecutionResult,
    UpdateService,
)


class FakeExecutor:
    def __init__(self, result: UpdateExecutionResult | None = None) -> None:
        self.calls = 0
        self.result = result or UpdateExecutionResult(
            "succeeded",
            updates.UPDATE_CATALOG.proposed_version,
            "Demo version verified.",
        )

    def execute(self) -> UpdateExecutionResult:
        self.calls += 1
        return self.result


def create_session():
    return SessionStore().create("finance_analyst")[1]


def test_proposal_is_fixed_and_only_created_once_per_session() -> None:
    service = UpdateService(FakeExecutor())
    session = create_session()

    proposal = service.create_proposal(session)

    assert proposal.package == "certifi"
    assert proposal.current_version == "2024.8.30"
    assert proposal.proposed_version == "2026.11.20"
    assert "not a reading of this computer" in proposal.explanation
    with pytest.raises(DuplicateProposalError):
        service.create_proposal(session)


def test_missing_or_wrong_admin_secret_never_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = FakeExecutor()
    service = UpdateService(executor)
    session = create_session()
    proposal = service.create_proposal(session)
    monkeypatch.delenv("DEMO_ADMIN_SECRET", raising=False)

    with pytest.raises(AdministratorConfigurationError):
        service.approve(session, proposal.id, "secret")
    monkeypatch.setenv("DEMO_ADMIN_SECRET", "authorized-secret")
    with pytest.raises(AdministratorAuthorizationError):
        service.approve(session, proposal.id, "wrong-secret")

    assert executor.calls == 0
    assert session.pending_update.status == "pending"


def test_proposal_is_bound_to_the_session_that_created_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_ADMIN_SECRET", "authorized-secret")
    executor = FakeExecutor()
    service = UpdateService(executor)
    owner_session = create_session()
    other_session = create_session()
    proposal = service.create_proposal(owner_session)

    with pytest.raises(ProposalNotFoundError):
        service.approve(other_session, proposal.id, "authorized-secret")
    assert executor.calls == 0


def test_approval_executes_at_most_once_and_returns_verified_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_ADMIN_SECRET", "authorized-secret")
    executor = FakeExecutor()
    service = UpdateService(executor)
    session = create_session()
    proposal = service.create_proposal(session)

    result = service.approve(session, proposal.id, "authorized-secret")

    assert result.status == "succeeded"
    assert result.verified_version == updates.UPDATE_CATALOG.proposed_version
    assert executor.calls == 1
    with pytest.raises(ProposalAlreadyConsumedError):
        service.approve(session, proposal.id, "authorized-secret")
    assert executor.calls == 1


def test_concurrent_approval_consumes_the_proposal_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_ADMIN_SECRET", "authorized-secret")
    started = threading.Event()
    release = threading.Event()

    class BlockingExecutor:
        def execute(self) -> UpdateExecutionResult:
            started.set()
            assert release.wait(timeout=5)
            return UpdateExecutionResult("succeeded", "2026.11.20", "Verified.")

    service = UpdateService(BlockingExecutor())
    session = create_session()
    proposal = service.create_proposal(session)
    results = []

    approval_thread = threading.Thread(
        target=lambda: results.append(service.approve(session, proposal.id, "authorized-secret"))
    )
    approval_thread.start()
    assert started.wait(timeout=5)
    try:
        with pytest.raises(ProposalAlreadyConsumedError):
            service.approve(session, proposal.id, "authorized-secret")
    finally:
        release.set()
        approval_thread.join(timeout=5)

    assert not approval_thread.is_alive()
    assert len(results) == 1
    assert results[0].status == "succeeded"


def test_docker_executor_uses_fixed_isolation_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    output = json.dumps(
        {
            "package": "certifi",
            "baseline": "2024.8.30",
            "target": "2026.11.20",
            "verified_version": "2026.11.20",
        }
    )
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(updates.subprocess, "run", fake_run)

    result = DockerUpdateExecutor().execute()

    command = captured["command"]
    assert command[0:2] == ["docker", "run"]
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges" in command
    assert "--user=10001:10001" in command
    assert "--memory=256m" in command
    assert "--cpus=0.5" in command
    assert any(value.startswith("--tmpfs=/tmp:") for value in command)
    assert command[-1] == updates.UPDATE_CATALOG.image
    assert not any(value in {"-v", "--volume", "--mount", "--privileged"} for value in command)
    assert captured["kwargs"] == {
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": updates.EXECUTION_TIMEOUT_SECONDS,
    }
    assert result.status == "succeeded"
    assert result.verified_version == "2026.11.20"


@pytest.mark.parametrize(
    ("run_error", "return_code", "stdout", "expected_message"),
    [
        (FileNotFoundError(), None, None, "not installed"),
        (subprocess.TimeoutExpired("docker", timeout=1), None, None, "time limit"),
        (None, 1, "", "reported a failure"),
        (None, 0, "{}", "could not be verified"),
    ],
)
def test_docker_failures_are_safe(
    monkeypatch: pytest.MonkeyPatch,
    run_error: Exception | None,
    return_code: int | None,
    stdout: str | None,
    expected_message: str,
) -> None:
    def fake_run(command, **kwargs):
        if run_error is not None:
            raise run_error
        return subprocess.CompletedProcess(command, return_code, stdout=stdout, stderr="sensitive detail")

    monkeypatch.setattr(updates.subprocess, "run", fake_run)

    result = DockerUpdateExecutor(timeout_seconds=1).execute()

    assert result.status == "failed"
    assert result.verified_version is None
    assert expected_message in result.message
    assert "sensitive detail" not in result.message


@pytest.mark.skipif(os.getenv("RUN_DOCKER_INTEGRATION") != "1", reason="set RUN_DOCKER_INTEGRATION=1 to run Docker")
def test_docker_update_integration_builds_runs_and_removes_container(monkeypatch: pytest.MonkeyPatch) -> None:
    image = f"excel-calc-certifi-demo:test-{uuid.uuid4().hex}"
    monkeypatch.setattr(updates, "UPDATE_CATALOG", replace(updates.UPDATE_CATALOG, image=image))
    build_context = Path(__file__).parents[1] / "demo" / "update"
    subprocess.run(
        ["docker", "build", "--tag", image, "."],
        cwd=build_context,
        check=True,
        capture_output=True,
        text=True,
        timeout=600,
    )
    try:
        result = DockerUpdateExecutor().execute()
        containers = subprocess.run(
            ["docker", "ps", "--all", "--filter", f"ancestor={image}", "--format", "{{.ID}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.status == "succeeded"
        assert result.verified_version == "2026.11.20"
        assert containers.stdout.strip() == ""
    finally:
        subprocess.run(
            ["docker", "image", "rm", "--force", image],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )