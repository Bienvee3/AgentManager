// Human-in-the-loop speech bubble shown over a cubicle.

import { el, parseTs } from "./store.js";

function formatRemaining(expiresMs) {
  const total = Number.isNaN(expiresMs) ? 0 : Math.max(0, Math.floor((expiresMs - Date.now()) / 1000));
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  const ss = String(total % 60).padStart(2, "0");
  return `expira en ${mm}:${ss}`;
}

// Called once per second from main.js.
export function updateExpiryCounters(root) {
  for (const node of root.querySelectorAll(".bubble-expiry")) {
    node.textContent = formatRemaining(Number(node.dataset.expires));
  }
}

function buildBubble(approval, callbacks, api) {
  const bubble = el("div", "hitl-bubble");
  bubble.dataset.approvalId = approval.id;

  const head = el("div", "bubble-head");
  head.append(el("span", "bubble-title", "⚠ CONFIRMACIÓN REQUERIDA"), el("span", "bubble-more"));

  const action = el("p", "bubble-action", approval.action);
  const kind = el("p", "bubble-kind", approval.kind);

  const details = el("details", "bubble-details");
  details.append(el("summary", null, "Ver detalles"), el("pre", null, approval.details || "(sin detalles)"));

  const expiry = el("p", "bubble-expiry");
  expiry.dataset.expires = String(parseTs(approval.expires_at));
  expiry.textContent = formatRemaining(Number(expiry.dataset.expires));

  const buttons = el("div", "bubble-buttons");
  const approve = el("button", "btn-approve", "[APROBAR]");
  const reject = el("button", "btn-reject", "[RECHAZAR]");
  approve.type = "button";
  reject.type = "button";
  buttons.append(approve, reject);

  const error = el("p", "bubble-error");
  error.hidden = true;

  async function decide(handler) {
    approve.disabled = true;
    reject.disabled = true;
    error.hidden = true;
    try {
      await handler(approval, api);
      // Success: the WS "approval" event removes the bubble.
    } catch (err) {
      approve.disabled = false;
      reject.disabled = false;
      error.textContent = `ERROR: ${err instanceof Error ? err.message : String(err)}`;
      error.hidden = false;
    }
  }

  approve.addEventListener("click", () => decide(callbacks.onApprove));
  reject.addEventListener("click", () => decide(callbacks.onReject));

  bubble.append(head, action, kind, details, expiry, buttons, error);
  return bubble;
}

// Shows the oldest pending approval of the cubicle (and a "+N" badge when there
// are more). No pending approvals -> the bubble is removed.
export function renderBubble(cubicleEl, approvals, callbacks, api) {
  let slot = cubicleEl.querySelector(".hitl-slot");
  if (!slot) {
    slot = el("div", "hitl-slot");
    cubicleEl.prepend(slot);
  }
  if (approvals.length === 0) {
    if (slot.firstChild) slot.replaceChildren();
    return;
  }
  const sorted = [...approvals].sort((a, b) => parseTs(a.created_at) - parseTs(b.created_at));
  const current = sorted[0];
  let bubble = slot.firstElementChild;
  if (!bubble || bubble.dataset.approvalId !== current.id) {
    bubble = buildBubble(current, callbacks, api);
    slot.replaceChildren(bubble);
  }
  const more = bubble.querySelector(".bubble-more");
  const text = sorted.length > 1 ? `+${sorted.length - 1}` : "";
  if (more.textContent !== text) more.textContent = text;
  more.hidden = sorted.length < 2;
}
