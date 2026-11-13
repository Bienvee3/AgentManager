// Pure room geometry (no THREE). All units are world tiles; coordinates are
// room-local (x = 0 at the room centre, z grows towards the camera).

export const ROOM_W = 16;
export const ROOM_GAP = 4;
export const roomX = (index) => index * (ROOM_W + ROOM_GAP);

export const COLS = 4;
export const DESK_X = Object.freeze([-5.25, -1.75, 1.75, 5.25]);
// Walking lane to the right of each desk column.
export const GAP_X = Object.freeze([-3.5, 0, 3.5, 7.0]);
export const ROW_STEP = 3.2;

export const WALL_X = 8; // inner face of the side walls (|x|)
export const WALL_H = 2.5;
export const FRONT_Z = 4; // front edge of the floor (open side)
export const CORRIDOR_Z = 1;
export const DESK_AREA_Z = -0.5; // z below this is "in the desk area"

export const LOUNGE = Object.freeze({ x0: 1, x1: 7, z0: 1.8, z1: 3.6 });
export const COFFEE = Object.freeze({ x: 7.2, z: 3.4 });
export const DOOR_LEFT = Object.freeze({ x: -WALL_X, z: 2.2 });
export const DOOR_RIGHT = Object.freeze({ x: WALL_X, z: 2.2 });
// Where figures enter and leave the room (inside the left wall door).
export const DOOR_POINT = Object.freeze({ x: -7.3, z: 2.2 });
export const DOOR_POINT_RIGHT = Object.freeze({ x: 7.3, z: 2.2 });

// Boss desk (room 0 only) where the user's own avatar sits.
export const BOSS_DESK = Object.freeze({ x: -4.5, z: 2.6 });
export const BOSS_SEAT = Object.freeze({ x: -4.5, z: 1.8 });

export function rows(deskCount) {
  return Math.max(4, Math.ceil(deskCount / COLS));
}

export function backWallZ(rowCount) {
  return -2 - (rowCount - 1) * ROW_STEP - 2.2;
}

// Desk slot k -> desk centre, seat (agent faces +z, towards the camera) and the
// point where the agent stands while waiting for an approval.
export function deskSlot(k) {
  const col = k % COLS;
  const row = Math.floor(k / COLS);
  const x = DESK_X[col];
  const z = -2 - row * ROW_STEP;
  return {
    col,
    row,
    desk: { x, z },
    seat: { x, z: z - 0.9 },
    stand: { x: x + 0.9, z: z - 0.9 },
  };
}

export function nearestGapX(x) {
  let best = GAP_X[0];
  for (const gap of GAP_X) {
    if (Math.abs(gap - x) < Math.abs(best - x)) best = gap;
  }
  return best;
}

const inDeskArea = (p) => p.z < DESK_AREA_Z;

// Waypoints (excluding `from`, including `to`) that keep agents on the walking
// lanes between desk columns. Agent-agent collisions are ignored.
export function planPath(from, to) {
  if (Math.abs(from.x - to.x) < 1e-6 && Math.abs(from.z - to.z) < 1e-6) return [];
  const pts = [];
  const fromDesk = inDeskArea(from);
  const toDesk = inDeskArea(to);
  if (fromDesk && toDesk && nearestGapX(from.x) === nearestGapX(to.x)) {
    // Same lane: no need to go down to the corridor.
    const gx = nearestGapX(from.x);
    pts.push({ x: gx, z: from.z }, { x: gx, z: to.z });
  } else {
    if (fromDesk) {
      const gx = nearestGapX(from.x);
      pts.push({ x: gx, z: from.z }, { x: gx, z: CORRIDOR_Z });
    }
    if (toDesk) {
      const gx = nearestGapX(to.x);
      pts.push({ x: gx, z: CORRIDOR_Z }, { x: gx, z: to.z });
    }
  }
  pts.push({ x: to.x, z: to.z });
  const out = [];
  let prev = from;
  for (const p of pts) {
    if (Math.abs(p.x - prev.x) > 1e-6 || Math.abs(p.z - prev.z) > 1e-6) {
      out.push(p);
      prev = p;
    }
  }
  return out;
}

export function randomLoungePoint(rand) {
  return {
    x: LOUNGE.x0 + rand() * (LOUNGE.x1 - LOUNGE.x0),
    z: LOUNGE.z0 + rand() * (LOUNGE.z1 - LOUNGE.z0),
  };
}
