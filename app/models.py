from pydantic import BaseModel, ConfigDict, Field, field_validator


class SpreadsheetTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str


class SoftwareBackground(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    vendor: str
    category: str
    years_used: int = Field(ge=0, le=100)
    proficiency: str


class EmployeeRole(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    tasks: list[SpreadsheetTask]


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: str = Field(min_length=1, max_length=80)


class GuideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1, max_length=80)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must not be blank")
        return value


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    publisher: str
    version: str
    url: str


class GuideStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    instructions: str


class GuideResponse(BaseModel):
    title: str
    introduction: str
    steps: list[GuideStep]
    sources: list[SourceReference]
    unsupported: bool


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceReference]
    unsupported: bool


class UpdateProposalResponse(BaseModel):
    id: str
    package: str
    current_version: str
    proposed_version: str
    explanation: str
    status: str
    verified_version: str | None = None
    message: str | None = None


class UpdateApprovalResponse(BaseModel):
    proposal_id: str
    package: str
    current_version: str
    proposed_version: str
    status: str
    verified_version: str | None
    message: str


class SessionContext(BaseModel):
    status: str = "active"
    expires_in_seconds: int
    active_task_id: str | None = None
    pending_update: UpdateProposalResponse | None = None


class SessionResponse(BaseModel):
    role: EmployeeRole
    context: SessionContext
    software_history: list[SoftwareBackground] = []