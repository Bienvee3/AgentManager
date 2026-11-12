// Static pixel-art sprites. The returned SVG strings are the only content that
// may be assigned through innerHTML (they never contain agent-provided data).

const OUTLINE = "#1a1a2e";

const AGENT_MATRIX = [
  "................",
  ".....DDDDDD.....",
  "....DHHHHHHD....",
  "...DHHHHHHHHD...",
  "...DHSSSSSSHD...",
  "...DSSESSESSD...",
  "...DSSSSSSSSD...",
  "....DSSSSSSD....",
  ".....DDSSDD.....",
  "...DDTTTTTTDD...",
  "..DTTTTTTTTTTD..",
  "..DTTTTTTTTTTD..",
  ".DSTTTTTTTTTTSD.",
  ".DSDTTTTTTTTDSD.",
  "..D.DTTTTTTD.D..",
  "....DDDDDDDD....",
];

// hair / skin / shirt
const AGENT_PALETTES = [
  { H: "#3b2a1a", S: "#f1c27d", T: "#2e86de" },
  { H: "#f2c14e", S: "#ffdbac", T: "#8e44ad" },
  { H: "#1d1d1d", S: "#8d5524", T: "#16a085" },
  { H: "#c0392b", S: "#e0ac69", T: "#d35400" },
];

const MONITOR_MATRIX = [
  ".FFFFFFFFFFFFFF.",
  ".FBBBBBBBBBBBBF.",
  ".FBGGGGGGGGGGBF.",
  ".FBGGGGGGGGGGBF.",
  ".FBGGGGGGGGGGBF.",
  ".FBGGGGGGGGGGBF.",
  ".FBGGGGGGGGGGBF.",
  ".FBBBBBBBBBBBBF.",
  ".FFFFFFFFFFFFFF.",
  "......FFFF......",
  "....FFFFFFFF....",
  "................",
  ".KKKKKKKKKKKKKK.",
  ".KDKDKDKDKDKDKK.",
];

const MONITOR_COLORS = { F: "#c9c9c9", B: "#2d2d2d", K: "#7a7a7a", D: "#1a1a2e" };

// Screen text lines: [y, width] at x = 3.
const MONITOR_LINES = [
  [3, 6],
  [4, 8],
  [5, 4],
];

function rect(x, y, fill) {
  return `<rect x="${x}" y="${y}" width="1" height="1" fill="${fill}"/>`;
}

export function agentSprite(variant) {
  const index = ((Math.trunc(variant) % 4) + 4) % 4 || 0;
  const palette = AGENT_PALETTES[index];
  const colors = { D: OUTLINE, E: OUTLINE, ...palette };
  const rects = [];
  AGENT_MATRIX.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      const color = colors[row[x]];
      if (color) rects.push(rect(x, y, color));
    }
  });
  return `<svg class="sprite agent-svg" viewBox="0 0 16 16" shape-rendering="crispEdges" xmlns="http://www.w3.org/2000/svg">${rects.join("")}</svg>`;
}

export function monitorSprite() {
  const rects = [];
  MONITOR_MATRIX.forEach((row, y) => {
    for (let x = 0; x < row.length; x++) {
      const ch = row[x];
      if (ch === "G") {
        rects.push(`<rect class="scr" x="${x}" y="${y}" width="1" height="1"/>`);
      } else if (MONITOR_COLORS[ch]) {
        rects.push(rect(x, y, MONITOR_COLORS[ch]));
      }
    }
  });
  for (const [y, width] of MONITOR_LINES) {
    rects.push(`<rect class="ln" x="3" y="${y}" width="${width}" height="1" fill="#0b0f0b"/>`);
  }
  return `<svg class="sprite monitor-svg" viewBox="0 0 16 14" shape-rendering="crispEdges" xmlns="http://www.w3.org/2000/svg">${rects.join("")}</svg>`;
}

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
