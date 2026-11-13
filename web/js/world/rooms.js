// Voxel room: checker floor, walls, desks with monitors, doors and props.

import * as THREE from "three";
import {
  BOSS_DESK,
  BOSS_SEAT,
  COFFEE,
  COLS,
  DOOR_LEFT,
  DOOR_RIGHT,
  FRONT_Z,
  ROOM_W,
  WALL_H,
  WALL_X,
  backWallZ,
  deskSlot,
  roomX,
  rows,
} from "./layout.js";
import { box, disposeTree } from "./voxel.js";

const WALL = "#8d99ae";
const WALL_T = 0.3;
const SCREEN_COLORS = {
  ok: "#1f6f3f",
  err: "#7a1010",
  warn: "#7a5a10",
  hitl: "#7a5a10",
  idle: "#20232a",
  off: "#20232a",
};
const SCREEN_DARK = "#20232a";
const BLINK_S = 0.4;

function checkerTexture(repeatX, repeatY) {
  const canvas = document.createElement("canvas");
  canvas.width = 2;
  canvas.height = 2;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#2b2d42";
  ctx.fillRect(0, 0, 2, 2);
  ctx.fillStyle = "#30334f";
  ctx.fillRect(1, 0, 1, 1);
  ctx.fillRect(0, 1, 1, 1);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  texture.generateMipmaps = false;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(repeatX, repeatY);
  return texture;
}

function screenPlane(color, x, y, z, facing) {
  const material = new THREE.MeshBasicMaterial({ color });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(0.58, 0.36), material);
  mesh.position.set(x, y, z);
  if (facing < 0) mesh.rotation.y = Math.PI;
  return mesh;
}

// Monitor on a desk: the glass is shown on both faces so the status colour is
// visible from the camera side too. Returns { group, materials }.
function buildMonitor(x, z, deskTop) {
  const group = new THREE.Group();
  group.add(box(0.12, 0.12, 0.1, "#7a7a7a", x, deskTop + 0.06, z));
  group.add(box(0.7, 0.46, 0.06, "#c9c9c9", x, deskTop + 0.35, z));
  const front = screenPlane(SCREEN_DARK, x, deskTop + 0.35, z + 0.034, 1);
  const back = screenPlane(SCREEN_DARK, x, deskTop + 0.35, z - 0.034, -1);
  group.add(front, back);
  return { group, materials: [front.material, back.material] };
}

function buildDesk(slot, screens) {
  const { desk, seat } = slot;
  const group = new THREE.Group();
  group.add(box(1.8, 0.69, 0.9, "#8b5a2b", desk.x, 0.345, desk.z));
  group.add(box(1.84, 0.06, 0.94, "#5c3a1a", desk.x, 0.72, desk.z));
  group.add(box(0.5, 0.03, 0.18, "#2d3047", desk.x, 0.765, desk.z + 0.22));
  const monitor = buildMonitor(desk.x, desk.z - 0.12, 0.75);
  group.add(monitor.group);
  screens.push(monitor.materials);
  // Chair: seat, back and post.
  group.add(box(0.5, 0.08, 0.5, "#3d405b", seat.x, 0.1, seat.z));
  group.add(box(0.5, 0.6, 0.08, "#3d405b", seat.x, 0.45, seat.z - 0.28));
  group.add(box(0.1, 0.1, 0.1, "#3d405b", seat.x, 0.03, seat.z));
  return group;
}

function buildDoor(side, index) {
  const spot = side === "left" ? DOOR_LEFT : DOOR_RIGHT;
  const dir = side === "left" ? -1 : 1;
  const group = new THREE.Group();
  const cx = spot.x + dir * (WALL_T / 2);
  // Frame and panel straddle the wall so both faces show the door.
  group.add(box(0.36, 2.2, 1.5, "#d9c79a", cx, 1.1, spot.z));
  group.add(box(0.4, 1.95, 1.2, "#5c3a1a", cx, 0.975, spot.z));
  group.add(box(0.46, 0.1, 0.1, "#ffd23f", cx, 1.0, spot.z + 0.4));
  group.traverse((node) => {
    node.userData.door = side;
    node.userData.roomIndex = index;
  });
  group.userData.door = side;
  group.userData.roomIndex = index;
  return group;
}

function buildCoffee() {
  const group = new THREE.Group();
  group.add(box(0.7, 0.8, 0.6, "#4a4e69", COFFEE.x, 0.4, COFFEE.z));
  group.add(box(0.5, 0.5, 0.05, "#1a1a2e", COFFEE.x, 0.5, COFFEE.z + 0.31));
  group.add(box(0.1, 0.1, 0.05, "#ff4d4d", COFFEE.x + 0.18, 0.78, COFFEE.z + 0.31));
  group.add(box(0.74, 0.1, 0.64, "#2b2d42", COFFEE.x, 0.85, COFFEE.z));
  return group;
}

function buildPlant(x, z) {
  const group = new THREE.Group();
  group.add(box(0.45, 0.4, 0.45, "#8b5a2b", x, 0.2, z));
  group.add(box(0.55, 0.5, 0.55, "#2e8b57", x, 0.65, z));
  group.add(box(0.35, 0.35, 0.35, "#3ddc84", x, 1.0, z));
  return group;
}

function buildBossDesk() {
  const group = new THREE.Group();
  const { x, z } = BOSS_DESK;
  group.add(box(2.2, 0.69, 1.0, "#5c3a1a", x, 0.345, z));
  group.add(box(2.24, 0.06, 1.04, "#3b2510", x, 0.72, z));
  group.add(box(0.5, 0.03, 0.18, "#2d3047", x, 0.765, z + 0.25));
  const monitor = buildMonitor(x, z - 0.15, 0.75);
  for (const m of monitor.materials) m.color.set(SCREEN_COLORS.ok);
  group.add(monitor.group);
  group.add(box(0.5, 0.08, 0.5, "#e63946", BOSS_SEAT.x, 0.1, BOSS_SEAT.z));
  group.add(box(0.5, 0.6, 0.08, "#e63946", BOSS_SEAT.x, 0.45, BOSS_SEAT.z - 0.28));
  group.add(box(0.1, 0.1, 0.1, "#3d405b", BOSS_SEAT.x, 0.03, BOSS_SEAT.z));
  return group;
}

export function buildRoom(index, deskCount, { boss = false } = {}) {
  const group = new THREE.Group();
  group.name = `room-${index}`;
  group.position.x = roomX(index);

  let shell = null; // floor + walls (depend on the row count)
  let desks = null;
  let screens = []; // per slot: [front, back] materials
  let tones = [];
  let rowCount = 0;
  const room = { index, group, deskCount: 0 };

  function rebuild() {
    for (const part of [shell, desks]) {
      if (!part) continue;
      group.remove(part);
      disposeTree(part);
    }
    const backZ = backWallZ(rowCount);
    const depth = FRONT_Z - backZ;
    const centerZ = (FRONT_Z + backZ) / 2;

    shell = new THREE.Group();
    const floorMaterial = new THREE.MeshLambertMaterial({ map: checkerTexture(ROOM_W / 2, depth / 2) });
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(ROOM_W, depth), floorMaterial);
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(0, 0, centerZ);
    shell.add(floor);
    shell.add(box(ROOM_W + 0.4, 0.3, depth + 0.2, "#3d405b", 0, -0.16, centerZ));
    shell.add(box(ROOM_W + 2 * WALL_T, WALL_H, WALL_T, WALL, 0, WALL_H / 2, backZ - WALL_T / 2));
    shell.add(box(WALL_T, WALL_H, depth, WALL, -WALL_X - WALL_T / 2, WALL_H / 2, centerZ));
    const right = box(WALL_T, WALL_H, depth, WALL, WALL_X + WALL_T / 2, WALL_H / 2, centerZ);
    // The wall facing the camera would hide the room: keep it see-through.
    right.material = new THREE.MeshLambertMaterial({
      color: WALL,
      flatShading: true,
      transparent: true,
      opacity: 0.28,
      depthWrite: false,
    });
    shell.add(right);
    group.add(shell);

    desks = new THREE.Group();
    screens = [];
    for (let k = 0; k < rowCount * COLS; k++) desks.add(buildDesk(deskSlot(k), screens));
    group.add(desks);
    applyTones(0);
  }

  function applyTones(t) {
    for (let k = 0; k < screens.length; k++) {
      const tone = tones[k] ?? "off";
      let color = SCREEN_COLORS[tone] ?? SCREEN_DARK;
      if (tone === "err" && Math.floor(t / BLINK_S) % 2 === 1) color = SCREEN_DARK;
      for (const material of screens[k]) material.color.set(color);
    }
  }

  room.setDeskCount = (n) => {
    room.deskCount = n;
    const wanted = rows(n);
    if (wanted === rowCount) return;
    rowCount = wanted;
    rebuild();
  };

  // tone: ok | err | warn | hitl | idle | off
  room.setTones = (list) => {
    tones = list;
  };

  room.update = (t) => applyTones(t);

  room.doors = [buildDoor("left", index), buildDoor("right", index)];
  for (const door of room.doors) group.add(door);
  group.add(buildCoffee());
  group.add(buildPlant(-6.9, 3.3));
  group.add(buildPlant(-6.9, -0.2));
  if (boss) group.add(buildBossDesk());

  room.setDeskCount(deskCount);

  // World-space anchor above a door (for its sign).
  room.doorAnchor = (side, target) => {
    const spot = side === "left" ? DOOR_LEFT : DOOR_RIGHT;
    return target.set(roomX(index) + spot.x, 2.5, spot.z);
  };

  room.dispose = () => {
    disposeTree(group);
  };
  return room;
}
