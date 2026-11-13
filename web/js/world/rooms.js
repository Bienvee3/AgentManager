// Voxel office room in the corporate pixel-art style: beige tiles with blue
// carpet walkways, teal cubicles with orange desks, filing cabinets, a
// whiteboard and (room 0) the director's rug area.

import * as THREE from "three";
import {
  BOSS_DESK,
  BOSS_RUG,
  BOSS_SEAT,
  COLS,
  CORRIDOR_Z,
  DOOR_LEFT,
  DOOR_RIGHT,
  FRONT_Z,
  GAP_X,
  LANE_W,
  ROOM_W,
  WALL_H,
  WALL_X,
  backWallZ,
  deskSlot,
  roomX,
  rows,
} from "./layout.js";
import { box, disposeTree } from "./voxel.js";

const WALL = "#9cc7bf";
const WALL_TRIM = "#6f9f98";
const WALL_T = 0.3;
const PART = "#7fb3b0";
const PART_TOP = "#5a8f8c";
const DESK_TOP_Y = 0.75;
const BLINK_S = 0.4;

// ---- textures -------------------------------------------------------------

function canvasTexture(width, height, draw) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  draw(canvas.getContext("2d"), width, height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  texture.generateMipmaps = false;
  return texture;
}

function tileTexture(repeatX, repeatY) {
  const texture = canvasTexture(2, 2, (ctx) => {
    ctx.fillStyle = "#cfc7b4";
    ctx.fillRect(0, 0, 2, 2);
    ctx.fillStyle = "#c4bca8";
    ctx.fillRect(1, 0, 1, 1);
    ctx.fillRect(0, 1, 1, 1);
  });
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(repeatX, repeatY);
  return texture;
}

// Screen glass per tone: dim background with horizontal "code" lines.
const SCREEN_STYLES = {
  ok: { bg: "#0d2218", fg: "#3ddc84", alt: "#4cc9f0" },
  err: { bg: "#2a0f0f", fg: "#ff4d4d", alt: "#ff8c8c" },
  warn: { bg: "#2a210a", fg: "#ffd23f", alt: "#ffe58a" },
  idle: { bg: "#12151c", fg: "#2a3342", alt: "#222a36" },
};
SCREEN_STYLES.hitl = SCREEN_STYLES.warn;
SCREEN_STYLES.off = SCREEN_STYLES.idle;

const screenMaterials = new Map();
function screenMaterial(tone) {
  const style = SCREEN_STYLES[tone] ?? SCREEN_STYLES.idle;
  let material = screenMaterials.get(style);
  if (!material) {
    const map = canvasTexture(24, 14, (ctx, w, h) => {
      ctx.fillStyle = style.bg;
      ctx.fillRect(0, 0, w, h);
      for (let row = 0; row < 6; row++) {
        const indent = (row * 5) % 3 === 0 ? 0 : 2;
        const length = 6 + ((row * 7 + 3) % 11);
        ctx.fillStyle = row % 3 === 2 ? style.alt : style.fg;
        ctx.fillRect(2 + indent, 2 + row * 2, Math.min(length, w - 4 - indent), 1);
      }
    });
    material = new THREE.MeshBasicMaterial({ map });
    material.userData.shared = true;
    screenMaterials.set(style, material);
  }
  return material;
}

const SCREEN_GEOMETRY = new THREE.PlaneGeometry(0.54, 0.34);
SCREEN_GEOMETRY.userData.shared = true;

function signMaterial(text, fg = "#ffffff", bg = "#2b3a4a", width = 256, height = 32) {
  const map = canvasTexture(width, height, (ctx, w, h) => {
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);
    let size = h - 10;
    ctx.font = `bold ${size}px monospace`;
    while (size > 6 && ctx.measureText(text).width > w - 12) {
      size -= 1;
      ctx.font = `bold ${size}px monospace`;
    }
    ctx.fillStyle = fg;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, w / 2, h / 2 + 1);
  });
  return new THREE.MeshBasicMaterial({ map });
}

let boardMaterialCache = null;
function boardMaterial() {
  if (!boardMaterialCache) {
    const map = canvasTexture(64, 32, (ctx, w, h) => {
      ctx.fillStyle = "#f4f4f4";
      ctx.fillRect(0, 0, w, h);
      const notes = [
        [4, 4, "#ffd23f"], [14, 5, "#3ddc84"], [26, 3, "#ff8c8c"], [40, 5, "#4cc9f0"], [52, 4, "#ffd23f"],
        [6, 16, "#4cc9f0"], [20, 17, "#ffd23f"], [34, 15, "#3ddc84"], [47, 17, "#ff8c8c"], [56, 15, "#3ddc84"],
      ];
      for (const [x, y, color] of notes) {
        ctx.fillStyle = color;
        ctx.fillRect(x, y, 7, 7);
        ctx.fillStyle = "#5c6378";
        ctx.fillRect(x + 1, y + 2, 5, 1);
        ctx.fillRect(x + 1, y + 4, 3, 1);
      }
      ctx.fillStyle = "#8d99ae";
      ctx.fillRect(4, 27, 56, 1);
    });
    boardMaterialCache = new THREE.MeshBasicMaterial({ map });
    boardMaterialCache.userData.shared = true;
  }
  return boardMaterialCache;
}

function plane(width, height, material, x, y, z, rotY = 0) {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, height), material);
  mesh.position.set(x, y, z);
  mesh.rotation.y = rotY;
  return mesh;
}

// ---- furniture --------------------------------------------------------------

// Blue office chair at `seat`; the backrest is on the camera (+z) side.
function addChair(group, seat) {
  group.add(box(0.55, 0.12, 0.55, "#3a63b5", seat.x, 0.14, seat.z));
  group.add(box(0.55, 0.6, 0.1, "#3a63b5", seat.x, 0.5, seat.z + 0.3));
  group.add(box(0.1, 0.14, 0.1, "#2d3142", seat.x, 0.07, seat.z));
  group.add(box(0.5, 0.04, 0.5, "#2d3142", seat.x, 0.02, seat.z));
}

// One cubicle: partitions, desk, two monitors, keyboard, PC tower, chair.
function buildCubicle(slot, screens) {
  const { desk, seat } = slot;
  const group = new THREE.Group();

  // Partition L: back panel plus a left side panel (far from the camera).
  group.add(box(2.3, 1.4, 0.12, PART, desk.x, 0.7, desk.z - 0.6));
  group.add(box(2.34, 0.06, 0.16, PART_TOP, desk.x, 1.43, desk.z - 0.6));
  const sideLen = 1.95;
  const sideZ = desk.z - 0.55 + sideLen / 2;
  group.add(box(0.12, 1.0, sideLen, PART, desk.x - 1.15, 0.5, sideZ));
  group.add(box(0.16, 0.06, sideLen + 0.04, PART_TOP, desk.x - 1.15, 1.03, sideZ));

  // Orange desk: thin top, drawer pedestal at the right end, leg at the left.
  group.add(box(1.8, 0.08, 0.9, "#d98a3d", desk.x, DESK_TOP_Y - 0.04, desk.z));
  group.add(box(0.5, 0.67, 0.8, "#b9702f", desk.x + 0.65, 0.335, desk.z));
  group.add(box(0.42, 0.03, 0.02, "#8f5522", desk.x + 0.65, 0.5, desk.z + 0.41));
  group.add(box(0.42, 0.03, 0.02, "#8f5522", desk.x + 0.65, 0.25, desk.z + 0.41));
  group.add(box(0.06, 0.67, 0.8, "#b9702f", desk.x - 0.85, 0.335, desk.z));

  // Dual monitors facing +z (towards the person), keyboard, paperwork.
  const meshes = [];
  for (const dx of [-0.38, 0.32]) {
    const mx = desk.x + dx;
    const mz = desk.z - 0.18;
    group.add(box(0.1, 0.12, 0.08, "#1a1f2b", mx, DESK_TOP_Y + 0.06, mz));
    group.add(box(0.62, 0.42, 0.05, "#1a1f2b", mx, DESK_TOP_Y + 0.33, mz));
    const screen = new THREE.Mesh(SCREEN_GEOMETRY, screenMaterial("off"));
    screen.position.set(mx, DESK_TOP_Y + 0.33, mz + 0.027);
    group.add(screen);
    meshes.push(screen);
  }
  screens.push({ meshes, tone: "off" });
  group.add(box(0.5, 0.03, 0.18, "#1a1f2b", desk.x, DESK_TOP_Y + 0.015, desk.z + 0.2));
  group.add(box(0.3, 0.03, 0.22, "#e8e2c8", desk.x + 0.62, DESK_TOP_Y + 0.015, desk.z + 0.05));
  group.add(box(0.2, 0.03, 0.26, "#c0392b", desk.x - 0.7, DESK_TOP_Y + 0.015, desk.z + 0.1));

  // PC tower beside the desk.
  group.add(box(0.26, 0.6, 0.5, "#8a939c", desk.x + 1.03, 0.3, desk.z + 0.05));

  addChair(group, seat);
  return group;
}

function buildFilingCabinet(x, z) {
  const group = new THREE.Group();
  group.add(box(0.7, 1.4, 0.6, "#9aa3ad", x, 0.7, z));
  for (const y of [0.35, 0.7, 1.05]) group.add(box(0.6, 0.03, 0.02, "#6b747e", x, y, z + 0.31));
  for (const y of [0.45, 0.8, 1.15]) group.add(box(0.18, 0.04, 0.03, "#4a4e69", x, y, z + 0.32));
  return group;
}

function buildPlant(x, z) {
  const group = new THREE.Group();
  group.add(box(0.45, 0.4, 0.45, "#8b5a2b", x, 0.2, z));
  group.add(box(0.55, 0.5, 0.55, "#2e8b57", x, 0.65, z));
  group.add(box(0.35, 0.35, 0.35, "#3ddc84", x, 1.0, z));
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

// Director area: rug, dark desk, leather chair behind it, two visitor chairs.
function buildBossArea() {
  const group = new THREE.Group();
  const rug = BOSS_RUG;
  group.add(box(rug.w + 0.3, 0.035, rug.d + 0.3, "#8fa0d0", rug.x, 0.0175, rug.z));
  group.add(box(rug.w, 0.045, rug.d, "#4a5d9a", rug.x, 0.0225, rug.z));

  const { x, z } = BOSS_DESK;
  group.add(box(2.4, 0.8, 1.0, "#6a3f22", x, 0.4, z));
  group.add(box(2.44, 0.05, 1.04, "#4a2a14", x, 0.825, z));
  group.add(box(0.5, 0.03, 0.34, "#e8e2c8", x - 0.6, 0.865, z + 0.05));
  group.add(box(0.5, 0.03, 0.34, "#1a1f2b", x + 0.3, 0.865, z + 0.1));
  group.add(box(0.4, 0.1, 0.05, "#c9a227", x, 0.9, z + 0.4));

  // Boss chair (the user sits on it facing the camera): back on the far side.
  group.add(box(0.6, 0.14, 0.6, "#2d3142", BOSS_SEAT.x, 0.14, BOSS_SEAT.z));
  group.add(box(0.6, 0.85, 0.12, "#2d3142", BOSS_SEAT.x, 0.6, BOSS_SEAT.z - 0.32));
  group.add(box(0.12, 0.14, 0.12, "#1a1f2b", BOSS_SEAT.x, 0.07, BOSS_SEAT.z));

  // Visitor chairs facing the desk (-z): back on the camera side.
  for (const cx of [x - 0.8, x + 0.8]) {
    group.add(box(0.5, 0.1, 0.5, "#b5652a", cx, 0.3, 3.65));
    group.add(box(0.5, 0.5, 0.08, "#b5652a", cx, 0.6, 3.65 + 0.25));
    group.add(box(0.08, 0.3, 0.08, "#4a2a14", cx - 0.2, 0.15, 3.5));
    group.add(box(0.08, 0.3, 0.08, "#4a2a14", cx + 0.2, 0.15, 3.5));
    group.add(box(0.08, 0.3, 0.08, "#4a2a14", cx - 0.2, 0.15, 3.8));
    group.add(box(0.08, 0.3, 0.08, "#4a2a14", cx + 0.2, 0.15, 3.8));
  }

  // "OFICINA DEL DIRECTOR" on the left wall (the door takes z 1.45..2.95).
  group.add(box(0.05, 0.8, 1.0, "#2b3a4a", -WALL_X + 0.025, 1.55, 3.5));
  const sign = plane(0.92, 0.72, signMaterial2("OFICINA", "DEL DIRECTOR"), -WALL_X + 0.06, 1.55, 3.5, Math.PI / 2);
  group.add(sign);
  return group;
}

function signMaterial2(line1, line2) {
  const map = canvasTexture(64, 48, (ctx, w, h) => {
    ctx.fillStyle = "#2b3a4a";
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#ffffff";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = "bold 13px monospace";
    ctx.fillText(line1, w / 2, h / 2 - 8);
    ctx.font = "bold 9px monospace";
    ctx.fillText(line2, w / 2, h / 2 + 8);
  });
  return new THREE.MeshBasicMaterial({ map });
}

// ---- room ---------------------------------------------------------------------

export function buildRoom(index, deskCount, { boss = false } = {}) {
  const group = new THREE.Group();
  group.name = `room-${index}`;
  group.position.x = roomX(index);

  let shell = null; // floor, carpet, walls, back-wall props (depend on rows)
  let desks = null;
  let signMesh = null;
  let screens = []; // per slot: { meshes, tone }
  let tones = [];
  let rowCount = 0;
  let title = "";
  const room = { index, group, deskCount: 0 };

  function buildShell() {
    const backZ = backWallZ(rowCount);
    const depth = FRONT_Z - backZ;
    const centerZ = (FRONT_Z + backZ) / 2;
    const part = new THREE.Group();

    // Floor and slab.
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(ROOM_W, depth),
      new THREE.MeshLambertMaterial({ map: tileTexture(ROOM_W / 2, depth / 2) }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(0, 0, centerZ);
    part.add(floor);
    part.add(box(ROOM_W + 0.4, 0.3, depth + 0.2, "#8a8472", 0, -0.16, centerZ));

    // Carpet walkways: border strips first, then the bands on top.
    const laneLen = CORRIDOR_Z - (backZ + 0.1);
    const laneZ = (CORRIDOR_Z + backZ + 0.1) / 2;
    part.add(box(ROOM_W, 0.02, LANE_W + 0.2, "#3b5378", 0, 0.01, CORRIDOR_Z));
    for (const gx of GAP_X) part.add(box(LANE_W + 0.2, 0.02, laneLen, "#3b5378", gx, 0.01, laneZ));
    part.add(box(ROOM_W, 0.03, LANE_W, "#46628f", 0, 0.015, CORRIDOR_Z));
    for (const gx of GAP_X) part.add(box(LANE_W, 0.03, laneLen, "#46628f", gx, 0.015, laneZ));

    // Walls: back and left solid with a darker trim, right one see-through.
    part.add(box(ROOM_W + 2 * WALL_T, WALL_H, WALL_T, WALL, 0, WALL_H / 2, backZ - WALL_T / 2));
    part.add(box(ROOM_W + 2 * WALL_T + 0.04, 0.1, WALL_T + 0.04, WALL_TRIM, 0, WALL_H + 0.05, backZ - WALL_T / 2));
    part.add(box(WALL_T, WALL_H, depth, WALL, -WALL_X - WALL_T / 2, WALL_H / 2, centerZ));
    part.add(box(WALL_T + 0.04, 0.1, depth + 0.04, WALL_TRIM, -WALL_X - WALL_T / 2, WALL_H + 0.05, centerZ));
    const right = box(WALL_T, WALL_H, depth, WALL, WALL_X + WALL_T / 2, WALL_H / 2, centerZ);
    // The wall facing the camera would hide the room: keep it see-through.
    right.material = new THREE.MeshLambertMaterial({
      color: WALL,
      flatShading: true,
      transparent: true,
      opacity: 0.28,
      depthWrite: false,
    });
    part.add(right);

    // Back wall: windows, whiteboard, sign, filing cabinets.
    for (const wx of [-5.2, 5.2]) {
      part.add(box(2.4, 0.9, 0.06, WALL_TRIM, wx, 1.65, backZ + 0.03));
      part.add(box(2.28, 0.78, 0.05, "#bfe3ef", wx, 1.65, backZ + 0.045));
      part.add(box(0.06, 0.78, 0.07, WALL_TRIM, wx, 1.65, backZ + 0.05));
    }
    part.add(box(2.5, 1.3, 0.06, "#c9c9c9", 0, 1.25, backZ + 0.03));
    part.add(plane(2.34, 1.14, boardMaterial(), 0, 1.25, backZ + 0.065));
    part.add(box(2.0, 0.05, 0.1, "#9aa3ad", 0, 0.58, backZ + 0.08));
    part.add(box(4.6, 0.5, 0.05, "#2b3a4a", 0, 2.2, backZ + 0.025));
    signMesh = plane(4.5, 0.42, signMaterial(title || " "), 0, 2.2, backZ + 0.055);
    part.add(signMesh);
    part.add(buildFilingCabinet(-7.2, backZ + 0.35));
    part.add(buildFilingCabinet(7.2, backZ + 0.35));
    return part;
  }

  function rebuild() {
    for (const part of [shell, desks]) {
      if (!part) continue;
      group.remove(part);
      disposeTree(part);
    }
    shell = buildShell();
    group.add(shell);
    desks = new THREE.Group();
    screens = [];
    for (let k = 0; k < rowCount * COLS; k++) desks.add(buildCubicle(deskSlot(k), screens));
    group.add(desks);
    applyTones(0);
  }

  function applyTones(t) {
    for (let k = 0; k < screens.length; k++) {
      let tone = tones[k] ?? "off";
      if (tone === "err" && Math.floor(t / BLINK_S) % 2 === 1) tone = "idle";
      const entry = screens[k];
      if (entry.tone === tone) continue;
      entry.tone = tone;
      const material = screenMaterial(tone);
      for (const mesh of entry.meshes) mesh.material = material;
    }
  }

  room.setDeskCount = (n) => {
    room.deskCount = n;
    const wanted = rows(n);
    if (wanted === rowCount) return;
    rowCount = wanted;
    rebuild();
  };

  // Back wall sign text (room 0: OFICINA PRINCIPAL, others: project name).
  room.setTitle = (text) => {
    if (text === title) return;
    title = text;
    if (!signMesh) return;
    signMesh.material.map.dispose();
    signMesh.material.dispose();
    signMesh.material = signMaterial(title || " ");
  };

  // tone per desk slot: ok | err | warn | hitl | idle | off
  room.setTones = (list) => {
    tones = list;
  };

  room.update = (t) => applyTones(t);

  room.doors = [buildDoor("left", index), buildDoor("right", index)];
  for (const door of room.doors) group.add(door);
  group.add(buildPlant(6.9, 3.4));
  group.add(buildPlant(-6.9, -0.2));
  if (boss) group.add(buildBossArea());

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
