from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Action(Strict):
    name: str
    arguments: dict[str, Any]


class AcceptanceCheck(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,60}$")
    label: str
    kind: Literal["file_exists", "text_contains", "command", "manual"]
    path: str | None = None
    contains: str | None = None
    argv: list[str] = []
    timeout: float = Field(default=60, gt=0, le=600)

    @model_validator(mode="after")
    def valid(self):
        if self.kind in ("file_exists", "text_contains") and not self.path:
            raise ValueError("文件验收需要路径")
        if self.kind == "text_contains" and self.contains is None:
            raise ValueError("内容验收需要 contains")
        if self.kind == "command" and not self.argv:
            raise ValueError("命令验收需要 argv")
        return self


class Guardrails(Strict):
    max_tool_errors: int = Field(default=3, ge=1, le=20)
    max_steps: int = Field(default=160, ge=1, le=1000)
    repeated_results: int = Field(default=3, ge=2, le=10)
    repair_rounds: int = Field(default=3, ge=0, le=10)
    provider_retries: int = Field(default=2, ge=0, le=5)
    retry_delay: float = Field(default=1, ge=0, le=30)
    context_chars: int = Field(default=120000, ge=8000, le=500000)


class TaskSpec(Strict):
    conversational: bool = False
    goal: str = Field(min_length=1, max_length=20000)
    workspace: str
    context: str = ""
    inputs: list[str] = []
    deliverables: list[str] = []
    acceptance: list[str] = []
    plan: list[str] = []
    tools: list[str] = [
        "workspace.inspect",
        "task.plan",
        "files.read",
        "files.search",
        "files.symbols",
        "agent.delegate",
        "web.fetch",
        "web.search",
        "files.edit",
        "files.write",
        "terminal.run",
    ]
    mode: Literal["ask", "workspace"] = "ask"
    provider: str = "scripted"
    collaboration: bool = False
    collaboration_mapping: dict[str, str] = {}
    token_reminder: int | None = Field(default=None, gt=0)
    script: list[Action] = Field(default_factory=list, max_length=20)
    hard_token_budget: int | None = Field(default=None, gt=0)
    hard_cost_budget: float | None = Field(default=None, gt=0)
    cost_reminder: float | None = Field(default=None, gt=0)
    checks: list[AcceptanceCheck] = Field(default_factory=list, max_length=30)
    guardrails: Guardrails = Field(default_factory=Guardrails)

    @model_validator(mode="after")
    def unique_checks(self):
        if len({c.id for c in self.checks}) != len(self.checks):
            raise ValueError("验收检查 ID 不能重复")
        return self


class Steering(Strict):
    content: str = Field(min_length=1, max_length=20000)
    plan_change: bool = False
    attachments: list[str] = Field(default_factory=list, max_length=10)


class RecoveryDecision(Strict):
    call_id: str
    decision: Literal["skip", "retry"]
    note: str = Field(min_length=1, max_length=2000)


class Approval(Strict):
    allow: bool
    scope: Literal["once", "task", "workspace", "workspace_terminal"] = "once"
    hours: float = Field(default=1, gt=0, le=168)


class ProviderConfig(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str
    base_url: str = "https://api.openai.com/v1"
    model: str
    credential_ref: str | None = None
    tools: bool = False
    vision: bool = False
    streaming: bool = True
    timeout: float = Field(default=60, ge=1, le=600)
    input_price: float | None = Field(default=None, ge=0)
    output_price: float | None = Field(default=None, ge=0)
    cached_input_price: float | None = Field(default=None, ge=0)
    extra: dict[str, Any] = {}
    verified: dict[str, str] = {}
    profile: dict[str, Any] = {}


class Message(Strict):
    content: str = Field(min_length=1, max_length=50000)
    provider: str = "scripted"
    attachments: list[str] = Field(default_factory=list, max_length=10)
    execute: bool = False
    mode: Literal["ask", "workspace"] = "ask"
    workspace: str = ""
    collaboration: bool = False
    collaboration_mapping: dict[str, str] = {}


class FileRead(Strict):
    path: str
    offset: int = Field(default=0, ge=0)
    max_bytes: int = Field(default=65536, ge=1024, le=262144)


class FileWrite(Strict):
    path: str
    content: str = Field(max_length=1000000)
    expected_sha256: str | None = None


class Revert(Strict):
    change_id: str


class GitCommit(Strict):
    message: str = Field(min_length=1, max_length=500)
    paths: list[str] = Field(min_length=1, max_length=100)


class Command(Strict):
    argv: list[str] = Field(min_length=1, max_length=100)
    timeout: float = Field(default=300, gt=0, le=3600)
    cwd: str | None = None
    encoding: Literal["auto", "utf-8", "gb18030", "utf-16le"] = "auto"


STATES = {
    "draft": {"clarifying", "planned", "cancelled"},
    "clarifying": {"planned", "cancelled"},
    "planned": {"awaiting_approval", "running", "cancelled", "paused"},
    "awaiting_approval": {
        "planned",
        "running",
        "verifying",
        "cancelled",
        "paused",
        "failed",
        "waiting_for_user",
    },
    "running": {
        "awaiting_approval",
        "waiting_for_user",
        "paused",
        "verifying",
        "failed",
        "cancelled",
    },
    "waiting_for_user": {"planned", "running", "paused", "cancelled"},
    "paused": {"planned", "cancelled"},
    "verifying": {
        "awaiting_feedback",
        "running",
        "awaiting_approval",
        "waiting_for_user",
        "failed",
        "paused",
        "cancelled",
    },
    "awaiting_feedback": {"completed", "planned", "cancelled"},
    "completed": set(),
    "failed": {"planned", "cancelled"},
    "cancelled": set(),
}
