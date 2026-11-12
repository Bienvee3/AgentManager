"""Stdlib-only Agent Manager client.

This file MUST stay dependency-free and import nothing from the package, so it
can be copied into any virtualenv (e.g. the one that hosts Open Interpreter).

# INTEGRATION POINT: use it from your own scripts.
#
#     from agent_manager.client import AgentManagerClient
#
#     client = AgentManagerClient("my-agent", name="My Agent", role="ETL")
#     client.register()
#     client.start_heartbeat()
#     client.status("working", task="Nightly ETL")
#     decision = client.request_approval("Drop table users", details="DROP TABLE users;", kind="generic")
#     if decision.approved:
#         ...
#     client.close()
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class AgentManagerUnavailable(RuntimeError):
    """The Agent Manager server could not be reached."""


@dataclass
class Decision:
    approved: bool
    status: str
    reason: str


class AgentManagerClient:
    def __init__(
        self,
        agent_id: str,
        name: str | None = None,
        role: str = "",
        avatar: int | None = None,
        base_url: str | None = None,
        timeout: float = 10,
    ) -> None:
        self.agent_id = agent_id
        self.name = name or agent_id
        self.role = role
        self.avatar = avatar
        self.base_url = (base_url or os.environ.get("AGENT_MANAGER_URL", "http://127.0.0.1:8765")).rstrip("/")
        self.timeout = timeout
        self._hb_stop = threading.Event()
        self._hb_thread: threading.Thread | None = None

    # -- transport ---------------------------------------------------------

    def _request(self, method: str, path: str, body: Any = None, timeout: float | None = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        if method == "POST" and data is None:
            data = b"{}"
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{exc.code} {exc.read().decode('utf-8', 'replace')}") from None
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            raise AgentManagerUnavailable(f"Agent Manager not reachable at {self.base_url}: {exc}") from exc
        return json.loads(raw) if raw else None

    # -- API ---------------------------------------------------------------

    def register(self, heartbeat_interval_s: float | None = 15) -> dict:
        body: dict[str, Any] = {"id": self.agent_id, "name": self.name, "role": self.role}
        if self.avatar is not None:
            body["avatar"] = self.avatar
        if heartbeat_interval_s is not None:
            body["heartbeat_interval_s"] = heartbeat_interval_s
        return self._request("POST", "/api/agents", body)

    def status(
        self,
        status: str,
        task: str | None = None,
        detail: str | None = None,
        error_kind: str | None = None,
    ) -> dict:
        body: dict[str, Any] = {"status": status}
        if task is not None:
            body["task"] = task
        if detail is not None:
            body["detail"] = detail
        if error_kind is not None:
            body["error_kind"] = error_kind
        return self._request("POST", f"/api/agents/{self.agent_id}/status", body)

    def log(self, message: str, level: str = "info") -> None:
        self._request("POST", f"/api/agents/{self.agent_id}/logs", {"message": message, "level": level})

    def heartbeat(self) -> None:
        self._request("POST", f"/api/agents/{self.agent_id}/heartbeat", {})

    def start_heartbeat(self, interval: float = 15) -> None:
        if self._hb_thread is not None and self._hb_thread.is_alive():
            return
        self._hb_stop.clear()

        def loop() -> None:
            while not self._hb_stop.wait(interval):
                try:
                    self.heartbeat()
                except Exception:  # noqa: BLE001 - heartbeat must never kill the agent
                    pass

        self._hb_thread = threading.Thread(target=loop, name=f"heartbeat-{self.agent_id}", daemon=True)
        self._hb_thread.start()

    def is_critical(self, command: str, tool_name: str = "") -> tuple[bool, str]:
        res = self._request("POST", "/api/policy/classify", {"tool_name": tool_name, "command": command})
        return bool(res["critical"]), res.get("reason", "")

    def request_approval(
        self,
        action: str,
        details: str = "",
        kind: str = "generic",
        timeout_s: float | None = None,
    ) -> Decision:
        body: dict[str, Any] = {"action": action, "details": details, "kind": kind}
        if timeout_s is not None:
            body["timeout_s"] = timeout_s
        approval = self._request("POST", f"/api/agents/{self.agent_id}/approvals", body)
        while approval["status"] == "pending":
            approval = self._request("GET", f"/api/approvals/{approval['id']}?wait=25", timeout=35)
        return Decision(
            approved=approval["status"] == "approved",
            status=approval["status"],
            reason=approval.get("reason", ""),
        )

    def close(self) -> None:
        self._hb_stop.set()
        try:
            self.status("offline", task="", detail="")
        except (AgentManagerUnavailable, RuntimeError):
            pass
