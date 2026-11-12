// Client-side state store plus small DOM/time helpers shared by the modules.

const MAX_LOGS = 500;

export function createStore() {
  const state = {
    agents: new Map(),
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
