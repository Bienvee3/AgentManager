"""Status labels, tones and colours (single source for the TUI and hub logs)."""

from __future__ import annotations

from typing import Any

STATUS_LABELS: dict[str, str] = {
    "idle": "INACTIVO",
    "working": "TRABAJANDO",
    "paused": "EN PAUSA",
    "waiting_input": "ESPERANDO INPUT",
    "waiting_approval": "ESPERANDO APROBACIÓN",
    "error": "ERROR",
    "offline": "DESCONECTADO",
}

STATUS_TONES: dict[str, str] = {
    "idle": "idle",
    "working": "ok",
    "paused": "warn",
    "waiting_input": "warn",
    "waiting_approval": "hitl",
    "error": "err",
    "offline": "off",
}

ERROR_KIND_LABELS: dict[str, str] = {
    "rate_limit": "ERROR: RATE LIMIT",
    "crash": "ERROR: CAÍDA",
    "lost": "ERROR: SIN SEÑAL",
}

TONE_COLORS: dict[str, str] = {
    "ok": "#3ddc84",
    "err": "#ff4d4d",
    "warn": "#ffd23f",
    "hitl": "#ff8c1a",
    "idle": "#8d99ae",
    "off": "#4a4e69",
}


def _get(agent: Any, key: str) -> Any:
    """Read a field from a pydantic model or a plain dict (TUI store)."""
    if isinstance(agent, dict):
        return agent.get(key)
    return getattr(agent, key, None)


def status_value(agent: Any) -> str:
    status = _get(agent, "status")
    return getattr(status, "value", status) or "idle"


def status_label(agent: Any) -> str:
    status = status_value(agent)
    if status == "error":
        return ERROR_KIND_LABELS.get(_get(agent, "error_kind") or "", STATUS_LABELS["error"])
    return STATUS_LABELS.get(status, status.upper())


def status_text(agent: Any) -> str:
    text = f"ESTADO: {status_label(agent)}"
    task = (_get(agent, "task") or "").strip()
    if task:
        text += f" ({task.upper()})"
    return text
