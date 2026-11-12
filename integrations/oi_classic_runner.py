#!/usr/bin/env python
"""Run the classic ``open-interpreter`` library under Agent Manager supervision.

Run it from the virtualenv that hosts Open Interpreter. Only the stdlib-only
``agent_manager/client.py`` is imported from this repo.

    python integrations/oi_classic_runner.py --agent-id oi-classic --name "OI Classic" "list the files here"

Chunk contract (verified against Open Interpreter v0.4.2,
``core/respond.py:287-301`` and ``core/core.py:342-350``): with
``auto_run = False`` and ``stream=True`` the generator yields a
``{"type": "confirmation", ...}`` chunk before executing code. Resuming the
generator means "approve"; closing it (``GeneratorExit``) means "reject".

Failure policy: FAIL-CLOSED. In this mode the Manager is the only approval
interface, so if it becomes unreachable while a confirmation is pending the
code is rejected.

# INTEGRATION POINT: adapt ``run_prompt`` if your OI profile emits other chunks.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_manager.client import AgentManagerClient, AgentManagerUnavailable  # noqa: E402


def _best_effort(fn, *args, **kwargs) -> None:
    """Telemetry must never kill the agent if the Manager goes away."""
    try:
        fn(*args, **kwargs)
    except (AgentManagerUnavailable, RuntimeError):
        pass


def _first_line(text: str) -> str:
    lines = text.strip().splitlines()
    return lines[0] if lines else ""


def _confirm(client: AgentManagerClient, chunk: dict, approve_all: bool) -> bool:
    """Return True if the pending code execution may proceed."""
    content = chunk["content"]
    lang = str(content.get("format", ""))
    code = str(content.get("content", ""))
    action = f"Ejecutar {lang}: {_first_line(code)[:100]}"
    try:
        if approve_all or client.is_critical(code, tool_name=lang)[0]:
            decision = client.request_approval(action=action, details=code, kind="code_execution")
            if not decision.approved:
                _best_effort(
                    client.log, f"HITL rechazado: {action} ({decision.reason or decision.status})", "hitl"
                )
                _best_effort(client.status, "paused", detail="Ejecución rechazada")
                return False
            return True
    except AgentManagerUnavailable as exc:
        # Fail-closed: without the Manager nobody can approve this code.
        sys.stderr.write(f"[agent-manager] {exc}; rejecting code execution\n")
        return False
    _best_effort(client.log, f"Ejecución no crítica auto-aprobada: {action}")
    return True


def run_prompt(interpreter, client: AgentManagerClient, prompt: str, approve_all: bool) -> None:
    _best_effort(client.status, "working", task=prompt[:48], detail="")
    gen = interpreter.chat(prompt, display=False, stream=True)
    message_parts: list[str] = []
    last_task = None
    rejected = False
    try:
        for chunk in gen:
            ctype = chunk.get("type")
            if ctype == "confirmation":
                if not _confirm(client, chunk, approve_all):
                    gen.close()  # GeneratorExit inside OI: rejects the code
                    rejected = True
                    break
            elif ctype == "message" and chunk.get("role") == "assistant":
                if chunk.get("start"):
                    message_parts.clear()
                piece = chunk.get("content")
                if isinstance(piece, str):
                    message_parts.append(piece)
                if chunk.get("end"):
                    text = "".join(message_parts).strip()
                    message_parts.clear()
                    if text:
                        _best_effort(client.log, text[:2000])
            elif ctype == "console" and chunk.get("format") == "output":
                text = str(chunk.get("content", "")).strip()
                if text:
                    _best_effort(client.log, text[:500])
            elif ctype == "code":
                task = f"Ejecutando {chunk.get('format', '')}".strip()
                if task != last_task:
                    last_task = task
                    _best_effort(client.status, "working", task=task)
    except Exception as exc:
        kind = "rate_limit" if any("RateLimit" in c.__name__ for c in type(exc).__mro__) else "crash"
        _best_effort(client.status, "error", error_kind=kind, detail=str(exc)[:200])
        raise
    if not rejected:
        _best_effort(client.status, "idle", task="", detail="Tarea completada")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run classic open-interpreter under Agent Manager.")
    parser.add_argument("--agent-id", default="oi-classic", help="agent id (default: oi-classic)")
    parser.add_argument("--name", default=None, help="display name (default: the agent id)")
    parser.add_argument("--role", default="", help="agent role shown in the office")
    parser.add_argument(
        "--approve-all",
        action="store_true",
        help="ask for approval on every code execution, not only critical ones",
    )
    parser.add_argument("prompt", nargs="?", default=None, help="prompt; if omitted, ask interactively")
    args = parser.parse_args(argv)

    # Lazy import: --help and py_compile must work without Open Interpreter installed.
    from interpreter import interpreter

    interpreter.auto_run = False

    client = AgentManagerClient(args.agent_id, name=args.name, role=args.role)
    try:
        client.register()
    except AgentManagerUnavailable as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    client.start_heartbeat(15)

    failed = False
    try:
        if args.prompt:
            run_prompt(interpreter, client, args.prompt, args.approve_all)
        else:
            while True:
                try:
                    prompt = input("> ").strip()
                except EOFError:
                    break
                if prompt.lower() in ("exit", "quit"):
                    break
                if prompt:
                    run_prompt(interpreter, client, prompt, args.approve_all)
    except BaseException as exc:
        # Keep the error status visible in the Manager instead of overwriting it with "offline".
        failed = not isinstance(exc, KeyboardInterrupt)
        raise
    finally:
        if not failed:
            client.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
