// Voxel office workers: model builder plus the behaviour state machine (walk
// in, sit and type, wave, walk out) driven by the agent status.

import * as THREE from "three";
import { DOOR_POINT, deskSlot, planPath } from "./layout.js";
import { box } from "./voxel.js";

// Full dark-suit looks: hair / skin / jacket / trousers / tie.
export const AGENT_PALETTES = [
  { H: "#1d1d1d", S: "#f1c27d", T: "#2b2d42", P: "#1d1f2e", tie: "#c0392b" },
  { H: "#3b2a1a", S: "#ffdbac", T: "#3a3f4b", P: "#2b2f3a", tie: "#2e5aa8" },
  { H: "#8a3b1b", S: "#8d5524", T: "#22252e", P: "#181a21", tie: "#1d7a5b" },
  { H: "#f2c14e", S: "#e0ac69", T: "#34384a", P: "#262938", tie: "#c9a227" },
];

export const USER_PALETTE = { H: "#4a2c17", S: "#f1c27d", T: "#1d2b53", P: "#141d3a", tie: "#c0392b" };

// FNV-1a (32 bit) of the id, used when the agent has no explicit avatar.
export function fnv1a(text) {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

// Variant = agent.avatar ?? (FNV-1a(id) % 4)
export function agentVariant(agent) {
  return agent.avatar ?? fnv1a(String(agent.id)) % 4;
}

export function agentPalette(agent) {
  return AGENT_PALETTES[Math.abs(agentVariant(agent)) % AGENT_PALETTES.length];
}

const SHIRT = "#f2f2f2";
const EYES = "#1a1a2e";

// Returns a Group (feet at y = 0, facing +z). `group.userData.parts` holds the
// pivots the animation rotates: legL, legR, armL, armR, head.
export function buildFigure(palette) {
  const group = new THREE.Group();

  const pivotAt = (x, y, z) => {
    const pivot = new THREE.Group();
    pivot.position.set(x, y, z);
    group.add(pivot);
    return pivot;
  };

  // Trousers hang from the hip (y = 0.45).
  const legL = pivotAt(-0.12, 0.45, 0);
  const legR = pivotAt(0.12, 0.45, 0);
  legL.add(box(0.18, 0.45, 0.2, palette.P, 0, -0.225, 0));
  legR.add(box(0.18, 0.45, 0.2, palette.P, 0, -0.225, 0));

  // Jacket with a white shirt strip and a tie on the front (+z).
  group.add(box(0.5, 0.55, 0.3, palette.T, 0, 0.725, 0));
  group.add(box(0.16, 0.4, 0.02, SHIRT, 0, 0.78, 0.155));
  group.add(box(0.06, 0.3, 0.02, palette.tie, 0, 0.74, 0.168));

  // Sleeves hang from the shoulder; the hand is a skin-coloured block.
  const armL = pivotAt(-0.325, 0.95, 0);
  const armR = pivotAt(0.325, 0.95, 0);
  for (const arm of [armL, armR]) {
    arm.add(box(0.15, 0.4, 0.18, palette.T, 0, -0.2, 0));
    arm.add(box(0.13, 0.12, 0.16, palette.S, 0, -0.46, 0));
  }

  const head = pivotAt(0, 1.0, 0);
  head.add(box(0.42, 0.42, 0.42, palette.S, 0, 0.21, 0));
  head.add(box(0.44, 0.14, 0.44, palette.H, 0, 0.45, 0));
  head.add(box(0.44, 0.3, 0.06, palette.H, 0, 0.3, -0.2));
  head.add(box(0.06, 0.06, 0.06, EYES, -0.1, 0.24, 0.21));
  head.add(box(0.06, 0.06, 0.06, EYES, 0.1, 0.24, 0.21));

  group.userData.parts = { legL, legR, armL, armR, head };
  return group;
}

const SPEED = 2.2;
const SIT_DROP = 0.25;
const REACH = 1e-3;
const SEATED_STATUSES = new Set(["working", "error", "paused", "waiting_input"]);

const lerp = (a, b, k) => a + (b - a) * k;
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

function shortestAngle(from, to) {
  let d = (to - from) % (Math.PI * 2);
  if (d > Math.PI) d -= Math.PI * 2;
  if (d < -Math.PI) d += Math.PI * 2;
  return d;
}

export class Figure {
  constructor(palette) {
    this.root = new THREE.Group();
    this.model = buildFigure(palette);
    this.parts = this.model.userData.parts;
    this.root.add(this.model);

    this.pos = { x: DOOR_POINT.x, z: DOOR_POINT.z };
    this.yaw = 0;
    this.path = [];
    this.goal = { pose: "leave", at: DOOR_POINT, yaw: 0 };
    this.status = null;
    this.slot = null;
    this.removing = false;
    this.done = false; // walked out: the world may dispose it
    this.walk = 0; // 0..1 swing amplitude
    this.sit = 0; // 0..1 sitting blend
    this.wave = 0; // 0..1 raised arm blend
    this.syncTransform();
  }

  // Permanently seated figure (the user's avatar), facing the camera.
  setFixedSeat(seat) {
    this.pos = { x: seat.x, z: seat.z };
    this.goal = { pose: "sit", typing: false, sway: true, at: seat, yaw: 0 };
    this.yaw = 0;
    this.sit = 1;
    this.syncTransform();
  }

  // Active agent at desk `slot`; walks there from wherever it stands.
  setAgent(agent, slot) {
    const status = agent.status || "idle";
    const revived = this.removing;
    if (status === this.status && slot === this.slot && !revived) return;
    this.status = status;
    this.slot = slot;
    this.removing = false;
    this.replan();
  }

  // Walks out through the door; `done` flips once it got there.
  remove() {
    if (this.removing) return;
    this.removing = true;
    this.replan();
  }

  replan() {
    const spot = this.slot === null ? null : deskSlot(this.slot);
    if (this.removing || !spot || !(SEATED_STATUSES.has(this.status) || this.status === "waiting_approval")) {
      this.goal = { pose: "leave", at: DOOR_POINT, yaw: 0 };
    } else if (this.status === "waiting_approval") {
      this.goal = { pose: "wave", at: spot.stand, yaw: 0 };
    } else {
      // Seated at the desk, back to the camera, facing the monitors (-z).
      this.goal = {
        pose: "sit",
        typing: this.status === "working",
        sway: this.status === "paused" || this.status === "waiting_input",
        at: spot.seat,
        yaw: Math.PI,
      };
    }
    this.moveTo(this.goal.at);
  }

  moveTo(target) {
    if (reducedMotion()) {
      this.path = [];
      this.pos = { x: target.x, z: target.z };
      this.yaw = this.goal.yaw;
      this.afterArrival();
      this.syncTransform();
      return;
    }
    this.path = planPath(this.pos, target);
    if (this.path.length === 0) this.afterArrival();
  }

  afterArrival() {
    if (this.goal.pose === "leave") this.done = true;
  }

  update(dt, t) {
    if (this.done) return;
    const still = reducedMotion();

    let moving = false;
    if (this.path.length > 0) {
      moving = true;
      let left = SPEED * dt; // distance still to walk this frame
      let heading = null;
      while (left > 0 && this.path.length > 0) {
        const next = this.path[0];
        const dx = next.x - this.pos.x;
        const dz = next.z - this.pos.z;
        const dist = Math.hypot(dx, dz);
        if (dist <= REACH) {
          this.path.shift();
          continue;
        }
        heading = Math.atan2(dx, dz);
        if (dist <= left) {
          this.pos.x = next.x;
          this.pos.z = next.z;
          left -= dist;
          this.path.shift();
        } else {
          this.pos.x += (dx / dist) * left;
          this.pos.z += (dz / dist) * left;
          left = 0;
        }
      }
      if (heading !== null) this.yaw += shortestAngle(this.yaw, heading) * Math.min(1, dt * 14);
      if (this.path.length === 0) {
        moving = false;
        this.afterArrival();
        if (this.done) return;
      }
    }
    if (!moving) {
      // Arrived: turn to the pose's facing (monitors / camera).
      this.yaw += shortestAngle(this.yaw, this.goal.yaw) * Math.min(1, dt * 10);
    }

    const seated = !moving && this.goal.pose === "sit";
    const waving = !moving && this.goal.pose === "wave";
    const k = Math.min(1, dt * 10);
    this.walk = lerp(this.walk, moving && !still ? 1 : 0, k);
    this.sit = still ? (seated ? 1 : 0) : lerp(this.sit, seated ? 1 : 0, Math.min(1, dt * 8));
    this.wave = still ? 0 : lerp(this.wave, waving ? 1 : 0, k);

    const { legL, legR, armL, armR, head } = this.parts;
    const swing = Math.sin(t * 10) * 0.6 * this.walk;
    const sit = this.sit;
    legL.rotation.x = lerp(swing, -Math.PI / 2, sit);
    legR.rotation.x = lerp(-swing, -Math.PI / 2, sit);

    // Hands rest on the keyboard; typing alternates the arms.
    let typeL = -1.3;
    let typeR = -1.3;
    if (this.goal.typing && !still) {
      const wobble = Math.sin(t * 18) * 0.15;
      typeL = -1.4 + wobble;
      typeR = -1.4 - wobble;
    }
    armL.rotation.x = lerp(-swing, typeL, sit);
    const armRWalk = lerp(swing, typeR, sit);
    armR.rotation.x = lerp(armRWalk, -2.6 + Math.sin(t * 6) * 0.3, this.wave);

    head.rotation.y = this.goal.sway && seated && !still ? Math.sin(t * 1.5) * 0.3 : 0;

    const bob = Math.abs(Math.sin(t * 10)) * 0.05 * this.walk;
    this.model.position.y = -SIT_DROP * sit + bob;
    this.syncTransform();
  }

  syncTransform() {
    this.root.position.set(this.pos.x, 0, this.pos.z);
    this.root.rotation.y = this.yaw;
  }
}
