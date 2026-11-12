// Office grid: one cubicle per agent, reconciled by data-agent-id.

import { statusText, statusTone } from "./config.js";
import { renderBubble } from "./hitl.js";
import { agentSprite, agentVariant, monitorSprite } from "./sprites.js";
import { el } from "./store.js";

const EMPTY_TEXT = "SIN AGENTES — configura agents.yaml o registra uno vía API";

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

function buildCubicle(agent) {
  const cubicle = el("div", "cubicle");
  cubicle.dataset.agentId = agent.id;

  const slot = el("div", "hitl-slot");

  const tag = el("div", "status-tag");
  tag.append(el("span", "tag-main"), el("span", "tag-detail"));

  const scene = el("div", "scene");
  const agentBox = el("div", "agent-sprite");
  agentBox.innerHTML = agentSprite(agentVariant(agent)); // static SVG only
  const desk = el("div", "desk");
  const monitor = el("div", "monitor");
  monitor.innerHTML = monitorSprite(); // static SVG only
  scene.append(agentBox, desk, monitor);

  const plate = el("div", "nameplate");
  plate.append(el("span", "np-name"), el("span", "np-role"), el("span", "np-model"));

  cubicle.append(slot, tag, scene, plate);
  cubicle._avatarKey = `${agent.avatar}`;
  return cubicle;
}

function updateCubicle(cubicle, agent, pending, callbacks, api) {
  const tone = statusTone(agent);
  const cls = `cubicle status-${agent.status} tone-${tone}`;
  if (cubicle.dataset.cls !== cls) {
    const flash = cubicle.classList.contains("flash");
    cubicle.className = flash ? `${cls} flash` : cls;
    cubicle.dataset.cls = cls;
  }

  if (cubicle._avatarKey !== `${agent.avatar}`) {
    cubicle.querySelector(".agent-sprite").innerHTML = agentSprite(agentVariant(agent)); // static SVG only
    cubicle._avatarKey = `${agent.avatar}`;
  }

  const tag = cubicle.querySelector(".status-tag");
  const tagCls = `status-tag tone-${tone}`;
  if (tag.className !== tagCls) tag.className = tagCls;
  setText(tag.querySelector(".tag-main"), statusText(agent));
  const detail = tag.querySelector(".tag-detail");
  setText(detail, agent.detail || "");
  detail.hidden = !agent.detail;

  setText(cubicle.querySelector(".np-name"), agent.name || agent.id);
  const role = cubicle.querySelector(".np-role");
  setText(role, agent.role || "");
  role.hidden = !agent.role;
  const model = cubicle.querySelector(".np-model");
  setText(model, agent.model ? agent.model.split("/").pop() : "");
  model.hidden = !agent.model;

  renderBubble(cubicle, pending, callbacks, api);
}

function compareAgents(a, b) {
  return (a.desk ?? 0) - (b.desk ?? 0) || String(a.name).localeCompare(String(b.name));
}

export function renderOffice(root, state, callbacks, api) {
  if (!root._cubicles) root._cubicles = new Map();
  const cubicles = root._cubicles;
  const agents = [...state.agents.values()].sort(compareAgents);

  // Drop cubicles of agents that no longer exist.
  const live = new Set(agents.map((a) => a.id));
  for (const [id, node] of cubicles) {
    if (!live.has(id)) {
      node.remove();
      cubicles.delete(id);
    }
  }

  const empty = root.querySelector(":scope > .empty");
  if (agents.length === 0) {
    if (!empty) root.append(el("p", "empty", EMPTY_TEXT));
    return;
  }
  if (empty) empty.remove();

  const pendingByAgent = new Map();
  for (const approval of state.approvals.values()) {
    if (!pendingByAgent.has(approval.agent_id)) pendingByAgent.set(approval.agent_id, []);
    pendingByAgent.get(approval.agent_id).push(approval);
  }

  agents.forEach((agent, index) => {
    let cubicle = cubicles.get(agent.id);
    if (!cubicle) {
      cubicle = buildCubicle(agent);
      cubicles.set(agent.id, cubicle);
    }
    const current = root.children[index];
    if (current !== cubicle) root.insertBefore(cubicle, current ?? null);
    updateCubicle(cubicle, agent, pendingByAgent.get(agent.id) ?? [], callbacks, api);
  });
}
