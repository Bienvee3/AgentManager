// DOM overlay over the 3D canvas: agent labels (with the HITL bubble) and door
// signs. All agent-provided text goes through textContent only.

import { statusLabel, statusTone } from "../config.js";
import { renderBubble } from "../hitl.js";
import { el } from "../store.js";

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

export function createOverlay(root, { onSelect, onDoor }) {
  const node = el("div", "world-overlay");
  root.append(node);
  const labels = new Map(); // id -> { node, tag, main, detail, bubble }
  const signs = new Map(); // key -> { node, text, target }

  function ensureLabel(id, kind) {
    let label = labels.get(id);
    if (label) return label;
    const labelNode = el("div", "fig-label");
    const tag = el("div", "status-tag");
    const main = el("span", "tag-main");
    const detail = el("span", "tag-detail");
    tag.append(main, detail);
    labelNode.append(tag);
    labelNode.hidden = true;
    if (kind === "agent") {
      tag.classList.add("is-clickable");
      tag.addEventListener("click", () => onSelect?.(id));
    }
    node.append(labelNode);
    label = { node: labelNode, tag, main, detail, x: NaN, y: NaN, z: "" };
    labels.set(id, label);
    return label;
  }

  // The user's own avatar.
  function setUserLabel(id, text) {
    const label = ensureLabel(id, "user");
    label.tag.className = "status-tag tone-ok";
    setText(label.main, text);
    label.detail.hidden = true;
  }

  function setAgentLabel(agent, pending, callbacks, api) {
    const label = ensureLabel(agent.id, "agent");
    const tone = statusTone(agent);
    const tagCls = `status-tag is-clickable tone-${tone}`;
    if (label.tag.className !== tagCls) label.tag.className = tagCls;
    const cls = `fig-label status-${agent.status}`;
    if (label.node.className !== cls) label.node.className = cls;
    setText(label.main, agent.name || agent.id);
    const task = (agent.task || "").trim();
    setText(label.detail, statusLabel(agent) + (task ? ` (${task.toUpperCase()})` : ""));
    label.detail.hidden = false;
    renderBubble(label.node, pending, callbacks, api);
    label.hasBubble = pending.length > 0;
  }

  function removeLabel(id) {
    const label = labels.get(id);
    if (!label) return;
    label.node.remove();
    labels.delete(id);
  }

  function placeLabel(id, x, y, visible) {
    const label = labels.get(id);
    if (!label) return;
    if (label.node.hidden === visible) label.node.hidden = !visible;
    if (!visible) return;
    let px = Math.round(x);
    let py = Math.round(y);
    if (label.hasBubble) {
      // Keep the whole bubble (and its buttons) inside the view.
      const half = label.node.offsetWidth / 2;
      px = Math.min(Math.max(px, half + 4), node.clientWidth - half - 4);
      py = Math.max(py, label.node.offsetHeight + 4);
    }
    if (px !== label.x || py !== label.y) {
      label.x = px;
      label.y = py;
      label.node.style.transform = `translate(${px}px, ${py}px) translate(-50%, -100%)`;
    }
    const z = label.hasBubble ? "1000" : String(py);
    if (z !== label.z) {
      label.z = z;
      label.node.style.zIndex = z;
    }
  }

  // signs: [{ key, text, target }]
  function syncDoorSigns(list) {
    const keep = new Set(list.map((s) => s.key));
    for (const [key, sign] of signs) {
      if (!keep.has(key)) {
        sign.node.remove();
        signs.delete(key);
      }
    }
    for (const item of list) {
      let sign = signs.get(item.key);
      if (!sign) {
        const button = el("button", "door-sign");
        button.type = "button";
        button.hidden = true;
        sign = { node: button, target: item.target, x: NaN, y: NaN };
        button.addEventListener("click", () => onDoor(sign.target));
        node.append(button);
        signs.set(item.key, sign);
      }
      sign.target = item.target;
      setText(sign.node, item.text);
    }
  }

  function placeDoorSign(key, x, y, visible) {
    const sign = signs.get(key);
    if (!sign) return;
    if (sign.node.hidden === visible) sign.node.hidden = !visible;
    if (!visible) return;
    const px = Math.round(x);
    const py = Math.round(y);
    if (px !== sign.x || py !== sign.y) {
      sign.x = px;
      sign.y = py;
      sign.node.style.transform = `translate(${px}px, ${py}px) translate(-50%, -100%)`;
    }
  }

  function hideAllDoorSigns() {
    for (const sign of signs.values()) sign.node.hidden = true;
  }

  return {
    node,
    setUserLabel,
    setAgentLabel,
    removeLabel,
    placeLabel,
    syncDoorSigns,
    placeDoorSign,
    hideAllDoorSigns,
  };
}
