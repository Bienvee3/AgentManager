"""Rich terminal UI: live agent board with keyboard HITL approvals.

Pure helpers (``Store``, ``clamp_selection``, ``build_layout`` and the
``render_*`` functions) are separate from the Live/keyboard loop in ``run_tui``.
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any

from rich.columns import Columns
from rich.console import Group, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from . import labels

try:  # Windows-only keyboard input
    import msvcrt  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - non-Windows
    msvcrt = None  # type: ignore[assignment]

LOG_CAP = 500
VISIBLE_LOGS = 14
READ_ONLY_FOOTER = "Modo solo lectura (teclas HITL solo en Windows)"
KEYS_FOOTER = "[↑/↓] seleccionar  [A] aprobar  [R] rechazar  [Q] salir"

LEVEL_COLORS = {
    "info": "white",
    "warn": labels.TONE_COLORS["warn"],
    "error": labels.TONE_COLORS["err"],
    "hitl": labels.TONE_COLORS["hitl"],
    "system": "#4cc9f0",
}

DESK_ART = ("  ▄▄▄  ", "[■■■] o", "▔▔▔▔▔▔▔")


# --------------------------------------------------------------------------
# Store (same semantics as web/js/store.js)
# --------------------------------------------------------------------------


class Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.agents: dict[str, dict] = {}
        self.projects: dict[str, dict] = {}
        self.approvals: dict[str, dict] = {}  # pending only
        self.logs: list[dict] = []
        self.connected = False
        self.last_event_at: float | None = None

    def apply(self, event: dict) -> None:
        etype = event.get("type")
        data = event.get("data")
        with self._lock:
            if etype == "snapshot":
                data = data or {}
                self.agents = {a["id"]: a for a in data.get("agents", [])}
                self.projects = {p["id"]: p for p in data.get("projects", [])}
                self.approvals = {
                    a["id"]: a for a in data.get("approvals", []) if a.get("status") == "pending"
                }
                self.logs = list(data.get("logs", []))[-LOG_CAP:]
            elif etype == "agent" and data:
                self.agents[data["id"]] = data
            elif etype == "agent_removed" and data:
                self.agents.pop(data["id"], None)
            elif etype == "project" and data:
                self.projects[data["id"]] = data
            elif etype == "project_removed" and data:
                self.projects.pop(data["id"], None)
            elif etype == "approval" and data:
                if data.get("status") == "pending":
                    self.approvals[data["id"]] = data
                else:
                    self.approvals.pop(data["id"], None)
            elif etype == "log" and data:
                self.logs.append(data)
                if len(self.logs) > LOG_CAP:
                    del self.logs[: len(self.logs) - LOG_CAP]
            else:
                return
            self.last_event_at = time.time()

    def set_connected(self, value: bool) -> None:
        with self._lock:
            self.connected = value

    def view(self) -> dict[str, Any]:
        """Consistent copy of the state for rendering."""
        with self._lock:
            return {
                "agents": copy.deepcopy(self.agents),
                "projects": copy.deepcopy(self.projects),
                "approvals": copy.deepcopy(self.approvals),
                "logs": list(self.logs),
                "connected": self.connected,
                "last_event_at": self.last_event_at,
            }


def sorted_agents(view: dict) -> list[dict]:
    projects = view.get("projects", {})

    def room(agent: dict) -> int:
        return projects.get(agent.get("project"), {}).get("room", 0)

    return sorted(view["agents"].values(), key=lambda a: (room(a), a.get("desk", 0), a.get("name", "")))


def sorted_approvals(view: dict) -> list[dict]:
    return sorted(view["approvals"].values(), key=lambda a: (a.get("created_at") or "", a.get("id", "")))


def clamp_selection(selected: int, count: int) -> int:
    """Nearest valid index (0 when the list is empty)."""
    if count <= 0:
        return 0
    return max(0, min(selected, count - 1))


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _tone_color(agent: dict) -> str:
    return labels.TONE_COLORS[labels.STATUS_TONES.get(labels.status_value(agent), "idle")]


def render_header(view: dict) -> Panel:
    agents = list(view["agents"].values())
    count = lambda s: sum(1 for a in agents if labels.status_value(a) == s)  # noqa: E731
    text = Text()
    text.append("AGENT MANAGER", style="bold")
    text.append("  ")
    if view["connected"]:
        text.append("● CONECTADO", style=labels.TONE_COLORS["ok"])
    else:
        text.append("● DESCONECTADO", style=labels.TONE_COLORS["err"])
    text.append(
        f"   agentes: {len(agents)}  trabajando: {count('working')}  "
        f"HITL: {len(view['approvals'])}  errores: {count('error')}"
    )
    return Panel(text, style="on default")


def render_agent(agent: dict, pending: list[dict], project_name: str | None = None) -> Panel:
    color = _tone_color(agent)
    lines: list[RenderableType] = [Text(row, style=color) for row in DESK_ART]
    if agent.get("model"):
        lines.append(Text(f"modelo: {str(agent['model']).split('/')[-1]}", style="dim"))
    lines.append(Text(labels.status_text(agent), style=f"bold {color}"))
    if agent.get("detail"):
        lines.append(Text(agent["detail"], style="dim"))
    if pending:
        lines.append(Text(f"⚠ HITL: {pending[0].get('action', '')}", style=labels.TONE_COLORS["hitl"]))
    title = agent.get("name") or agent["id"]
    if project_name:
        title = f"{project_name} / {title}"
    if agent.get("role"):
        title = f"{title} · {agent['role']}"
    return Panel(Group(*lines), title=title, border_style=color, width=50)


def render_agents(view: dict) -> RenderableType:
    agents = sorted_agents(view)
    if not agents:
        return Panel(Text("SIN AGENTES — configura agents.yaml o registra uno vía API", style="dim"), title="agentes")
    approvals = sorted_approvals(view)
    projects = view.get("projects", {})
    panels = [
        render_agent(
            a,
            [p for p in approvals if p.get("agent_id") == a["id"]],
            projects.get(a.get("project"), {}).get("name"),
        )
        for a in agents
    ]
    return Panel(Columns(panels, expand=False), title="agentes", border_style="dim")


def render_approvals(view: dict, selected: int) -> Panel:
    approvals = sorted_approvals(view)
    if not approvals:
        body: RenderableType = Text("Sin aprobaciones pendientes", style="dim")
    else:
        selected = clamp_selection(selected, len(approvals))
        rows = []
        for i, ap in enumerate(approvals):
            line = f"{i + 1}. {ap.get('agent_id', '')} — {ap.get('action', '')} [{ap.get('kind', '')}]"
            rows.append(Text(line, style="reverse" if i == selected else labels.TONE_COLORS["hitl"], no_wrap=True, overflow="ellipsis"))
        body = Group(*rows)
    return Panel(body, title="aprobaciones", border_style=labels.TONE_COLORS["hitl"])


def _hhmmss(ts: str | None) -> str:
    # ISO-8601 "YYYY-MM-DDTHH:MM:SS..." -> HH:MM:SS (UTC as sent by the server)
    if ts and "T" in ts:
        return ts.split("T", 1)[1][:8]
    return ts or ""


def render_logs(view: dict) -> Panel:
    rows = []
    for entry in view["logs"][-VISIBLE_LOGS:]:
        who = entry.get("agent_id") or "SYSTEM"
        line = f"[{_hhmmss(entry.get('ts'))}] [{who}] {entry.get('message', '')}"
        rows.append(Text(line, style=LEVEL_COLORS.get(entry.get("level", "info"), "white"), no_wrap=True, overflow="ellipsis"))
    body: RenderableType = Group(*rows) if rows else Text("Sin logs", style="dim")
    return Panel(body, title="logs", border_style="dim")


def render_footer(message: str, interactive: bool) -> Panel:
    text = Text(KEYS_FOOTER if interactive else READ_ONLY_FOOTER)
    if message:
        text.append("   " + message, style="bold")
    return Panel(text)


def build_layout(view: dict, selected: int, message: str = "", interactive: bool = True) -> Layout:
    layout = Layout()
    layout.split_column(Layout(name="header", size=3), Layout(name="body"), Layout(name="footer", size=3))
    layout["body"].split_row(Layout(name="agents", ratio=3), Layout(name="right", ratio=2))
    layout["right"].split_column(
        Layout(name="approvals", size=max(5, min(12, len(view["approvals"]) + 2))),
        Layout(name="logs"),
    )
    layout["header"].update(render_header(view))
    layout["agents"].update(render_agents(view))
    layout["approvals"].update(render_approvals(view, selected))
    layout["logs"].update(render_logs(view))
    layout["footer"].update(render_footer(message, interactive))
    return layout


# --------------------------------------------------------------------------
# Runtime: websocket reader, HTTP actions, keyboard loop
# --------------------------------------------------------------------------


def _ws_url(url: str) -> str:
    base = url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    return base + "/ws"


def _reader(url: str, store: Store, stop: threading.Event) -> None:
    import json

    from websockets.sync.client import connect

    backoff = 1.0
    while not stop.is_set():
        try:
            with connect(_ws_url(url), open_timeout=5) as ws:
                store.set_connected(True)
                backoff = 1.0
                while not stop.is_set():
                    try:
                        raw = ws.recv(timeout=1)
                    except TimeoutError:
                        continue
                    store.apply(json.loads(raw))
        except Exception:  # noqa: BLE001 - any failure -> reconnect
            pass
        store.set_connected(False)
        if stop.wait(backoff):
            return
        backoff = min(backoff * 2, 10.0)


def decide(url: str, approval_id: str, approve: bool) -> str:
    """POST an approve/reject decision; return a footer message."""
    import httpx

    verb = "approve" if approve else "reject"
    body = {"via": "tui", "reason": "" if approve else "Rechazado desde la TUI"}
    try:
        res = httpx.post(f"{url.rstrip('/')}/api/approvals/{approval_id}/{verb}", json=body, timeout=10)
    except httpx.HTTPError as exc:
        return f"Error: {exc}"
    if res.status_code == 200:
        return "Aprobado" if approve else "Rechazado"
    return f"Error {res.status_code}: {res.text[:100]}"


def _read_key() -> str | None:
    """Return 'up', 'down', a lowercase char, or None. Requires msvcrt."""
    if msvcrt is None or not msvcrt.kbhit():
        return None
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        code = msvcrt.getwch()
        return {"H": "up", "P": "down"}.get(code)
    return ch.lower()


def run_tui(url: str) -> None:
    from rich.live import Live

    store = Store()
    stop = threading.Event()
    thread = threading.Thread(target=_reader, args=(url, store, stop), daemon=True)
    thread.start()
    interactive = msvcrt is not None
    selected = 0
    message = ""
    try:
        with Live(screen=True, refresh_per_second=4, auto_refresh=False) as live:
            while True:
                view = store.view()
                approvals = sorted_approvals(view)
                selected = clamp_selection(selected, len(approvals))
                key = _read_key() if interactive else None
                if key == "q":
                    break
                if key == "up":
                    selected = clamp_selection(selected - 1, len(approvals))
                elif key == "down":
                    selected = clamp_selection(selected + 1, len(approvals))
                elif key in ("a", "r"):
                    if approvals:
                        message = decide(url, approvals[selected]["id"], key == "a")
                    else:
                        message = "Sin aprobaciones pendientes"
                    view = store.view()
                live.update(build_layout(view, selected, message, interactive), refresh=True)
                time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
