// Client-side state store plus small DOM/time helpers shared by the modules.

const MAX_LOGS = 500;

export function createStore() {
  const state = {
    agents: new Map(),
    projects: new Map(), // id -> { id, name, path, room }
    approvals: new Map(), // pending only
    logs: [],
    connected: false,
    lastEventAt: null,
    // Bookkeeping for incremental renderers.
    logOffset: 0, // number of logs dropped from the front of `logs`
    snapshotSeq: 0, // bumped on every snapshot
  };
  const subscribers = new Set();
  let scheduled = false;

  function flush() {
    scheduled = false;
    for (const fn of subscribers) fn(state);
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(flush);
    else setTimeout(flush, 16);
  }

  function apply(event) {
    if (!event || typeof event !== "object") return;
    const data = event.data;
    switch (event.type) {
      case "snapshot": {
        state.agents = new Map((data?.agents ?? []).map((a) => [a.id, a]));
        state.projects = new Map((data?.projects ?? []).map((p) => [p.id, p]));
        state.approvals = new Map(
          (data?.approvals ?? []).filter((a) => a.status === "pending").map((a) => [a.id, a]),
        );
        state.logs = (data?.logs ?? []).slice(-MAX_LOGS);
        state.logOffset = 0;
        state.snapshotSeq += 1;
        break;
      }
      case "agent":
        if (!data?.id) return;
        state.agents.set(data.id, data);
        break;
      case "agent_removed":
        if (!data?.id) return;
        state.agents.delete(data.id);
        break;
      case "project":
        if (!data?.id) return;
        state.projects.set(data.id, data);
        break;
      case "project_removed":
        if (!data?.id) return;
        state.projects.delete(data.id);
        break;
      case "approval":
        if (!data?.id) return;
        if (data.status === "pending") state.approvals.set(data.id, data);
        else state.approvals.delete(data.id);
        break;
      case "log": {
        if (!data) return;
        state.logs.push(data);
        const drop = state.logs.length - MAX_LOGS;
        if (drop > 0) {
          state.logs.splice(0, drop);
          state.logOffset += drop;
        }
        break;
      }
      default:
        return;
    }
    state.lastEventAt = Date.now();
    schedule();
  }

  function setConnected(connected) {
    if (state.connected === connected) return;
    state.connected = connected;
    schedule();
  }

  function subscribe(fn) {
    subscribers.add(fn);
    return () => subscribers.delete(fn);
  }

  return { state, apply, setConnected, subscribe };
}

// Room index of an agent: its project's room, or 0 (main office).
export function roomOf(agent, projects) {
  return projects.get(agent.project)?.room ?? 0;
}

export const MAIN_ROOM_TITLE = "OFICINA PRINCIPAL";

// Rooms in index order: [{ index, title, project, agents, working }]. Agents
// are in desk-slot order: the room's own project agents first, then agents
// without a project (runtime / config / simulator) that live in room 0.
export function listRooms(state) {
  const rooms = new Map();
  const ensure = (index) => {
    if (!rooms.has(index)) rooms.set(index, { index, title: "", project: null, agents: [], working: 0 });
    return rooms.get(index);
  };
  ensure(0);
  for (const project of state.projects.values()) ensure(project.room).project = project;
  for (const agent of state.agents.values()) {
    const room = ensure(roomOf(agent, state.projects));
    room.agents.push(agent);
    if (agent.status === "working") room.working += 1;
  }
  const rank = (a) => (a.project && state.projects.has(a.project) ? 0 : 1);
  for (const room of rooms.values()) {
    room.agents.sort(
      (a, b) =>
        rank(a) - rank(b) ||
        (a.desk ?? 0) - (b.desk ?? 0) ||
        String(a.name).localeCompare(String(b.name)),
    );
    if (room.index === 0) {
      room.title = room.project ? `${MAIN_ROOM_TITLE} · ${room.project.name}` : MAIN_ROOM_TITLE;
    } else {
      room.title = room.project?.name ?? `SALA ${room.index + 1}`;
    }
  }
  return [...rooms.values()].sort((a, b) => a.index - b.index);
}

// ISO-8601 string -> epoch ms. Strings without a timezone are treated as UTC.
export function parseTs(iso) {
  if (!iso) return NaN;
  const s = String(iso);
  return Date.parse(/(Z|[+-]\d\d:?\d\d)$/i.test(s) ? s : `${s}Z`);
}

// epoch ms | ISO string -> "hh:mm:ss" (local time)
export function fmtTime(value) {
  const ms = typeof value === "number" ? value : parseTs(value);
  if (Number.isNaN(ms)) return "--:--:--";
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

// DOM builder: only ever sets textContent (agent-provided text is untrusted).
export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
