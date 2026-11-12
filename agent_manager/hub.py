"""In-memory hub: the single source of truth for agents, approvals and logs.

All state lives on one asyncio loop and every mutation runs synchronously
between awaits, so no locks are needed.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from datetime import timedelta
from typing import Any

from . import hitl_callbacks, labels
from .config import Settings
from .models import AgentState, Approval, LogEntry, Status, utcnow

SUBSCRIBER_QUEUE_LIMIT = 1000
SNAPSHOT_LOGS = 200
ACTION_MAX = 160
DETAILS_MAX = 4000
MESSAGE_MAX = 2000


class ApprovalConflict(Exception):
    """Raised when deciding an approval that is not pending."""


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _status_log_level(status: Status) -> str:
    if status == Status.error:
        return "error"
    if status in (Status.paused, Status.waiting_input, Status.waiting_approval):
        return "warn"
    return "info"


class Hub:
    def __init__(self, settings: Settings, agents: list[AgentState]) -> None:
        self.settings = settings
        self.agents: dict[str, AgentState] = {a.id: a for a in agents}
        self.approvals: dict[str, Approval] = {}
        self._waiters: dict[str, asyncio.Event] = {}
        self.logs: deque[LogEntry] = deque(maxlen=settings.monitor.log_buffer)
        self._subscribers: set[asyncio.Queue] = set()
        self._bg: set[asyncio.Task] = set()
        for message in settings.startup_logs:
            self._record_log(None, "system", message, broadcast=False)

    # -- subscriptions -------------------------------------------------------

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _broadcast(self, event_type: str, data: Any) -> None:
        event = {"type": event_type, "data": data.model_dump(mode="json")}
        for queue in list(self._subscribers):
            if queue.qsize() >= SUBSCRIBER_QUEUE_LIMIT:
                self._subscribers.discard(queue)  # slow client: drop it
                queue.put_nowait(None)  # wake its sender so the socket closes
                continue
            queue.put_nowait(event)

    async def snapshot(self) -> dict[str, Any]:
        return {
            "agents": [a.model_dump(mode="json") for a in self._sorted_agents()],
            "approvals": [
                a.model_dump(mode="json") for a in self.approvals.values() if a.status == "pending"
            ],
            "logs": [e.model_dump(mode="json") for e in list(self.logs)[-SNAPSHOT_LOGS:]],
        }

    def _sorted_agents(self) -> list[AgentState]:
        return sorted(self.agents.values(), key=lambda a: (a.desk, a.name))

    # -- helpers ---------------------------------------------------------------

    def _agent(self, agent_id: str) -> AgentState:
        try:
            return self.agents[agent_id]
        except KeyError:
            raise KeyError(f"Unknown agent '{agent_id}'") from None

    def _approval(self, approval_id: str) -> Approval:
        try:
            return self.approvals[approval_id]
        except KeyError:
            raise KeyError(f"Unknown approval '{approval_id}'") from None

    def _record_log(self, agent_id: str | None, level: str, message: str, broadcast: bool = True) -> None:
        entry = LogEntry(ts=utcnow(), agent_id=agent_id, level=level, message=_truncate(message, MESSAGE_MAX))
        self.logs.append(entry)
        if broadcast:
            self._broadcast("log", entry)

    def _touch(self, agent: AgentState) -> None:
        agent.last_seen = utcnow()

    # -- agents ------------------------------------------------------------------

    async def upsert_agent(
        self,
        agent_id: str,
        name: str | None = None,
        role: str | None = None,
        avatar: int | None = None,
        heartbeat_interval_s: float | None = None,
    ) -> AgentState:
        agent = self.agents.get(agent_id)
        if agent is None:
            desk = max((a.desk for a in self.agents.values()), default=-1) + 1
            agent = AgentState(
                id=agent_id,
                name=name or agent_id,
                role=role or "",
                avatar=avatar,
                desk=desk,
                source="runtime",
                status=Status.idle,
                heartbeat_interval_s=heartbeat_interval_s,
            )
            self.agents[agent_id] = agent
            self._touch(agent)
            self._record_log(agent_id, "system", f"Agente registrado: {agent.name}")
        else:
            if name is not None:
                agent.name = name
            if role is not None:
                agent.role = role
            if avatar is not None:
                agent.avatar = avatar
            if heartbeat_interval_s is not None:
                agent.heartbeat_interval_s = heartbeat_interval_s
            self._touch(agent)
            if agent.status == Status.offline:
                # A registration means the agent is alive.
                agent.status = Status.idle
                self._record_log(agent_id, "info", labels.status_text(agent))
        self._broadcast("agent", agent)
        return agent

    async def set_status(
        self,
        agent_id: str,
        status: Status | str,
        task: str | None = None,
        detail: str | None = None,
        error_kind: str | None = None,
        *,
        from_agent: bool = True,
    ) -> AgentState:
        agent = self._agent(agent_id)
        status = Status(status)
        agent.status = status
        if task is not None:
            agent.task = task
        if detail is not None:
            agent.detail = detail
        agent.error_kind = error_kind if status == Status.error else None
        if from_agent:
            self._touch(agent)
        self._record_log(agent_id, _status_log_level(status), labels.status_text(agent))
        self._broadcast("agent", agent)
        return agent

    async def log(self, agent_id: str | None, level: str, message: str) -> None:
        if agent_id is not None:
            self._touch(self._agent(agent_id))
        self._record_log(agent_id, level, message)

    async def heartbeat(self, agent_id: str) -> None:
        agent = self._agent(agent_id)
        self._touch(agent)
        self._broadcast("agent", agent)

    # -- approvals ---------------------------------------------------------------

    async def create_approval(
        self,
        agent_id: str,
        action: str,
        details: str = "",
        kind: str = "generic",
        timeout_s: float | None = None,
    ) -> Approval:
        agent = self._agent(agent_id)
        timeout = timeout_s if timeout_s is not None else self.settings.hitl.approval_timeout_s
        now = utcnow()
        approval = Approval(
            id=uuid.uuid4().hex,
            agent_id=agent_id,
            action=_truncate(action, ACTION_MAX),
            kind=kind,
            details=_truncate(details, DETAILS_MAX),
            created_at=now,
            expires_at=now + timedelta(seconds=timeout),
        )
        self.approvals[approval.id] = approval
        self._waiters[approval.id] = asyncio.Event()

        agent.status = Status.waiting_approval
        agent.error_kind = None
        agent.pending_approvals += 1
        self._touch(agent)

        self._record_log(agent_id, "hitl", f"HITL solicitado: {approval.action}")
        self._broadcast("approval", approval)
        self._broadcast("agent", agent)

        task = asyncio.create_task(self._expire_later(approval.id, timeout))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return approval

    async def _expire_later(self, approval_id: str, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            await self.expire(approval_id)
        except (KeyError, ApprovalConflict):
            pass  # already decided

    async def wait_approval(self, approval_id: str, wait: float) -> Approval:
        approval = self._approval(approval_id)
        if approval.status == "pending" and wait > 0:
            try:
                await asyncio.wait_for(self._waiters[approval_id].wait(), wait)
            except TimeoutError:
                pass
        return approval

    async def decide(
        self,
        approval_id: str,
        approved: bool,
        reason: str = "",
        via: str | None = "api",
        *,
        status: str | None = None,
    ) -> Approval:
        approval = self._approval(approval_id)
        if approval.status != "pending":
            raise ApprovalConflict(f"Approval already {approval.status}")
        approval.status = status or ("approved" if approved else "rejected")  # type: ignore[assignment]
        approval.reason = reason
        approval.decided_via = via  # type: ignore[assignment]
        approval.decided_at = utcnow()

        agent = self.agents[approval.agent_id]
        agent.pending_approvals = max(0, agent.pending_approvals - 1)
        if agent.status == Status.waiting_approval and agent.pending_approvals == 0:
            if approved:
                agent.status = Status.working
                agent.detail = f"Aprobado: {approval.action}"
            else:
                agent.status = Status.paused
                agent.detail = f"Rechazado: {approval.action}"
        self._touch(agent)

        verb = {"approved": "aprobado", "rejected": "rechazado", "expired": "expirado"}[approval.status]
        self._record_log(approval.agent_id, "hitl", f"HITL {verb}: {approval.action}")
        self._broadcast("approval", approval)
        self._broadcast("agent", agent)
        self._waiters[approval_id].set()

        task = asyncio.create_task(self._run_callback(approved, approval, agent))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return approval

    async def expire(self, approval_id: str) -> Approval:
        return await self.decide(approval_id, False, "Timeout", None, status="expired")

    async def _run_callback(self, approved: bool, approval: Approval, agent: AgentState) -> None:
        callback = hitl_callbacks.on_approved if approved else hitl_callbacks.on_rejected
        try:
            await callback(approval.model_copy(), agent.model_copy())
        except Exception as exc:  # noqa: BLE001 - user callbacks must not break the hub
            self._record_log(approval.agent_id, "error", f"HITL callback failed: {exc}")

    # -- monitoring ----------------------------------------------------------------

    async def run_stale_monitor(self) -> None:
        interval = self.settings.monitor.stale_check_interval_s
        while True:
            await asyncio.sleep(interval)
            now = utcnow()
            for agent in list(self.agents.values()):
                if (
                    agent.heartbeat_interval_s
                    and agent.last_seen is not None
                    and agent.status not in (Status.offline, Status.error)
                    and (now - agent.last_seen).total_seconds() > 3 * agent.heartbeat_interval_s
                ):
                    await self.set_status(
                        agent.id, Status.error, detail="Sin señal del agente", error_kind="lost", from_agent=False
                    )

    async def shutdown(self) -> None:
        for task in list(self._bg):
            task.cancel()
        if self._bg:
            await asyncio.gather(*self._bg, return_exceptions=True)
