"""omp (oh-my-pi) integration: per-project agent rosters + live session watcher.

Read-only and driven by the projects omp is actually used in (nothing is hard-coded):

* ``discover_roster``  - the agent *definitions* omp would offer in a project:
  nearest ``<project>/.omp/agents/*.md``, then ``~/.omp/agent/agents/*.md``, then the
  bundled agents (first name wins, like omp's own discovery). Each definition's model
  is resolved through ``modelRoles`` in omp's ``config.yml``.
* ``ProjectsWatcher`` - opens one room per active project and tails its omp session files
  (``<agent dir>/sessions/<project slug>/<session>.jsonl`` and the per-subagent
  ``<session>/<Name>.jsonl`` files) to light the matching roster desks.

Only structural fields are read (model, stop reason, tool name, intent). Usage and cost
records present in those files are deliberately ignored.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import yaml

from .models import AgentState, ProjectState, Status

# Bundled omp agents are embedded in the omp binary (no file to read).
BUNDLED_AGENTS = {
    "task": "General-purpose subagent",
    "scout": "Read-only codebase scout",
    "reviewer": "Code review",
    "security-reviewer": "Security review",
    "sonic": "Mechanical low-reasoning agent",
}
IDLE_AFTER_S = 300  # unfinished work with no file activity for this long is shown as paused
ACTIVE_S = 900  # a session with activity inside this window makes its project "active" (opens a room)
CLOSE_GRACE_S = 60  # an inactive project's room closes after this long
DISCOVERY_INTERVAL_S = 10  # how often active projects / rosters are re-discovered
FRESH_S = 3600  # session files untouched for longer than this are not live: shown offline / not listed
MAX_LINE_BYTES = 64 * 1024 * 1024


def agent_dir() -> Path:
    env = os.environ.get("PI_CODING_AGENT_DIR")
    return Path(env).expanduser() if env else Path.home() / ".omp" / "agent"


def slug(name: str, prefix: str = "") -> str:
    text = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-") or "agent"
    return (prefix + text)[:64].strip("-") or "agent"


def project_key(path: Path) -> str:
    digest = hashlib.sha1(os.path.normcase(str(path)).encode()).hexdigest()[:6]
    return f"{slug(path.name)[:40]}-{digest}"


def main_agent_id(key: str) -> str:
    return f"{key}--main"


def agent_id_for(key: str, name: str) -> str:
    return slug(name, f"{key}--")


# --------------------------------------------------------------------------- roster


@dataclass
class AgentDef:
    name: str
    description: str = ""
    model: str | None = None  # first selector of the frontmatter list, unresolved (may be "@role")
    source: str = "user"  # project | user | bundled


def _frontmatter(path: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.match(r"^---\s*\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1).replace("\t", "  "))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _load_defs(directory: Path, source: str) -> list[AgentDef]:
    defs: list[AgentDef] = []
    for path in sorted(directory.glob("*.md")) if directory.is_dir() else []:
        meta = _frontmatter(path)
        if not meta or not isinstance(meta.get("name"), str) or not isinstance(meta.get("description"), str):
            continue  # omp skips invalid definitions too
        model = meta.get("model")
        if isinstance(model, str):
            model = model.split(",")[0].strip()
        elif isinstance(model, list) and model:
            model = str(model[0]).strip()
        else:
            model = None
        defs.append(AgentDef(meta["name"].strip(), meta["description"].strip(), model or None, source))
    return defs


def _nearest_project_agents_dir(project: Path) -> Path | None:
    for directory in [project, *project.parents]:
        candidate = directory / ".omp" / "agents"
        if candidate.is_dir():
            return candidate
    return None


def load_agent_defs(project: Path, home_agent_dir: Path) -> list[AgentDef]:
    seen: set[str] = set()
    result: list[AgentDef] = []
    project_dir = _nearest_project_agents_dir(project)
    groups = [
        _load_defs(project_dir, "project") if project_dir else [],
        _load_defs(home_agent_dir / "agents", "user"),
        [AgentDef(name, desc, None, "bundled") for name, desc in BUNDLED_AGENTS.items()],
    ]
    for group in groups:
        for definition in group:
            if definition.name not in seen:
                seen.add(definition.name)
                result.append(definition)
    return result


@dataclass
class ModelConfig:
    roles: dict[str, str] = field(default_factory=dict)
    agent_overrides: dict[str, str] = field(default_factory=dict)

    def resolve(self, selector: str | None) -> str | None:
        """Expand an ``@role`` alias through modelRoles; concrete selectors pass through."""
        if not selector:
            return None
        if selector.startswith("@"):
            return self.roles.get(selector[1:])
        return selector


def load_model_config(project: Path, home_agent_dir: Path) -> ModelConfig:
    config = ModelConfig()
    # Global first, project overlay second. The project overlay file name is an
    # assumption (unverified); a missing file is simply ignored.
    for path in (home_agent_dir / "config.yml", project / ".omp" / "config.yml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        roles = data.get("modelRoles")
        if isinstance(roles, dict):
            config.roles.update({str(k): str(v) for k, v in roles.items()})
        task_cfg = data.get("task")
        overrides = task_cfg.get("agentModelOverrides") if isinstance(task_cfg, dict) else None
        if isinstance(overrides, dict):
            config.agent_overrides.update({str(k): str(v) for k, v in overrides.items()})
    return config


def agent_model(definition: AgentDef, cfg: ModelConfig) -> str | None:
    selector = cfg.agent_overrides.get(definition.name) or definition.model
    # Without an explicit model omp falls back to the parent's active model.
    return cfg.resolve(selector) or cfg.roles.get("default")


def discover_roster(project: Path, key: str, home_agent_dir: Path | None = None) -> list[AgentState]:
    """Agents omp would offer in ``project`` (room ``key``): main session first, then definitions."""
    home = home_agent_dir or agent_dir()
    cfg = load_model_config(project, home)
    agents = [
        AgentState(
            id=main_agent_id(key),
            name="Sesión principal",
            role="omp main",
            model=cfg.roles.get("default"),
            project=key,
            desk=0,
            source="config",
            status=Status.offline,
        )
    ]
    for index, definition in enumerate(load_agent_defs(project, home), start=1):
        agents.append(
            AgentState(
                id=agent_id_for(key, definition.name),
                name=definition.name,
                role=definition.source,
                model=agent_model(definition, cfg),
                project=key,
                desk=index,
                source="config",
                status=Status.idle,
                detail="Disponible",
            )
        )
    return agents


# --------------------------------------------------------------------------- sessions


def _read_header_cwd(path: Path) -> str | None:
    try:
        with path.open("rb") as fh:
            for _ in range(3):
                line = fh.readline(1_000_000)
                if b'"type":"session"' in line[:40]:
                    return json.loads(line).get("cwd")
    except (OSError, ValueError):
        return None
    return None


def _same_path(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def find_sessions_dir(project: Path, home_agent_dir: Path) -> Path | None:
    root = home_agent_dir / "sessions"
    if not root.is_dir():
        return None
    candidates: list[Path] = []
    try:
        rel = project.relative_to(Path.home())
        candidates.append(root / ("-" + "-".join(rel.parts)))
    except ValueError:
        pass
    candidates.extend(d for d in root.iterdir() if d.is_dir() and d not in candidates)
    for directory in candidates:
        if not directory.is_dir():
            continue
        files = sorted(directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[:1]:
            cwd = _read_header_cwd(path)
            if cwd and _same_path(cwd, project):
                return directory
    return None


def _session_activity(path: Path) -> float:
    latest = path.stat().st_mtime
    children = path.with_suffix("")
    if children.is_dir():
        for child in children.glob("*.jsonl"):
            latest = max(latest, child.stat().st_mtime)
    return latest


def _quiet_for(path: Path) -> float:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return 0.0


def newest_session(directory: Path) -> Path | None:
    best: tuple[float, Path] | None = None
    for path in directory.glob("*.jsonl"):
        try:
            stamp = _session_activity(path)
        except OSError:
            continue
        if best is None or stamp > best[0]:
            best = (stamp, path)
    return best[1] if best else None


@dataclass
class Update:
    key: str  # file path, stable per agent
    name: str
    role: str
    model: str | None
    status: Status
    task: str
    detail: str
    error_kind: str | None
    logs: list[tuple[str, str]] = field(default_factory=list)
    is_main: bool = False
    definition: str = ""  # agent definition name (subagents only)
    activity: float = 0.0  # file mtime, to pick the most recent instance


class Tracker:
    """Incrementally folds one omp session file into an agent snapshot."""

    def __init__(self, path: Path, is_main: bool, default_model: str | None) -> None:
        self.path = path
        self.is_main = is_main
        self.offset = 0
        self.buffer = b""
        self.replayed = False
        self.model = default_model
        self.definition = ""
        self.status = Status.working if not is_main else Status.idle
        self.task = ""
        self.detail = ""
        self.error_kind: str | None = None
        self.exited = False
        self.logs: list[tuple[str, str]] = []

    # -- file reading ---------------------------------------------------------

    def _lines(self) -> Iterator[bytes]:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.offset:  # truncated / rewritten
            self.offset, self.buffer = 0, b""
        with self.path.open("rb") as fh:
            fh.seek(self.offset)
            while chunk := fh.read(1 << 20):
                self.offset += len(chunk)
                self.buffer += chunk
                *lines, self.buffer = self.buffer.split(b"\n")
                yield from lines
                if len(self.buffer) > MAX_LINE_BYTES:
                    self.buffer = b""

    # -- event folding -----------------------------------------------------------

    def _finish_turn(self) -> None:
        self.error_kind = None
        self.task = ""
        if self.is_main:
            self.status, self.detail = Status.waiting_input, "Esperando tu input"
        else:
            self.status, self.detail = Status.idle, "Tarea completada"

    def _handle(self, line: bytes) -> None:
        head = line[:200]
        if b'"type":"model_change"' in head:
            event = json.loads(line)
            if self.is_main or str(event.get("role", "")).startswith("subagent:"):
                self.model = event.get("model") or self.model
        elif b'"type":"session_init"' in head:
            event = json.loads(line)
            self.definition = str(event.get("agent") or "")
            self.model = event.get("resolvedModel") or self.model
        elif b'"type":"custom"' in head:
            if b"session_exit" in line[:400]:
                self.exited = True
                self.task = ""
                if self.is_main:
                    self.status, self.detail = Status.offline, "Sesión cerrada"
                elif self.status == Status.working:
                    self.status, self.detail = Status.idle, "Sesión cerrada"
        elif b'"type":"message"' in line[:120]:
            self._handle_message(line)

    def _handle_message(self, line: bytes) -> None:
        marker = line.find(b'"role":"', 0, 600)
        role = line[marker + 8 : marker + 24].split(b'"', 1)[0].decode() if marker >= 0 else ""
        self.exited = False
        if role == "toolResult":
            self.status, self.error_kind = Status.working, None
        elif role == "user":
            self.status, self.error_kind = Status.working, None
            self.task, self.detail = "", "Procesando" if self.is_main else "Tarea recibida"
        elif role == "assistant":
            message = json.loads(line).get("message", {})
            calls = [c for c in message.get("content", []) if isinstance(c, dict) and c.get("type") == "toolCall"]
            stop = message.get("stopReason")
            if stop == "error":
                text = str(message.get("errorMessage") or "")
                lowered = text.lower()
                self.status = Status.error
                self.error_kind = "rate_limit" if ("429" in text or "rate" in lowered or "quota" in lowered) else "crash"
                self.detail = "Límite de uso del proveedor" if self.error_kind == "rate_limit" else text[:120]
            elif stop == "aborted":
                self.status, self.error_kind, self.task, self.detail = Status.paused, None, "", "Interrumpido"
            elif calls and stop != "stop":
                self.status, self.error_kind = Status.working, None
                self.task = ", ".join(str(c.get("name", "")) for c in calls[:2])
                last = calls[-1]
                args = last.get("arguments") if isinstance(last.get("arguments"), dict) else {}
                intent = str(last.get("intent") or args.get("i") or "")
                self.detail = intent[:160]
                for call in calls:
                    call_args = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
                    label = str(call.get("intent") or call_args.get("i") or "")
                    self.logs.append(("info", f"{call.get('name', '?')}: {label}".rstrip(": ")))
            else:
                self._finish_turn()
                text = " ".join(
                    str(c.get("text", "")) for c in message.get("content", []) if isinstance(c, dict) and c.get("type") == "text"
                ).strip()
                if text:
                    self.logs.append(("info", f"Respuesta: {text[:200]}"))

    # -- public ---------------------------------------------------------------------

    def advance(self) -> Update:
        for line in self._lines():
            if not line.strip():
                continue
            try:
                self._handle(line)
            except (ValueError, AttributeError, TypeError):
                continue  # a malformed line must never stop the watcher
        logs = [] if not self.replayed else self.logs
        self.logs = []
        self.replayed = True
        return self.snapshot(logs)

    def snapshot(self, logs: list[tuple[str, str]]) -> Update:
        status, detail = self.status, self.detail
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            mtime = time.time()
        quiet_s = time.time() - mtime
        if quiet_s > FRESH_S and status != Status.offline:
            status, detail = Status.offline, "Sesión inactiva"
        elif status == Status.working and quiet_s > IDLE_AFTER_S:
            status, detail = Status.paused, "Sin actividad reciente"
        return Update(
            key=str(self.path),
            name="Sesión principal" if self.is_main else self.path.stem,
            role="omp main" if self.is_main else self.definition,
            model=self.model,
            status=status,
            task=self.task,
            detail=detail,
            error_kind=self.error_kind if status == Status.error else None,
            logs=logs,
            is_main=self.is_main,
            definition=self.definition,
            activity=mtime,
        )


class SessionScanner:
    """Synchronous core of the watcher (runs in a worker thread)."""

    def __init__(self, project: Path, home_agent_dir: Path | None = None) -> None:
        self.project = project
        self.home = home_agent_dir or agent_dir()
        self.cfg = load_model_config(project, self.home)
        self.sessions_dir: Path | None = None
        self.current: Path | None = None
        self.trackers: dict[Path, Tracker] = {}

    def scan(self) -> list[Update]:
        if self.sessions_dir is None or not self.sessions_dir.is_dir():
            self.sessions_dir = find_sessions_dir(self.project, self.home)
        if self.sessions_dir is None:
            return []
        newest = newest_session(self.sessions_dir)
        if newest is None:
            return []
        updates: list[Update] = []
        if newest != self.current:
            self.current = newest  # new session: instances of the previous one are over
            self.trackers = {}
        files = [(newest, True)]
        children = newest.with_suffix("")
        if children.is_dir():
            files += [(p, False) for p in sorted(children.glob("*.jsonl"))]
        for path, is_main in files:
            tracker = self.trackers.get(path)
            if tracker is None and not is_main and _quiet_for(path) > FRESH_S:
                continue  # a long-finished subagent of this session is not worth tracking
            if tracker is None:
                tracker = self.trackers[path] = Tracker(path, is_main, self.cfg.roles.get("default") if is_main else None)
            updates.append(tracker.advance())
        return updates


_RANK = {Status.working: 4, Status.error: 3, Status.paused: 2, Status.idle: 1, Status.offline: 0}


def aggregate(group: list[Update]) -> tuple[Status, str, str, str | None]:
    """Fold the running instances of one agent definition into its desk's state.

    working beats error beats paused beats idle; ties go to the most recently active file.
    """
    best = max(group, key=lambda u: (_RANK.get(u.status, 1), u.activity))
    if best.status == Status.offline:  # long-quiet instances: the desk is simply available
        return Status.idle, "", "Disponible", None
    detail = best.detail
    parallel = sum(1 for u in group if u.status == Status.working) - 1
    if best.status == Status.working and parallel > 0:
        detail = f"{detail} (+{parallel} en paralelo)".strip()
    return best.status, best.task, detail, best.error_kind


def session_exited(path: Path) -> bool:
    """True when the last line of a session file is the ``session_exit`` marker."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            fh.seek(max(0, size - 4096))
            tail = fh.read()
    except OSError:
        return False
    lines = [raw for raw in tail.split(b"\n") if raw.strip()]
    return bool(lines) and b'"session_exit"' in lines[-1]


def discover_active_projects(home: Path, now: float) -> set[Path]:
    """Projects (by session header cwd) with a live omp session: recent activity, not exited."""
    root = home / "sessions"
    found: set[Path] = set()
    if not root.is_dir():
        return found
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        newest = newest_session(directory)
        if newest is None:
            continue
        try:
            if now - _session_activity(newest) > ACTIVE_S:
                continue
        except OSError:
            continue
        if session_exited(newest):
            continue
        cwd = _read_header_cwd(newest)
        if cwd and Path(cwd).is_dir():
            found.add(Path(cwd).resolve())
    return found


@dataclass
class ProjectRuntime:
    """One open room."""

    path: Path
    key: str
    room: int
    pinned: bool
    scanner: SessionScanner
    last: dict[str, tuple] = field(default_factory=dict)
    driven: set[str] = field(default_factory=set)  # roster desks currently driven by running instances
    inactive_since: float | None = None


class ProjectsWatcher:
    """Opens one room per active omp project and keeps its agents' status in the hub.

    Pinned projects (``--project`` / cwd) always have a room; discovered ones open while
    their omp session is live and close CLOSE_GRACE_S after it ends. Rooms only ever hold
    roster agents: running subagents light their roster desk, nothing is created from
    session files.
    """

    def __init__(
        self,
        hub: Any,
        pinned: list[Path],
        discover: bool,
        poll_s: float = 2.0,
        home_agent_dir: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.hub = hub
        self.pinned = [p.resolve() for p in pinned]
        self.discover = discover
        self.poll_s = poll_s
        self.home = home_agent_dir or agent_dir()
        self.clock = clock
        self.runtimes: dict[str, ProjectRuntime] = {}
        self._active: set[Path] = set()
        self._last_discovery: float | None = None

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the watcher must survive odd files
                await self.hub.log(None, "error", f"omp watcher: {exc}")
                await asyncio.sleep(self.poll_s * 5)
            await asyncio.sleep(self.poll_s)

    async def tick(self) -> None:
        now = self.clock()
        discovery_tick = self._last_discovery is None or now - self._last_discovery >= DISCOVERY_INTERVAL_S
        if discovery_tick:
            self._last_discovery = now
            if self.discover:
                self._active = await asyncio.to_thread(discover_active_projects, self.home, now)
        pinned_keys = {project_key(p) for p in self.pinned}
        wanted = {project_key(p): p for p in [*self.pinned, *sorted(self._active, key=str)]}
        for key, path in wanted.items():
            if key not in self.runtimes:
                await self._open(key, path, key in pinned_keys)
        for key, rt in list(self.runtimes.items()):
            if key in wanted:
                rt.inactive_since = None
            else:
                if rt.inactive_since is None:
                    rt.inactive_since = now
                if now - rt.inactive_since >= CLOSE_GRACE_S:
                    await self.hub.remove_project(key)
                    del self.runtimes[key]
                    continue
            await self._apply(rt, await asyncio.to_thread(rt.scanner.scan))
            if discovery_tick:
                await self._refresh_roster(rt)

    async def _open(self, key: str, path: Path, pinned: bool) -> None:
        used = {rt.room for rt in self.runtimes.values()}
        room = next(i for i in range(len(used) + 1) if i not in used)
        self.runtimes[key] = ProjectRuntime(path, key, room, pinned, SessionScanner(path, self.home))
        await self.hub.upsert_project(ProjectState(id=key, name=path.name, path=str(path), room=room))
        for agent in discover_roster(path, key, self.home):
            await self.hub.put_agent(agent)
        await self.hub.log(None, "system", f"Proyecto abierto: {path.name} (sala {room + 1})")

    async def _refresh_roster(self, rt: ProjectRuntime) -> None:
        """Pick up added/removed agent definitions and model changes."""
        hub = self.hub
        fresh = discover_roster(rt.path, rt.key, self.home)
        main_id = main_agent_id(rt.key)
        for agent in fresh:
            current = hub.agents.get(agent.id)
            if agent.id == main_id and current is not None and current.model:
                agent.model = current.model  # the session's real model beats the configured default
            await hub.put_agent(agent)
        ids = {a.id for a in fresh}
        for agent in [a for a in hub.agents.values() if a.project == rt.key and a.source == "config"]:
            if agent.id not in ids:
                await hub.remove_agent(agent.id)
                rt.last.pop(agent.id, None)
                rt.driven.discard(agent.id)

    async def _apply(self, rt: ProjectRuntime, updates: list[Update]) -> None:
        """Light roster desks. Instances whose definition is not on the roster are ignored."""
        hub = self.hub
        main_id = main_agent_id(rt.key)
        groups: dict[str, list[Update]] = {}
        for update in updates:
            if update.is_main:
                agent = hub.agents.get(main_id)
                if agent is not None and agent.source == "config":
                    if update.model and agent.model != update.model:
                        await hub.upsert_agent(main_id, model=update.model)
                    await self._push(rt, main_id, update.status, update.task, update.detail, update.error_kind)
                continue
            if not update.definition:
                continue
            agent_id = agent_id_for(rt.key, update.definition)
            agent = hub.agents.get(agent_id)
            if agent is None or agent.source != "config" or agent.project != rt.key:
                continue
            groups.setdefault(agent_id, []).append(update)
            for level, message in update.logs:
                await hub.log(agent_id, level, f"{update.name}: {message}")
        for agent_id, group in groups.items():
            await self._push(rt, agent_id, *aggregate(group))
        for agent_id in rt.driven - groups.keys():  # no running instance any more
            await self._push(rt, agent_id, Status.idle, "", "Disponible", None)
        rt.driven = set(groups)

    async def _push(
        self, rt: ProjectRuntime, agent_id: str, status: Status, task: str, detail: str, error_kind: str | None
    ) -> None:
        if agent_id not in self.hub.agents:
            return
        state = (status, task, detail, error_kind)
        if rt.last.get(agent_id) != state:
            rt.last[agent_id] = state
            await self.hub.set_status(agent_id, status, task=task, detail=detail, error_kind=error_kind)
