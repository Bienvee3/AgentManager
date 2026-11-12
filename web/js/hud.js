// HUD: system dashboard and log terminal.

import { el, fmtTime } from "./store.js";

const ROWS = [
  ["total", "AGENTES"],
  ["working", "TRABAJANDO"],
  ["waiting", "EN ESPERA/PAUSA"],
  ["hitl", "HITL PENDIENTES"],
  ["errors", "ERRORES"],
  ["offline", "DESCONECTADOS"],
  ["manager", "MANAGER"],
  ["last", "ÚLTIMO EVENTO"],
];

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

function buildDashboard(root) {
  root.replaceChildren();
  root.append(el("h2", "hud-title", "SYSTEM STATUS"));
  const list = el("dl", "hud-rows");
  const values = {};
  for (const [key, label] of ROWS) {
    const row = el("div", "hud-row");
    const value = el("dd", "hud-value");
    row.append(el("dt", "hud-label", label), value);
    list.append(row);
    values[key] = value;
  }
  root.append(list);
  root.append(el("h3", "hud-subtitle", "APROBACIONES PENDIENTES"));
  const pending = el("ul", "pending-list");
  root.append(pending);
  root._dash = { values, pending };
  return root._dash;
}

function flashCubicle(agentId) {
  const target = document.querySelector(`.cubicle[data-agent-id="${CSS.escape(agentId)}"]`);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("flash");
  setTimeout(() => target.classList.remove("flash"), 1000);
}

export function renderDashboard(root, state) {
  const dash = root._dash ?? buildDashboard(root);
  const counts = { working: 0, waiting: 0, errors: 0, offline: 0 };
  for (const agent of state.agents.values()) {
    if (agent.status === "working") counts.working++;
    else if (agent.status === "paused" || agent.status === "waiting_input") counts.waiting++;
    else if (agent.status === "error") counts.errors++;
    else if (agent.status === "offline") counts.offline++;
  }
  const v = dash.values;
  setText(v.total, String(state.agents.size));
  setText(v.working, String(counts.working));
  setText(v.waiting, String(counts.waiting));
  setText(v.hitl, String(state.approvals.size));
  setText(v.errors, String(counts.errors));
  setText(v.offline, String(counts.offline));
  setText(v.manager, state.connected ? "ONLINE" : "OFFLINE");
  v.manager.className = `hud-value ${state.connected ? "is-online" : "is-offline"}`;
  setText(v.last, state.lastEventAt ? fmtTime(state.lastEventAt) : "—");

  // Pending approvals list: rebuilt only when its content changes.
  const approvals = [...state.approvals.values()];
  const key = approvals
    .map((a) => `${a.id}|${a.agent_id}|${a.action}|${state.agents.get(a.agent_id)?.name ?? ""}`)
    .join("\n");
  if (dash.pendingKey === key) return;
  dash.pendingKey = key;
  if (approvals.length === 0) {
    dash.pending.replaceChildren(el("li", "pending-empty", "Sin pendientes"));
    return;
  }
  dash.pending.replaceChildren(
    ...approvals.map((approval) => {
      const item = el("li");
      const agentName = state.agents.get(approval.agent_id)?.name || approval.agent_id;
      const button = el("button", "pending-item", `${agentName} — ${approval.action}`);
      button.type = "button";
      button.addEventListener("click", () => flashCubicle(approval.agent_id));
      item.append(button);
      return item;
    }),
  );
}

function formatLine(entry) {
  return `[${fmtTime(entry.ts)}] [${entry.agent_id ?? "SYSTEM"}] ${entry.message}`;
}

const MAX_DOM_LINES = 500;

// Terminal: incremental painting. `painted` is the absolute index (store
// logOffset + position) of the next log to paint; a full repaint only happens
// after a snapshot or when the filter changes.
export function createTerminal(root, store) {
  const select = root.querySelector("#log-filter");
  const autoscroll = root.querySelector("#autoscroll");
  const lines = root.querySelector("#log-lines");
  let filter = "";
  let painted = 0;
  let seenSnapshot = -1;
  let optionsKey = "";

  function makeLine(entry) {
    const li = el("li", `log-line lvl-${entry.level}`, formatLine(entry));
    return li;
  }

  function matches(entry) {
    return filter === "" || entry.agent_id === filter;
  }

  function scrollToEnd() {
    if (autoscroll.checked) lines.scrollTop = lines.scrollHeight;
  }

  function syncOptions(state) {
    const agents = [...state.agents.values()].sort(
      (a, b) => (a.desk ?? 0) - (b.desk ?? 0) || String(a.name).localeCompare(String(b.name)),
    );
    const key = agents.map((a) => `${a.id}\u0000${a.name}`).join("\u0001");
    if (key === optionsKey) return false;
    optionsKey = key;
    const all = el("option", null, "Todos");
    all.value = "";
    const options = agents.map((a) => {
      const option = el("option", null, a.name || a.id);
      option.value = a.id;
      return option;
    });
    select.replaceChildren(all, ...options);
    let changed = false;
    if (filter !== "" && !state.agents.has(filter)) {
      filter = "";
      changed = true;
    }
    select.value = filter;
    return changed;
  }

  function fullRepaint(state) {
    const fragment = document.createDocumentFragment();
    const visible = state.logs.filter(matches).slice(-MAX_DOM_LINES);
    for (const entry of visible) fragment.append(makeLine(entry));
    lines.replaceChildren(fragment);
    painted = state.logOffset + state.logs.length;
    scrollToEnd();
  }

  function render() {
    const state = store.state;
    const filterReset = syncOptions(state);
    if (state.snapshotSeq !== seenSnapshot || filterReset) {
      seenSnapshot = state.snapshotSeq;
      fullRepaint(state);
      return;
    }
    const start = Math.max(0, painted - state.logOffset);
    if (start >= state.logs.length) return;
    const fragment = document.createDocumentFragment();
    for (let i = start; i < state.logs.length; i++) {
      if (matches(state.logs[i])) fragment.append(makeLine(state.logs[i]));
    }
    painted = state.logOffset + state.logs.length;
    if (!fragment.hasChildNodes()) return;
    lines.append(fragment);
    while (lines.childElementCount > MAX_DOM_LINES) lines.firstElementChild.remove();
    scrollToEnd();
  }

  select.addEventListener("change", () => {
    filter = select.value;
    fullRepaint(store.state);
  });

  return { render };
}
