// Entry point: wires API, store, WebSocket and renderers together.

import { connectEvents, createApi } from "./api.js";
import { HITL_CALLBACKS, MANAGER_URL, WS_URL, loadInitialState } from "./config.js";
import { createTerminal, renderDashboard } from "./hud.js";
import { updateExpiryCounters } from "./hitl.js";
import { createStore, el, listRooms } from "./store.js";
import { createWorld } from "./world/world.js";

const api = createApi(MANAGER_URL);
const store = createStore();

const worldEl = document.getElementById("world");
const roomsEl = document.getElementById("rooms");
const dashboardEl = document.getElementById("dashboard");
const terminalEl = document.getElementById("terminal");
const connEl = document.getElementById("conn");
const connTextEl = document.getElementById("conn-text");

const terminal = createTerminal(terminalEl, store);

let selectedId = null;

function onFocusAgent(id) {
  world.focusAgent(id);
  onSelect(id);
}

function onSelect(id) {
  selectedId = id;
  renderDashboard(dashboardEl, store.state, selectedId, onFocusAgent);
}

const world = createWorld(worldEl, {
  callbacks: HITL_CALLBACKS,
  api,
  onSelect,
  onRoomChange: () => renderRoomTabs(store.state),
});

function renderConnection(connected) {
  connEl.className = `led ${connected ? "led-on" : "led-off"}`;
  connEl.title = connected ? "Manager conectado" : "Manager desconectado";
  connTextEl.textContent = connected ? "ONLINE" : "OFFLINE";
}

// One button per room: title + number of active agents.
let tabsKey = "";
function renderRoomTabs(state) {
  const active = world.currentRoom();
  const rooms = listRooms(state);
  const key = rooms.map((r) => `${r.index}\u0000${r.title}\u0000${r.active}`).join("\u0001") + `\u0002${active}`;
  if (key === tabsKey) return;
  tabsKey = key;
  roomsEl.replaceChildren(
    ...rooms.map((room) => {
      const button = el("button", "room-tab", `${room.title} (${room.active})`);
      button.type = "button";
      if (room.index === active) button.classList.add("active");
      button.addEventListener("click", () => world.goToRoom(room.index));
      return button;
    }),
  );
}

function renderAll(state) {
  renderConnection(state.connected);
  world.render(state);
  renderRoomTabs(state);
  renderDashboard(dashboardEl, state, selectedId, onFocusAgent);
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
  updateExpiryCounters(worldEl);
  renderDashboard(dashboardEl, store.state, selectedId, onFocusAgent);
}, 1000);
