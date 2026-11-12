// Front-end integration point: where the UI gets its data and what the
// APROBAR / RECHAZAR buttons do.

export const MANAGER_URL = window.location.origin;
export const WS_URL = MANAGER_URL.replace(/^http/, "ws") + "/ws";

// INTEGRATION POINT: initial state of the office.
// By default the snapshot comes from the Manager (GET /api/state). To feed the
// UI from another source, return an object with the same shape, e.g.
//   return { agents: [{ id: "my-bot", name: "My Bot", role: "ETL", avatar: 0,
//                       desk: 0, source: "config", status: "idle", task: "",
//                       detail: "", error_kind: null, last_seen: null,
//                       heartbeat_interval_s: null, pending_approvals: 0 }],
//            approvals: [], logs: [] };
// Live updates still arrive through the WebSocket (see main.js).
export async function loadInitialState(api) {
  return api.getState();
}

// INTEGRATION POINT: what happens when a human decides in the web UI.
// The default only talks to the Manager. To also notify your own backend add
// a request before returning, e.g.:
//   await fetch("http://localhost:XXXX/your-endpoint", {
//     method: "POST",
//     headers: { "Content-Type": "application/json" },
//     body: JSON.stringify(approval),
//   });
export const HITL_CALLBACKS = {
  async onApprove(approval, api) {
    return api.approve(approval.id, "");
  },
  async onReject(approval, api) {
    return api.reject(approval.id, "Rechazado desde la web");
  },
};

// Mirrors agent_manager/labels.py (STATUS_LABELS / STATUS_TONES / ERROR_KIND_LABELS).
export const STATUS_META = Object.freeze({
  idle: { label: "INACTIVO", tone: "idle" },
  working: { label: "TRABAJANDO", tone: "ok" },
  paused: { label: "EN PAUSA", tone: "warn" },
  waiting_input: { label: "ESPERANDO INPUT", tone: "warn" },
  waiting_approval: { label: "ESPERANDO APROBACIÓN", tone: "hitl" },
  error: { label: "ERROR", tone: "err" },
  offline: { label: "DESCONECTADO", tone: "off" },
});

export const ERROR_KIND_LABELS = Object.freeze({
  rate_limit: "ERROR: RATE LIMIT",
  crash: "ERROR: CAÍDA",
  lost: "ERROR: SIN SEÑAL",
});

export function statusLabel(agent) {
  const status = agent.status || "idle";
  if (status === "error") {
    const kind = agent.error_kind;
    if (kind && Object.hasOwn(ERROR_KIND_LABELS, kind)) return ERROR_KIND_LABELS[kind];
    return STATUS_META.error.label;
  }
  if (Object.hasOwn(STATUS_META, status)) return STATUS_META[status].label;
  return String(status).toUpperCase();
}

export function statusTone(agent) {
  const status = agent.status || "idle";
  return Object.hasOwn(STATUS_META, status) ? STATUS_META[status].tone : "idle";
}

// "ESTADO: <LABEL>" plus " (<TASK>)" when the agent has a task.
export function statusText(agent) {
  let text = `ESTADO: ${statusLabel(agent)}`;
  const task = (agent.task || "").trim();
  if (task) text += ` (${task.toUpperCase()})`;
  return text;
}
