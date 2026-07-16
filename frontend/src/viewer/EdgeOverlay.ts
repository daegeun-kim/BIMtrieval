// Merged entity edge overlay (tasks/task15.md §2).
//
// One THREE.LineSegments over ALL rendered entities — one object, one draw
// call, never a per-entity component or render loop. Geometry comes from the
// already-loaded Fragments model (`getItemsGeometry`, the same mechanism the
// component preview uses), run through THREE.EdgesGeometry per mesh and merged
// into a single position buffer with an RGBA vertex-color attribute plus a
// localId → vertex-range index.
//
// Because color/alpha live per-vertex, a highlight change never rebuilds
// geometry: it rewrites the color ranges of the affected entities and flips
// `needsUpdate`. Edge colors follow the entity's CURRENT face role and are
// derived exclusively from viewerTheme's EDGES block (darken factor + per-role
// alpha) — nothing is hard-coded here.
//
// Measured basis for this design (Node probe on the real Schependomlaan
// artifact): 3,505 items / 5,973 meshes / 258k triangles → 187k edge segments,
// ~10 MB of buffers, ~1.3 s to extract. The build therefore runs asynchronously
// AFTER scene-ready, in yielded batches, so it never blocks load or input.
import * as FRAGS from "@thatopen/fragments";
import * as THREE from "three";

import { EDGES, VIEWER_COLORS } from "./viewerTheme";

export type EdgeRole = keyof typeof EDGES.alpha;

/** Items whose EdgesGeometry is extracted per main-thread slice before
 * yielding. Geometry itself is fetched from the worker in ONE call — batching
 * that fetch multiplies postMessage serialization overhead enormously. */
const EXTRACT_BATCH = 100;

interface VertexRange {
  start: number; // first vertex index
  count: number; // number of vertices
}

/**
 * Yield to the event loop WITHOUT timer throttling. Background tabs clamp
 * `setTimeout(0)` to ~1s, which turned a ~1.5s sliced build into ~30s when the
 * window was unfocused (measured); MessageChannel callbacks are not throttled.
 */
function yieldToLoop(): Promise<void> {
  return new Promise((resolve) => {
    const channel = new MessageChannel();
    channel.port1.onmessage = () => resolve();
    channel.port2.postMessage(null);
  });
}

/** Precomputed RGBA per role, derived from the theme on demand. */
function roleRgba(): Record<EdgeRole, [number, number, number, number]> {
  const out = {} as Record<EdgeRole, [number, number, number, number]>;
  const source: Record<EdgeRole, string> = {
    roof: VIEWER_COLORS.roof,
    wall: VIEWER_COLORS.wall,
    other: VIEWER_COLORS.other,
    primary: VIEWER_COLORS.primary,
    primaryUnfocused: VIEWER_COLORS.primaryUnfocused,
    context: VIEWER_COLORS.context,
    manual: VIEWER_COLORS.manual,
    dim: VIEWER_COLORS.dim,
  };
  for (const role of Object.keys(source) as EdgeRole[]) {
    const c = new THREE.Color(source[role]).multiplyScalar(EDGES.darken);
    out[role] = [c.r, c.g, c.b, EDGES.alpha[role]];
  }
  return out;
}

export class EdgeOverlay {
  private lines: THREE.LineSegments | null = null;
  private colors: Float32Array | null = null;
  private ranges = new Map<number, VertexRange>();
  /** Last role written per entity — lets recolor skip unchanged entities. */
  private lastRole = new Map<number, EdgeRole>();
  private disposed = false;
  private building = false;
  private buildMs: number | null = null;

  isBuilt(): boolean {
    return this.lines !== null && !this.disposed;
  }

  /** Wall-clock build duration in ms once built — for the task15 §2 gate. */
  getBuildMs(): number | null {
    return this.buildMs;
  }

  /**
   * Extract edges for every item with geometry and mount ONE LineSegments under
   * `parent` (the model's own object, so the overlay inherits its transform).
   *
   * The geometry is fetched from the Fragments worker in a SINGLE call — the
   * worker prepares it off the main thread, and one round trip avoids the
   * per-batch postMessage serialization that measurably froze the viewer when
   * this was first written batched. Only the main-thread EdgesGeometry pass is
   * sliced, yielding between slices so orbit/pan/zoom stay responsive. Safe to
   * abandon via dispose() mid-build. Returns true when mounted.
   */
  async build(model: FRAGS.FragmentsModel, parent: THREE.Object3D): Promise<boolean> {
    if (this.disposed || this.building || this.lines) return this.isBuilt();
    this.building = true;
    const started = performance.now();
    try {
      // All local ids, plain numbers on every model flavor. (The worker's
      // getItemsWithGeometry returns Item wrappers whose local id is async —
      // extracting from it silently yielded zero ids when this was first
      // written.) Items without geometry simply produce no meshes below.
      const localIds: number[] = await model.getLocalIds();
      if (localIds.length === 0) return false;

      // One worker round trip for everything (measured 70 ms in the browser
      // for all 5,973 meshes of the current model).
      const perItem = await model.getItemsGeometry(localIds);
      if (this.disposed) return false;

      const chunks: Float32Array[] = [];
      const pending = new Map<number, VertexRange>();
      let vertexCount = 0;

      for (let offset = 0; offset < localIds.length; offset += EXTRACT_BATCH) {
        if (this.disposed) return false; // model switched away mid-build
        const end = Math.min(offset + EXTRACT_BATCH, localIds.length);
        for (let i = offset; i < end; i++) {
          const start = vertexCount;
          for (const mesh of perItem[i] ?? []) {
            const edge = this.extractEdges(mesh);
            if (!edge) continue;
            chunks.push(edge);
            vertexCount += edge.length / 3;
          }
          if (vertexCount > start) {
            pending.set(localIds[i]!, { start, count: vertexCount - start });
          }
        }
        // Yield so orbit/pan/zoom stay responsive during the one-time build.
        await yieldToLoop();
      }
      if (this.disposed || vertexCount === 0) return false;

      const positions = new Float32Array(vertexCount * 3);
      let cursor = 0;
      for (const chunk of chunks) {
        positions.set(chunk, cursor);
        cursor += chunk.length;
      }
      this.colors = new Float32Array(vertexCount * 4);
      this.ranges = pending;

      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute("color", new THREE.BufferAttribute(this.colors, 4));
      const material = new THREE.LineBasicMaterial({
        vertexColors: true,
        transparent: true, // per-vertex alpha (RGBA attribute) needs blending on
        depthWrite: false,
      });
      const lines = new THREE.LineSegments(geometry, material);
      lines.frustumCulled = false; // one whole-model object; culling it is all-or-nothing
      lines.renderOrder = 1; // draw after the faces it outlines
      parent.add(lines);
      this.lines = lines;
      this.buildMs = Math.round(performance.now() - started);
      return true;
    } catch (err) {
      // The overlay is an optional layer — a failed build leaves faces intact.
      // One bounded warning so the omission is observable, never a crash.
      console.warn("edge overlay build failed:", (err as Error)?.message ?? err);
      return false;
    } finally {
      this.building = false;
    }
  }

  /** EdgesGeometry for one mesh, transformed into model space. */
  private extractEdges(mesh: FRAGS.MeshData): Float32Array | null {
    if (!mesh?.positions?.length) return null;
    const geometry = new THREE.BufferGeometry();
    const positions =
      mesh.positions instanceof Float32Array ? mesh.positions : new Float32Array(mesh.positions);
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    if (mesh.indices?.length) {
      geometry.setIndex(new THREE.BufferAttribute(mesh.indices as Uint32Array, 1));
    }
    try {
      const edges = new THREE.EdgesGeometry(geometry, EDGES.thresholdAngleDeg);
      if (mesh.transform) edges.applyMatrix4(mesh.transform);
      const out = (edges.getAttribute("position")?.array as Float32Array) ?? null;
      // Copy out before disposing the intermediate geometry.
      const copy = out && out.length ? new Float32Array(out) : null;
      edges.dispose();
      return copy;
    } catch {
      return null;
    } finally {
      geometry.dispose();
    }
  }

  /**
   * Repaint entity edge colors from their current roles. Only entities whose
   * role actually CHANGED are rewritten, and only the touched spans are
   * uploaded to the GPU (BufferAttribute.addUpdateRange) — so a focus click
   * that flips 880 primaries costs a fraction of a full 12 MB re-upload, and a
   * no-op repaint costs nothing. Never any geometry work.
   */
  recolor(roleOf: (localId: number) => EdgeRole): void {
    if (!this.lines || !this.colors) return;
    const rgba = roleRgba();
    let dirtyStart = Number.POSITIVE_INFINITY;
    let dirtyEnd = 0;

    for (const [localId, range] of this.ranges) {
      const role = roleOf(localId);
      if (this.lastRole.get(localId) === role) continue;
      this.lastRole.set(localId, role);
      const [r, g, b, a] = rgba[role];
      const end = (range.start + range.count) * 4;
      for (let i = range.start * 4; i < end; i += 4) {
        this.colors[i] = r;
        this.colors[i + 1] = g;
        this.colors[i + 2] = b;
        this.colors[i + 3] = a;
      }
      if (range.start * 4 < dirtyStart) dirtyStart = range.start * 4;
      if (end > dirtyEnd) dirtyEnd = end;
    }
    if (dirtyEnd === 0) return; // nothing changed — no write, no upload

    const attr = this.lines.geometry.getAttribute("color") as THREE.BufferAttribute;
    attr.clearUpdateRanges();
    attr.addUpdateRange(dirtyStart, dirtyEnd - dirtyStart);
    attr.needsUpdate = true;
  }

  dispose(): void {
    this.disposed = true;
    if (this.lines) {
      this.lines.removeFromParent();
      this.lines.geometry.dispose();
      (this.lines.material as THREE.Material).dispose();
      this.lines = null;
    }
    this.colors = null;
    this.ranges.clear();
    this.lastRole.clear();
  }
}
