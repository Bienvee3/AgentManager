"""Pydantic models shared by the hub, the server and the TUI."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

AGENT_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Status(str, Enum):
    idle = "idle"
    working = "working"
    paused = "paused"
    waiting_input = "waiting_input"
    waiting_approval = "waiting_approval"
    error = "error"
    offline = "offline"


class AgentState(BaseModel):
    id: str = Field(pattern=AGENT_ID_PATTERN)
    name: str
    role: str = ""
    avatar: int | None = Field(default=None, ge=0, le=3)
    desk: int = 0
    source: Literal["config", "runtime"] = "runtime"
    status: Status = Status.idle
    task: str = ""
    detail: str = ""
    error_kind: str | None = None
    last_seen: datetime | None = None
    heartbeat_interval_s: float | None = None
    pending_approvals: int = 0


class Approval(BaseModel):
    id: str
    agent_id: str
    action: str
    kind: str = "generic"
    details: str = ""
    status: Literal["pending", "approved", "rejected", "expired"] = "pending"
    reason: str = ""
    decided_via: Literal["web", "tui", "api"] | None = None
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None = None


class LogEntry(BaseModel):
    ts: datetime
    agent_id: str | None = None
    level: Literal["info", "warn", "error", "hitl", "system"] = "info"
    message: str


# --- request bodies -------------------------------------------------------


class AgentUpsert(BaseModel):
    id: str = Field(pattern=AGENT_ID_PATTERN)
    name: str | None = None
    role: str | None = None
    avatar: int | None = Field(default=None, ge=0, le=3)
    heartbeat_interval_s: float | None = Field(default=None, gt=0)


class StatusUpdate(BaseModel):
    status: Status
    task: str | None = None
    detail: str | None = None
    error_kind: str | None = None


class LogCreate(BaseModel):
    message: str
    level: Literal["info", "warn", "error", "hitl", "system"] = "info"


class ApprovalCreate(BaseModel):
    action: str
    details: str = ""
    kind: str = "generic"
    timeout_s: float | None = Field(default=None, gt=0)


class Decision(BaseModel):
    reason: str = ""
    via: Literal["web", "tui", "api"] = "api"


class ClassifyRequest(BaseModel):
    tool_name: str = ""
    command: str


class HookRequest(BaseModel):
    agent_id: str = Field(pattern=AGENT_ID_PATTERN)
    agent_name: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
