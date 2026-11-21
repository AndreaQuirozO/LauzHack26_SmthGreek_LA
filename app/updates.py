import hmac
import json
import os
import secrets
import subprocess
from dataclasses import dataclass, replace
from typing import Protocol

from app.sessions import Session


@dataclass(frozen=True)
class UpdateCatalogItem:
    package: str
    current_version: str
    proposed_version: str
    image: str
    explanation: str


@dataclass(frozen=True)
class UpdateProposal:
    id: str
    package: str
    current_version: str
    proposed_version: str
    explanation: str
    status: str = "pending"
    verified_version: str | None = None
    message: str = "Approval is required before this demo update can run."


@dataclass(frozen=True)
class UpdateExecutionResult:
    status: str
    verified_version: str | None
    message: str


UPDATE_CATALOG = UpdateCatalogItem(
    package="certifi",
    current_version="2024.8.30",
    proposed_version="2026.11.20",
    image="excel-calc-certifi-demo:2026.11.20",
    explanation=(
        "This fixed scenario demonstrates an approved certificate-bundle package update. "
        "The versions describe only the disposable demo environment; they are not a reading of this "
        "computer and do not claim that the baseline is vulnerable."
    ),
)
EXECUTION_TIMEOUT_SECONDS = 180


class UpdateError(Exception):
    pass


class DuplicateProposalError(UpdateError):
    pass


class ProposalNotFoundError(UpdateError):
    pass


class ProposalAlreadyConsumedError(UpdateError):
    pass


class AdministratorConfigurationError(UpdateError):
    pass


class AdministratorAuthorizationError(UpdateError):
    pass


class UpdateExecutor(Protocol):
    def execute(self) -> UpdateExecutionResult: ...


class DockerUpdateExecutor:
    def __init__(self, timeout_seconds: int = EXECUTION_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def execute(self) -> UpdateExecutionResult:
        command = [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--memory=256m",
            "--memory-swap=256m",
            "--cpus=0.5",
            "--ulimit=nofile=64:64",
            "--user=10001:10001",
            "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,uid=10001,gid=10001",
            "--env=HOME=/tmp",
            "--env=PIP_NO_INDEX=1",
            "--env=PIP_NO_CACHE_DIR=1",
            "--env=PIP_DISABLE_PIP_VERSION_CHECK=1",
            "--env=PIP_CONFIG_FILE=/dev/null",
            UPDATE_CATALOG.image,
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except FileNotFoundError:
            return UpdateExecutionResult("failed", None, "Docker is not installed or is not available on PATH.")
        except subprocess.TimeoutExpired:
            return UpdateExecutionResult("failed", None, "The isolated update exceeded its time limit.")
        except OSError:
            return UpdateExecutionResult("failed", None, "Docker could not start the isolated update.")

        if result.returncode != 0:
            return UpdateExecutionResult("failed", None, "The isolated update container reported a failure.")

        try:
            output = json.loads(result.stdout)
        except (TypeError, ValueError):
            return UpdateExecutionResult("failed", None, "The isolated update returned an unreadable result.")
        if (
            not isinstance(output, dict)
            or output.get("package") != UPDATE_CATALOG.package
            or output.get("baseline") != UPDATE_CATALOG.current_version
            or output.get("target") != UPDATE_CATALOG.proposed_version
            or output.get("verified_version") != UPDATE_CATALOG.proposed_version
        ):
            return UpdateExecutionResult("failed", None, "The isolated update version could not be verified.")
        return UpdateExecutionResult(
            "succeeded",
            UPDATE_CATALOG.proposed_version,
            f"{UPDATE_CATALOG.package} {UPDATE_CATALOG.proposed_version} was verified in the disposable container.",
        )


class UpdateService:
    def __init__(self, executor: UpdateExecutor | None = None) -> None:
        self.executor = executor if executor is not None else DockerUpdateExecutor()

    def create_proposal(self, session: Session) -> UpdateProposal:
        with session.lock:
            if session.pending_update is not None:
                raise DuplicateProposalError("This session already has an update proposal.")
            proposal = UpdateProposal(
                id=secrets.token_urlsafe(24),
                package=UPDATE_CATALOG.package,
                current_version=UPDATE_CATALOG.current_version,
                proposed_version=UPDATE_CATALOG.proposed_version,
                explanation=UPDATE_CATALOG.explanation,
            )
            session.pending_update = proposal
            return proposal

    def approve(
        self,
        session: Session,
        proposal_id: str,
        supplied_secret: str | None,
    ) -> UpdateProposal:
        expected_secret = os.getenv("DEMO_ADMIN_SECRET", "")
        if not expected_secret:
            raise AdministratorConfigurationError(
                "Administrator approval is not configured. Set DEMO_ADMIN_SECRET before approving updates."
            )
        if not supplied_secret or not hmac.compare_digest(
            supplied_secret.encode("utf-8"), expected_secret.encode("utf-8")
        ):
            raise AdministratorAuthorizationError("A valid demo administrator secret is required.")

        with session.lock:
            proposal = session.pending_update
            if not isinstance(proposal, UpdateProposal) or not hmac.compare_digest(
                proposal.id.encode("utf-8"), proposal_id.encode("utf-8")
            ):
                raise ProposalNotFoundError("No matching update proposal exists in this session.")
            if proposal.status != "pending":
                raise ProposalAlreadyConsumedError("This update proposal has already been consumed.")
            running_proposal = replace(
                proposal,
                status="running",
                message="The approved update is running in a disposable container.",
            )
            session.pending_update = running_proposal

        try:
            result = self.executor.execute()
        except Exception:
            result = UpdateExecutionResult("failed", None, "The isolated update failed safely.")

        with session.lock:
            completed_proposal = replace(
                running_proposal,
                status=result.status,
                verified_version=result.verified_version,
                message=result.message,
            )
            session.pending_update = completed_proposal
            return completed_proposal