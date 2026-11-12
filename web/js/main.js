// Entry point: wires API, store, WebSocket and renderers together.

import { connectEvents, createApi } from "./api.js";
import { HITL_CALLBACKS, MANAGER_URL, WS_URL, loadInitialState } from "./config.js";
import { createTerminal, renderDashboard } from "./hud.js";
import { updateExpiryCounters } from "./hitl.js";
import { renderOffice } from "./office.js";
import { createStore } from "./store.js";

const api = createApi(MANAGER_URL);
const store = createStore();

const officeEl = document.getElementById("office");
const dashboardEl = document.getElementById("dashboard");
const terminalEl = document.getElementById("terminal");
const connEl = document.getElementById("conn");
const connTextEl = document.getElementById("conn-text");

const terminal = createTerminal(terminalEl, store);

function renderConnection(connected) {
  connEl.className = `led ${connected ? "led-on" : "led-off"}`;
  connEl.title = connected ? "Manager conectado" : "Manager desconectado";
  connTextEl.textContent = connected ? "ONLINE" : "OFFLINE";
}

function renderAll(state) {
  renderConnection(state.connected);
  renderOffice(officeEl, state, HITL_CALLBACKS, api);
  renderDashboard(dashboardEl, state);
  terminal.render();
}

store.subscribe(renderAll);
renderAll(store.state);

connectEvents(WS_URL, {
  onEvent: (event) => store.apply(event),
  onStatus: (status) => store.setConnected(status === "online"),
});

// The WebSocket snapshot is authoritative; the initial state only fills in
// when it has not arrived yet (the WebSocket reconnects on its own).
loadInitialState(api).then(
  (data) => {
    if (store.state.snapshotSeq === 0) store.apply({ type: "snapshot", data });
  },
  (err) => console.error("Initial state not available:", err),
);

// One global tick: expiry counters in the bubbles and "ÚLTIMO EVENTO".
setInterval(() => {
  updateExpiryCounters(officeEl);
  renderDashboard(dashboardEl, store.state);
}, 1000);
