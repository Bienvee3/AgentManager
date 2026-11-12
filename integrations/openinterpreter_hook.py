#!/usr/bin/env python
"""Open Interpreter hook for Agent Manager (stdlib only, one script for all events).

Reads the hook payload (JSON) from stdin, forwards it to the Agent Manager
bridge and, for a critical PreToolUse, blocks (long-poll) until the operator
approves or rejects it from the web UI or the TUI.

Environment:
    AGENT_MANAGER_URL         Manager base URL (default http://127.0.0.1:8765)
    AGENT_MANAGER_AGENT_ID    Agent id (default: "oi-" + slug of the cwd basename)
    AGENT_MANAGER_AGENT_NAME  Display name (default: the agent id)

Failure policy: FAIL-OPEN. If the Manager is unreachable or stdin is invalid,
a warning goes to stderr and the script exits 0, so Open Interpreter's native
approval_policy keeps acting as the safety net.

# INTEGRATION POINT: register this script in hooks.json (see hooks.json.example).
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8765"
LONG_POLL_WAIT_S = 25


def _warn(message: str) -> None:
    sys.stderr.write(f"[agent-manager] unreachable: {message}\n")
    sys.stderr.flush()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "-", value.lower())[:60]


def _agent_id(payload: dict) -> str:
    env_id = os.environ.get("AGENT_MANAGER_AGENT_ID")
    if env_id:
        return env_id
    cwd = payload.get("cwd")
    base = ""
    if isinstance(cwd, str):
        parts = [p for p in re.split(r"[\\/]+", cwd) if p]
        base = parts[-1] if parts else ""
    return "oi-" + (_slug(base) or "unknown")


def _request(base_url: str, method: str, path: str, body: dict | None = None, timeout: float = 10) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base_url + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{exc.code} {exc.read().decode('utf-8', 'replace')}") from None
    return json.loads(raw) if raw else {}


def _deny(reason: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"Rechazado desde Agent Manager: {reason}",
        }
    }
    sys.stdout.write(json.dumps(out))
    sys.stdout.flush()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("payload is not a JSON object")
    except (ValueError, OSError) as exc:
        _warn(f"invalid stdin: {exc}")
        return 0

    base_url = os.environ.get("AGENT_MANAGER_URL", DEFAULT_URL).rstrip("/")
    agent_id = _agent_id(payload)
    agent_name = os.environ.get("AGENT_MANAGER_AGENT_NAME") or agent_id

    try:
        res = _request(
            base_url,
            "POST",
            "/api/hooks/openinterpreter",
            {"agent_id": agent_id, "agent_name": agent_name, "payload": payload},
        )
        if res.get("action") != "pending":
            return 0

        approval = res["approval"]
        while approval["status"] == "pending":
            approval = _request(
                base_url, "GET", f"/api/approvals/{approval['id']}?wait={LONG_POLL_WAIT_S}", timeout=35
            )
    except Exception as exc:  # noqa: BLE001 - fail-open on any transport/protocol error
        _warn(str(exc))
        return 0

    if approval["status"] != "approved":
        _deny(approval.get("reason") or approval["status"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
