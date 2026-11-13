// Pure room geometry (no THREE). All units are world tiles; coordinates are
// room-local (x = 0 at the room centre, z grows towards the camera).

export const ROOM_W = 16;
export const ROOM_GAP = 4;
export const roomX = (index) => index * (ROOM_W + ROOM_GAP);

export const COLS = 4;
export const DESK_X = Object.freeze([-5.25, -1.75, 1.75, 5.25]);
// Walking lane to the right of each desk column.
export const GAP_X = Object.freeze([-3.5, 0, 3.5, 7.0]);
export const LANE_W = 1.2;
export const ROW_STEP = 3.2;

export const WALL_X = 8; // inner face of the side walls (|x|)
export const WALL_H = 2.5;
export const FRONT_Z = 4; // front edge of the floor (open side)
export const CORRIDOR_Z = 1; // centre line of the front corridor
export const DESK_AREA_Z = -0.5; // z below this is "in the desk area"

export const DOOR_LEFT = Object.freeze({ x: -WALL_X, z: 2.2 });
export const DOOR_RIGHT = Object.freeze({ x: WALL_X, z: 2.2 });
// Where figures enter and leave the room (inside the left wall door).
export const DOOR_POINT = Object.freeze({ x: -7.3, z: 2.2 });

// Director area (room 0 only): the user's avatar sits behind the desk facing
// the camera, two visitor chairs stand in front of it, all on a rug.
export const BOSS_DESK = Object.freeze({ x: -4.5, z: 2.6 });
export const BOSS_SEAT = Object.freeze({ x: -4.5, z: 1.8 });
export const BOSS_RUG = Object.freeze({ x: -4.5, z: 2.7, w: 5, d: 2.6 });

export function rows(deskCount) {
  return Math.max(4, Math.ceil(deskCount / COLS));
}

export function backWallZ(rowCount) {
  return -2 - (rowCount - 1) * ROW_STEP - 2.2;
}

// Desk slot k -> desk centre, seat (the person sits on the camera side of the
// desk, facing -z towards the monitors) and the point where the agent stands
// beside its chair while waiting for an approval.
export function deskSlot(k) {
  const col = k % COLS;
  const row = Math.floor(k / COLS);
  const x = DESK_X[col];
  const z = -2 - row * ROW_STEP;
  return {
    col,
    row,
    desk: { x, z },
    seat: { x, z: z + 0.9 },
    stand: { x: x + 0.9, z: z + 0.9 },
  };
}

// Lane used by whoever is at / next to x: the lane right of the nearest desk
// column (ties resolve to the lower column).
export function laneX(x) {
  let col = 0;
  for (let i = 1; i < COLS; i++) {
    if (Math.abs(DESK_X[i] - x) < Math.abs(DESK_X[col] - x)) col = i;
  }
  return GAP_X[col];
}

const inDeskArea = (p) => p.z < DESK_AREA_Z;
const near = (a, b) => Math.abs(a - b) < 1e-6;

// Waypoints (excluding `from`, including `to`) that keep agents on the walking
// lanes between desk columns and on the front corridor. Agent-agent collisions
// are ignored.
export function planPath(from, to) {
  if (near(from.x, to.x) && near(from.z, to.z)) return [];
  const pts = [];
  const fromDesk = inDeskArea(from);
  const toDesk = inDeskArea(to);
  if (fromDesk && toDesk && laneX(from.x) === laneX(to.x)) {
    if (!near(from.z, to.z)) {
      // Same lane, different row: walk along the lane.
      const gx = laneX(from.x);
      pts.push({ x: gx, z: from.z }, { x: gx, z: to.z });
    }
  } else {
    if (fromDesk) {
      const gx = laneX(from.x);
      pts.push({ x: gx, z: from.z }, { x: gx, z: CORRIDOR_Z });
    } else if (toDesk && from.z > CORRIDOR_Z + 1e-6) {
      pts.push({ x: from.x, z: CORRIDOR_Z });
    }
    if (toDesk) {
      const gx = laneX(to.x);
      pts.push({ x: gx, z: CORRIDOR_Z }, { x: gx, z: to.z });
    } else if (fromDesk && to.z > CORRIDOR_Z + 1e-6) {
      pts.push({ x: to.x, z: CORRIDOR_Z });
    }
  }
  pts.push({ x: to.x, z: to.z });
  const out = [];
  let prev = from;
  for (const p of pts) {
    if (!near(p.x, prev.x) || !near(p.z, prev.z)) {
      out.push(p);
      prev = p;
    }
  }
  return out;
}
