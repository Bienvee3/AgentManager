// Shared box geometries / flat-shaded materials. Cached instances are marked
// `userData.shared` so disposeTree() never frees them.

import * as THREE from "three";

const geometries = new Map();
const materials = new Map();

function boxGeometry(w, h, d) {
  const key = `${w}|${h}|${d}`;
  let geometry = geometries.get(key);
  if (!geometry) {
    geometry = new THREE.BoxGeometry(w, h, d);
    geometry.userData.shared = true;
    geometries.set(key, geometry);
  }
  return geometry;
}

export function lambert(color) {
  let material = materials.get(color);
  if (!material) {
    material = new THREE.MeshLambertMaterial({ color, flatShading: true });
    material.userData.shared = true;
    materials.set(color, material);
  }
  return material;
}

// Box mesh of size w x h x d centred at (x, y, z).
export function box(w, h, d, color, x = 0, y = 0, z = 0) {
  const mesh = new THREE.Mesh(boxGeometry(w, h, d), lambert(color));
  mesh.position.set(x, y, z);
  return mesh;
}

// Frees every non-shared geometry / material / texture below `object`.
export function disposeTree(object) {
  object.traverse((node) => {
    if (!node.isMesh) return;
    if (!node.geometry.userData.shared) node.geometry.dispose();
    const material = node.material;
    if (!material.userData.shared) {
      material.map?.dispose();
      material.dispose();
    }
  });
}
