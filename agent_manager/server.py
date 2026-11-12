"""FastAPI application: REST + WebSocket + static web UI."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .hub import ApprovalConflict, Hub
from .models import (
    AgentState,
    AgentUpsert,
    Approval,
    ApprovalCreate,
    ClassifyRequest,
    Decision,
    HookRequest,
    LogCreate,
    Status,
    StatusUpdate,
)
from .policy import classify, command_text
from .sources import load_agents

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _allowed_origins(settings: Settings) -> set[str]:
    port = settings.server.port
    return {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
        f"http://{settings.server.host}:{port}",
    }


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub = Hub(settings, load_agents(settings))
        app.state.hub = hub
        monitor = asyncio.create_task(hub.run_stale_monitor())
        tasks = [monitor]
        if settings.project is not None:
            from .omp_source import OmpWatcher

            tasks.append(asyncio.create_task(OmpWatcher(hub, settings.project).run()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await hub.shutdown()

    app = FastAPI(title="Agent Manager", lifespan=lifespan)

    def hub_of(source: Request | WebSocket) -> Hub:
        return source.app.state.hub

    # -- security / errors -------------------------------------------------------

    @app.middleware("http")
    async def require_json(request: Request, call_next):
        if request.method == "POST" and request.url.path.startswith("/api"):
            content_type = request.headers.get("content-type", "")
            if content_type.split(";")[0].strip().lower() != "application/json":
                return JSONResponse({"detail": "Content-Type must be application/json"}, status_code=415)
        return await call_next(request)

    @app.exception_handler(KeyError)
    async def unknown_handler(request: Request, exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": str(exc.args[0])}, status_code=404)

    @app.exception_handler(ApprovalConflict)
    async def conflict_handler(request: Request, exc: ApprovalConflict) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    # -- state -------------------------------------------------------------------

    @app.get("/api/state")
    async def get_state(request: Request) -> dict[str, Any]:
        return await hub_of(request).snapshot()

    @app.get("/api/agents", response_model=list[AgentState])
    async def list_agents(request: Request):
        return hub_of(request)._sorted_agents()

    @app.post("/api/agents", response_model=AgentState)
    async def upsert_agent(request: Request, body: AgentUpsert):
        return await hub_of(request).upsert_agent(
            body.id, body.name, body.role, body.avatar, body.heartbeat_interval_s, model=body.model
        )

    @app.post("/api/agents/{agent_id}/status", response_model=AgentState)
    async def set_status(request: Request, agent_id: str, body: StatusUpdate):
        return await hub_of(request).set_status(
            agent_id, body.status, body.task, body.detail, body.error_kind
        )

    @app.post("/api/agents/{agent_id}/logs", status_code=204)
    async def add_log(request: Request, agent_id: str, body: LogCreate) -> Response:
        await hub_of(request).log(agent_id, body.level, body.message)
        return Response(status_code=204)

    @app.post("/api/agents/{agent_id}/heartbeat", status_code=204)
    async def heartbeat(request: Request, agent_id: str) -> Response:
        await hub_of(request).heartbeat(agent_id)
        return Response(status_code=204)

    # -- approvals -----------------------------------------------------------------

    @app.post("/api/agents/{agent_id}/approvals", status_code=201, response_model=Approval)
    async def create_approval(request: Request, agent_id: str, body: ApprovalCreate):
        return await hub_of(request).create_approval(
            agent_id, body.action, body.details, body.kind, body.timeout_s
        )

    @app.get("/api/approvals/{approval_id}", response_model=Approval)
    async def get_approval(request: Request, approval_id: str, wait: float = Query(0, ge=0, le=30)):
        return await hub_of(request).wait_approval(approval_id, wait)

    @app.post("/api/approvals/{approval_id}/approve", response_model=Approval)
    async def approve(request: Request, approval_id: str, body: Decision = Body(default_factory=Decision)):
        return await hub_of(request).decide(approval_id, True, body.reason, body.via)

    @app.post("/api/approvals/{approval_id}/reject", response_model=Approval)
    async def reject(request: Request, approval_id: str, body: Decision = Body(default_factory=Decision)):
        return await hub_of(request).decide(approval_id, False, body.reason, body.via)

    # -- policy / hooks ----------------------------------------------------------------

    @app.post("/api/policy/classify")
    async def policy_classify(request: Request, body: ClassifyRequest) -> dict[str, Any]:
        critical, reason = classify(body.tool_name, body.command, settings.hitl)
        return {"critical": critical, "reason": reason}

    @app.post("/api/hooks/openinterpreter")
    async def openinterpreter_hook(request: Request, body: HookRequest) -> dict[str, Any]:
        hub = hub_of(request)
        await hub.upsert_agent(body.agent_id, name=body.agent_name or body.agent_id)
        payload = body.payload
        # Event-specific fields (tool_name, tool_input, prompt) are unverified in the
        # Open Interpreter docs, so every access degrades to empty values.
        event = str(payload.get("hook_event_name", "") or "")

        if event == "SessionStart":
            await hub.set_status(body.agent_id, Status.working, task="Sesión iniciada")
        elif event == "UserPromptSubmit":
            prompt = payload.get("prompt")
            task = prompt[:48] if isinstance(prompt, str) and prompt.strip() else "Nuevo prompt"
            await hub.set_status(body.agent_id, Status.working, task=task)
        elif event == "PreToolUse":
            tool = str(payload.get("tool_name", "") or "")
            cmd = command_text(payload.get("tool_input", ""))
            await hub.log(body.agent_id, "info", f"{tool}: {cmd[:160]}")
            critical, _reason = classify(tool, cmd, settings.hitl)
            if critical:
                approval = await hub.create_approval(
                    body.agent_id, f"{tool}: {cmd[:120]}", details=cmd, kind="tool_call"
                )
                return {"action": "pending", "approval": approval.model_dump(mode="json")}
        elif event == "PostToolUse":
            tool = str(payload.get("tool_name", "") or "")
            await hub.log(body.agent_id, "info", f"{tool} terminado")
            await hub.set_status(body.agent_id, Status.working)
        elif event == "PermissionRequest":
            await hub.set_status(
                body.agent_id, Status.waiting_input, detail="Aprobación pendiente en la terminal"
            )
        elif event == "Stop":
            await hub.set_status(
                body.agent_id, Status.waiting_input, detail="Turno terminado — esperando input"
            )
        else:
            await hub.log(body.agent_id, "info", event or "evento sin nombre")
        return {"action": "allow"}

    # -- websocket ------------------------------------------------------------------------

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        origin = ws.headers.get("origin")
        if origin is not None and origin not in _allowed_origins(settings):
            await ws.close(code=1008)
            return
        hub = hub_of(ws)
        await ws.accept()
        queue = await hub.subscribe()  # subscribe first: no event is lost between snapshot and stream
        try:
            await ws.send_json({"type": "snapshot", "data": await hub.snapshot()})

            async def sender() -> None:
                while True:
                    event = await queue.get()
                    if event is None:  # hub dropped this slow subscriber
                        return
                    await ws.send_json(event)

            async def receiver() -> None:
                while True:  # clients send nothing; this only notices disconnects
                    await ws.receive_text()

            tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except WebSocketDisconnect:
            pass
        finally:
            await hub.unsubscribe(queue)

    # Static UI last, so it never shadows /api or /ws.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
