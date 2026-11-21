import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.assistant import AssistantError, OnboardingAssistant
from app.knowledge import get_role, get_roles, get_sources
from app.models import (
    ChatRequest,
    ChatResponse,
    EmployeeRole,
    GuideRequest,
    GuideResponse,
    SessionContext,
    SessionCreateRequest,
    SessionResponse,
    SourceReference,
    UpdateApprovalResponse,
    UpdateProposalResponse,
)
from app.sessions import SESSION_COOKIE_NAME, SessionStore
from app.updates import (
    AdministratorAuthorizationError,
    AdministratorConfigurationError,
    DuplicateProposalError,
    ProposalAlreadyConsumedError,
    ProposalNotFoundError,
    UpdateProposal,
    UpdateService,
)


def create_app(
    session_store: SessionStore | None = None,
    assistant: OnboardingAssistant | None = None,
    update_service: UpdateService | None = None,
) -> FastAPI:
    application = FastAPI(title="Excel to Calc Onboarding Demo", version="0.1.0")
    store = session_store or SessionStore()
    onboarding_assistant = assistant if assistant is not None else OnboardingAssistant()
    updates = update_service if update_service is not None else UpdateService()
    application.state.session_store = store
    application.state.assistant = onboarding_assistant
    application.state.update_service = updates

    @application.middleware("http")
    async def restrict_to_local_clients(request: Request, call_next):
        host = request.headers.get("host", "")
        client_host = request.client.host if request.client is not None else ""
        test_harness = client_host == "testclient" and host.lower() == "testserver"
        if not test_harness and (not is_loopback_authority(host) or not is_loopback_client(client_host)):
            return JSONResponse(status_code=403, content={"detail": "This demo accepts local connections only."})

        origin = request.headers.get("origin")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin is not None:
            if not is_same_origin_loopback(origin, host, request.url.scheme):
                return JSONResponse(status_code=403, content={"detail": "Cross-origin requests are not allowed."})
        return await call_next(request)

    def authenticated_session(request: Request, response: Response):
        token = request.cookies.get(SESSION_COOKIE_NAME)
        session = store.get(token)
        if session is None:
            raise HTTPException(status_code=401, detail="Create a session first")
        set_session_cookie(response, token, store.ttl_seconds)
        return session

    def get_source_references(source_ids: tuple[str, ...]) -> list[SourceReference]:
        sources = {source["id"]: source for source in get_sources()}
        return [SourceReference(**sources[source_id]) for source_id in source_ids if source_id in sources]

    def get_update_proposal_response(proposal: UpdateProposal) -> UpdateProposalResponse:
        return UpdateProposalResponse(
            id=proposal.id,
            package=proposal.package,
            current_version=proposal.current_version,
            proposed_version=proposal.proposed_version,
            explanation=proposal.explanation,
            status=proposal.status,
            verified_version=proposal.verified_version,
            message=proposal.message,
        )

    @application.get("/healthz")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    static_directory = Path(__file__).parent / "static"
    application.mount("/static", StaticFiles(directory=static_directory), name="static")

    @application.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_directory / "index.html")

    @application.get("/api/roles", response_model=list[EmployeeRole])
    def list_roles() -> list[dict]:
        return get_roles()

    @application.post("/api/session", response_model=SessionResponse, status_code=201)
    def create_session(
        body: SessionCreateRequest,
        request: Request,
        response: Response,
    ) -> SessionResponse:
        role = get_role(body.role_id)
        if role is None:
            raise HTTPException(status_code=404, detail="Unknown employee role")

        store.delete(request.cookies.get(SESSION_COOKIE_NAME))
        token, _ = store.create(body.role_id)
        set_session_cookie(response, token, store.ttl_seconds)
        return SessionResponse(
            role=role,
            context=SessionContext(expires_in_seconds=store.ttl_seconds),
        )

    @application.get("/api/session", response_model=SessionResponse)
    def get_session(request: Request, response: Response) -> SessionResponse:
        session = authenticated_session(request, response)

        role = get_role(session.role_id)
        if role is None:
            raise HTTPException(status_code=401, detail="Session role is no longer available")
        with session.lock:
            pending_update = session.pending_update
            update_response = (
                get_update_proposal_response(pending_update)
                if isinstance(pending_update, UpdateProposal)
                else None
            )
            active_task_id = session.active_task_id
        return SessionResponse(
            role=role,
            context=SessionContext(
                expires_in_seconds=store.ttl_seconds,
                active_task_id=active_task_id,
                pending_update=update_response,
            ),
        )

    @application.post("/api/guide", response_model=GuideResponse)
    def create_guide(
        body: GuideRequest,
        request: Request,
        response: Response,
    ) -> GuideResponse:
        session = authenticated_session(request, response)
        role = get_role(session.role_id)
        if role is None:
            raise HTTPException(status_code=401, detail="Session role is no longer available")
        task = next((item for item in role["tasks"] if item["id"] == body.task_id), None)
        if task is None:
            raise HTTPException(status_code=404, detail="Unknown task for the selected role")

        try:
            with session.lock:
                result = onboarding_assistant.generate_guide(role, task, list(session.history))
                session.active_task_id = task["id"]
                guide_history = result.answer + "\n" + "\n".join(
                    f"{step['title']}: {step['instructions']}" for step in result.steps
                )
                store.record_exchange(
                    session,
                    f"Generate an onboarding guide for {task['name']}.",
                    guide_history,
                )
        except AssistantError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

        return GuideResponse(
            title=task["name"],
            introduction=result.answer,
            steps=result.steps,
            sources=get_source_references(result.source_ids),
            unsupported=result.unsupported,
        )

    @application.post("/api/chat", response_model=ChatResponse)
    def chat(body: ChatRequest, request: Request, response: Response) -> ChatResponse:
        session = authenticated_session(request, response)
        role = get_role(session.role_id)
        if role is None:
            raise HTTPException(status_code=401, detail="Session role is no longer available")
        task = next(
            (item for item in role["tasks"] if item["id"] == session.active_task_id),
            None,
        )

        try:
            with session.lock:
                result = onboarding_assistant.answer_question(
                    role,
                    task,
                    list(session.history),
                    body.message,
                )
                store.record_exchange(session, body.message, result.answer)
        except AssistantError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

        return ChatResponse(
            answer=result.answer,
            sources=get_source_references(result.source_ids),
            unsupported=result.unsupported,
        )

    @application.post(
        "/api/updates/proposals",
        response_model=UpdateProposalResponse,
        status_code=201,
    )
    def create_update_proposal(request: Request, response: Response) -> UpdateProposalResponse:
        session = authenticated_session(request, response)
        try:
            proposal = updates.create_proposal(session)
        except DuplicateProposalError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return get_update_proposal_response(proposal)

    @application.post(
        "/api/updates/{proposal_id}/approve",
        response_model=UpdateApprovalResponse,
    )
    def approve_update(
        proposal_id: str,
        request: Request,
        response: Response,
        admin_secret: str | None = Header(default=None, alias="X-Demo-Admin-Secret"),
    ) -> UpdateApprovalResponse:
        session = authenticated_session(request, response)
        try:
            proposal = updates.approve(session, proposal_id, admin_secret)
        except AdministratorConfigurationError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except AdministratorAuthorizationError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except ProposalNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ProposalAlreadyConsumedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return UpdateApprovalResponse(
            proposal_id=proposal.id,
            package=proposal.package,
            current_version=proposal.current_version,
            proposed_version=proposal.proposed_version,
            status=proposal.status,
            verified_version=proposal.verified_version,
            message=proposal.message,
        )

    return application


def set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )


def is_loopback_authority(authority: str) -> bool:
    try:
        parsed = urlsplit(f"//{authority}")
        hostname = parsed.hostname
        if not hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            return False
        parsed.port
        return hostname.lower() == "localhost" or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def is_loopback_client(host: str) -> bool:
    if host == "testclient":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_same_origin_loopback(origin: str, host: str, scheme: str) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return (
        parsed.scheme == scheme
        and parsed.netloc.lower() == host.lower()
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and is_loopback_authority(parsed.netloc)
    )


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)