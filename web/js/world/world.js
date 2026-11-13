// Three.js voxel world: rooms, figures, camera, picking and the render loop.

import * as THREE from "three";
import { isActive, statusTone } from "../config.js";
import { MAIN_ROOM_TITLE, el, listRooms } from "../store.js";
import { Figure, USER_PALETTE, agentPalette } from "./figures.js";
import { BOSS_SEAT, FRONT_Z, ROOM_W, backWallZ, roomX, rows } from "./layout.js";
import { createOverlay } from "./overlay.js";
import { buildRoom } from "./rooms.js";

const PIXEL = 3; // CSS pixels per rendered pixel
const TWEEN_MS = 700;
const CAM_OFFSET = new THREE.Vector3(8, 12, 14);
const LABEL_LIFT = 1.9;
const MIN_DESKS = 16;
const USER_ID = "__user__";

const easeInOutCubic = (k) => (k < 0.5 ? 4 * k * k * k : 1 - (-2 * k + 2) ** 3 / 2);
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

function unsupported(root) {
  root.replaceChildren(el("p", "empty", "Tu navegador no soporta WebGL"));
  return {
    render() {},
    goToRoom() {},
    currentRoom: () => 0,
    focusAgent() {},
  };
}

export function createWorld(root, { callbacks, api, onSelect, onRoomChange }) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: false });
  } catch (err) {
    console.error("WebGL not available:", err);
    return unsupported(root);
  }
  renderer.setPixelRatio(1);
  renderer.setClearColor("#1a1a2e");
  const canvas = renderer.domElement;
  canvas.className = "world-canvas";
  root.replaceChildren(canvas);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#1a1a2e");
  // Three.js >= r155 uses physical light units: x PI gives the classic
  // 0.7 ambient + 0.8 directional look.
  scene.add(new THREE.AmbientLight(0xffffff, 0.7 * Math.PI));
  const sun = new THREE.DirectionalLight(0xffffff, 0.8 * Math.PI);
  sun.position.set(5, 10, 7);
  scene.add(sun);

  const camera = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.1, 200);

  const overlay = createOverlay(root, {
    onSelect: (id) => onSelect?.(id),
    onDoor: (index) => goToRoom(index),
  });

  const rooms = new Map(); // index -> room
  const figures = new Map(); // agent id -> { figure, room }
  let userFigure = null;
  let model = []; // listRooms() of the last state
  let current = 0;
  let lastState = null;
  const cam = { x: 0, z: 0, depth: 18 };
  let tween = null;
  let width = 1;
  let height = 1;

  // ---- camera -----------------------------------------------------------

  function targetFor(index) {
    const room = rooms.get(index);
    const backZ = backWallZ(rows(room ? room.deskCount : MIN_DESKS));
    return { x: roomX(index), z: (FRONT_Z + backZ) / 2, depth: FRONT_Z - backZ };
  }

  function applyCamera() {
    const aspect = width / height;
    const viewH = Math.max(cam.depth * 0.75 + 6, (ROOM_W + 4) / aspect);
    const halfH = viewH / 2;
    const halfW = halfH * aspect;
    camera.left = -halfW;
    camera.right = halfW;
    camera.top = halfH;
    camera.bottom = -halfH;
    camera.updateProjectionMatrix();
    camera.position.set(cam.x + CAM_OFFSET.x, CAM_OFFSET.y, cam.z + CAM_OFFSET.z);
    camera.lookAt(cam.x, 0, cam.z);
    camera.updateMatrixWorld();
  }

  function goToRoom(index) {
    if (!rooms.has(index) || index === current) return;
    current = index;
    const to = targetFor(index);
    if (reducedMotion()) {
      Object.assign(cam, to);
      tween = null;
    } else {
      tween = { from: { ...cam }, to, start: performance.now() };
    }
    onRoomChange?.(index);
  }

  function stepTween(now) {
    if (!tween) {
      Object.assign(cam, targetFor(current));
      return;
    }
    const k = Math.min(1, (now - tween.start) / TWEEN_MS);
    const e = easeInOutCubic(k);
    for (const key of ["x", "z", "depth"]) cam[key] = tween.from[key] + (tween.to[key] - tween.from[key]) * e;
    if (k >= 1) tween = null;
  }

  // ---- sizing -----------------------------------------------------------

  function resize() {
    const w = root.clientWidth;
    const h = root.clientHeight;
    if (!w || !h) return;
    width = w;
    height = h;
    renderer.setSize(Math.ceil(w / PIXEL), Math.ceil(h / PIXEL), false);
    applyCamera();
  }
  new ResizeObserver(resize).observe(root);

  // ---- reconcile --------------------------------------------------------

  function ensureRoom(info) {
    const count = Math.max(MIN_DESKS, info.agents.length);
    let room = rooms.get(info.index);
    if (!room) {
      room = buildRoom(info.index, count, { boss: info.index === 0 });
      rooms.set(info.index, room);
      scene.add(room.group);
    } else {
      room.setDeskCount(count);
    }
    return room;
  }

  function ensureUser() {
    if (userFigure) return;
    userFigure = new Figure(USER_PALETTE);
    userFigure.setFixedSeat(BOSS_SEAT);
    rooms.get(0).group.add(userFigure.root);
    overlay.setUserLabel(USER_ID, "TÚ · DIRECTOR");
  }

  function dropFigure(id) {
    const entry = figures.get(id);
    if (!entry) return;
    rooms.get(entry.room)?.group.remove(entry.figure.root);
    figures.delete(id);
    overlay.removeLabel(id);
  }

  // Only active agents are on stage: they walk in through the door when they
  // become active and walk out (then vanish) when they stop being so.
  function reconcile(state) {
    lastState = state;
    model = listRooms(state);
    const wanted = new Set(model.map((r) => r.index));

    for (const info of model) {
      const room = ensureRoom(info);
      room.setTitle(info.index === 0 ? MAIN_ROOM_TITLE : (info.project?.name ?? info.title).toUpperCase());
    }
    ensureUser();

    const pendingByAgent = new Map();
    for (const approval of state.approvals.values()) {
      if (!pendingByAgent.has(approval.agent_id)) pendingByAgent.set(approval.agent_id, []);
      pendingByAgent.get(approval.agent_id).push(approval);
    }

    const onStage = new Set();
    for (const info of model) {
      const room = rooms.get(info.index);
      const tones = new Array(room.deskCount).fill("off");
      info.agents.forEach((agent, slot) => {
        let entry = figures.get(agent.id);
        if (!isActive(agent)) {
          if (entry && !entry.figure.removing) {
            entry.figure.remove();
            overlay.removeLabel(agent.id);
          }
          return;
        }
        onStage.add(agent.id);
        if (entry && entry.room !== info.index) {
          dropFigure(agent.id); // moved to another room: re-enter there
          entry = undefined;
        }
        if (!entry) {
          const figure = new Figure(agentPalette(agent));
          figure.root.userData.agentId = agent.id;
          entry = { figure, room: info.index };
          figures.set(agent.id, entry);
          room.group.add(figure.root);
        }
        entry.figure.setAgent(agent, slot);
        tones[slot] = statusTone(agent);
        overlay.setAgentLabel(agent, pendingByAgent.get(agent.id) ?? [], callbacks, api);
      });
      room.setTones(tones);
    }

    // Agents that disappeared from the roster walk out too.
    for (const [id, entry] of figures) {
      if (onStage.has(id) || entry.figure.removing) continue;
      entry.figure.remove();
      overlay.removeLabel(id);
    }

    // Rooms that no longer exist: drop them together with their figures.
    for (const [index, room] of rooms) {
      if (wanted.has(index)) continue;
      for (const [id, entry] of [...figures]) {
        if (entry.room === index) dropFigure(id);
      }
      scene.remove(room.group);
      room.dispose();
      rooms.delete(index);
    }
    if (!rooms.has(current)) {
      current = -1;
      goToRoom(0);
    }

    syncDoorSigns();
  }

  function doorTarget(index, side) {
    const sorted = model.map((r) => r.index);
    if (side === "right") return sorted.find((i) => i > index) ?? null;
    return [...sorted].reverse().find((i) => i < index) ?? null;
  }

  function titleOf(index) {
    return model.find((r) => r.index === index)?.title ?? "";
  }

  function syncDoorSigns() {
    const signs = [];
    for (const index of rooms.keys()) {
      for (const side of ["left", "right"]) {
        const target = doorTarget(index, side);
        if (target === null) continue;
        signs.push({
          key: `${index}-${side}`,
          text: `${side === "left" ? "← " : "→ "}${titleOf(target)}`,
          target,
        });
      }
    }
    overlay.syncDoorSigns(signs);
  }

  // ---- picking ----------------------------------------------------------

  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();

  canvas.addEventListener("pointerdown", (event) => {
    const rect = canvas.getBoundingClientRect();
    ndc.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const room = rooms.get(current);
    if (!room) return;
    const targets = [...room.doors];
    for (const entry of figures.values()) {
      if (entry.room === current && !entry.figure.removing) targets.push(entry.figure.root);
    }
    const hit = raycaster.intersectObjects(targets, true)[0];
    if (!hit) return;
    for (let node = hit.object; node; node = node.parent) {
      if (node.userData.door) {
        const target = doorTarget(current, node.userData.door);
        if (target !== null) goToRoom(target);
        return;
      }
      if (node.userData.agentId) {
        onSelect?.(node.userData.agentId);
        return;
      }
    }
  });

  window.addEventListener("keydown", (event) => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const tag = event.target?.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const target = doorTarget(current, event.key === "ArrowLeft" ? "left" : "right");
    if (target !== null) goToRoom(target);
  });

  // ---- render loop ------------------------------------------------------

  const anchor = new THREE.Vector3();
  let lastFrame = performance.now();

  function project(vector) {
    vector.project(camera);
    return {
      x: (vector.x * 0.5 + 0.5) * width,
      y: (-vector.y * 0.5 + 0.5) * height,
      inside: Math.abs(vector.x) <= 1.15 && vector.y >= -1.1 && vector.y <= 1.3,
    };
  }

  function placeOverlay() {
    const place = (id, figure, roomIndex) => {
      if (roomIndex !== current || !figure.root.visible) {
        overlay.placeLabel(id, 0, 0, false);
        return;
      }
      figure.root.getWorldPosition(anchor);
      anchor.y += LABEL_LIFT;
      const p = project(anchor);
      overlay.placeLabel(id, p.x, p.y, p.inside);
    };
    for (const [id, entry] of figures) place(id, entry.figure, entry.room);
    if (userFigure) place(USER_ID, userFigure, 0);

    for (const index of rooms.keys()) {
      const room = rooms.get(index);
      for (const side of ["left", "right"]) {
        const key = `${index}-${side}`;
        if (index !== current || doorTarget(index, side) === null) {
          overlay.placeDoorSign(key, 0, 0, false);
          continue;
        }
        const p = project(room.doorAnchor(side, anchor));
        overlay.placeDoorSign(key, p.x, p.y, p.inside);
      }
    }
  }

  function frame(now) {
    requestAnimationFrame(frame);
    if (document.hidden) {
      lastFrame = now;
      return;
    }
    const dt = Math.min(0.1, (now - lastFrame) / 1000);
    lastFrame = now;
    const t = now / 1000;

    stepTween(now);
    applyCamera();
    for (const room of rooms.values()) room.update(t);
    for (const [id, entry] of figures) {
      entry.figure.update(dt, t);
      if (entry.figure.done) dropFigure(id); // walked out through the door
    }
    userFigure?.update(dt, t);
    scene.updateMatrixWorld();
    placeOverlay();
    renderer.render(scene, camera);
  }

  resize();
  requestAnimationFrame(frame);

  return {
    render: reconcile,
    goToRoom,
    currentRoom: () => current,
    focusAgent(agentId) {
      const agent = lastState?.agents.get(agentId);
      if (!agent) return;
      const info = model.find((r) => r.agents.some((a) => a.id === agentId));
      if (info) goToRoom(info.index);
    },
  };
}
