// Spatially chunked entity edge overlay (tasks/task15.md §2; rewritten by
// tasks/task18.md §7 from a single whole-model object into 20-160 spatially
// bounded `THREE.LineSegments` chunks with real frustum culling).
//
// Geometry comes from the already-loaded Fragments model (`getItemsGeometry`,
// the same mechanism the component preview uses), run through
// THREE.EdgesGeometry per mesh. Each entity's edges are bucketed into a
// uniform 3D grid cell by their centroid; every populated cell becomes one
// merged LineSegments with its own RGBA vertex-color buffer, computed
// bounding sphere/box, and `frustumCulled = true` — off-screen chunks are
// skipped by Three.js's own culling, something a single whole-model object
// (with `frustumCulled` forced false, since culling an all-encompassing box
// is meaningless) could never do.
//
// Because color/alpha live per-vertex within each chunk, a highlight change
// never rebuilds geometry: it rewrites the color ranges of the affected
// entities in their owning chunk and flips that chunk's `needsUpdate`. Edge
// colors follow the entity's CURRENT face role and are derived exclusively
// from viewerTheme's EDGES block (darken factor + per-role alpha) — nothing
// is hard-coded here.
//
// Measured basis for the original single-object design (Node probe on the
// real Schependomlaan artifact): 3,505 items / 5,973 meshes / 258k triangles
// → 187k edge segments, ~10 MB of buffers, ~1.3 s to extract. The build
// therefore still runs asynchronously AFTER scene-ready, in yielded batches,
// so it never blocks load or input — chunking adds a cheap grid-bucketing
// step inline in that same loop, not a second pass.
//
// tasks/task20.md §1/§2 replaced task18's motion handling: camera motion used
// to hide base edges by rewriting every non-highlighted vertex's ALPHA across
// all chunks (still submitted to the GPU at alpha 0) and requesting a color
// upload on every hide/restore. That regressed real-hardware interaction on
// large models. Motion now toggles each chunk's `lines.visible` instead — a
// bounded, cheap per-chunk boolean flip that actually removes the geometry
// from the draw, with zero color-buffer writes. Selected/query-primary edges
// stay visible via a small SEPARATE highlight overlay (below), maintained
// only by recolor()'s existing role-diff loop, never by motion.
import * as FRAGS from "@thatopen/fragments";
import * as THREE from "three";

import { EDGE_RESTORE_DELAY_MS, EDGES, VIEWER_COLORS } from "./viewerTheme";

export type EdgeRole = keyof typeof EDGES.alpha;

/** Roles that stay visible while the camera moves (task18 §5) — selected and
 * query-primary results. Everything else (base roof/wall/other/dim/context)
 * hides during motion and restores after rest settles. Chunks containing at
 * least one of these roles also get a relaxed screen-size LOD threshold
 * (task18 §8), so they stay legible farther from the camera than base context. */
const VISIBLE_DURING_MOTION = new Set<EdgeRole>(["primary", "primaryUnfocused", "manual"]);

/** Items whose EdgesGeometry is extracted per main-thread slice before
 * yielding. Geometry itself is fetched from the worker in ONE call — batching
 * that fetch multiplies postMessage serialization overhead enormously. */
const EXTRACT_BATCH = 100;

/** Target items per grid CELL (task18 §7). Architectural geometry clusters
 * non-uniformly within its axis-aligned bounding box (e.g. a building
 * footprint leaves most of the box above/around it empty), so the populated
 * chunk count measured on model 2 came in well under the target grid
 * resolution (47 populated cells from a 124-cell target, ~38% occupancy).
 * This value is tuned down accordingly so the resulting POPULATED count (not
 * the raw grid resolution) lands in the accepted 50-150 range for model 2. */
const ITEMS_PER_CHUNK_TARGET = 90;
const MIN_GRID_CHUNKS = 20;
// A safety valve on the raw grid RESOLUTION, not the populated chunk count
// the task bounds (50-150) — occupancy is well under 100% for architectural
// geometry (see ITEMS_PER_CHUNK_TARGET), so the grid target must run higher
// than 150 for the resulting populated count to land in that range.
const MAX_GRID_CHUNKS = 500;

interface VertexRange {
  chunkIndex: number;
  start: number; // first vertex index WITHIN the owning chunk's buffers
  count: number; // number of vertices
}

interface Chunk {
  lines: THREE.LineSegments;
  colors: Float32Array;
  /** Count of entities in this chunk currently in a VISIBLE_DURING_MOTION role
   * (task18 §8) — kept incrementally by recolor(), never rescanned. */
  highlightCount: number;
  /** Screen-size LOD hysteresis state (task18 §8): true once culled, cleared
   * only after growing past the (relaxed, if highlighted) exit threshold. */
  lodCulled: boolean;
}

/**
 * A small, always-separate overlay of ONLY the currently highlighted
 * (query-primary/manual) entities' edges (task20 §2), rebuilt exclusively by
 * recolor()'s existing role-diff loop — never by camera motion. Positions and
 * colors are sliced directly out of the owning base chunk's already-extracted
 * typed arrays, so building it costs no worker round trip and never clones
 * the full edge dataset.
 */
interface HighlightOverlay {
  lines: THREE.LineSegments;
  ranges: Map<number, VertexRange>;
}

interface GridDims {
  nx: number;
  ny: number;
  nz: number;
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

/**
 * Per-axis cell counts weighted by that axis's extent (task18 §7 "balanced by
 * spatial extent") — a flat, wide building doesn't get uselessly split along
 * its thin vertical axis. A uniform grid (not an octree/k-d tree) is used
 * deliberately: it's O(1) per vertex to bucket, fully deterministic, and
 * simple enough to unit-test exactly — an octree's recursive split adds
 * complexity this scale doesn't need.
 */
function chooseGridDims(size: THREE.Vector3, targetChunks: number): GridDims {
  const sx = Math.max(size.x, 1e-3);
  const sy = Math.max(size.y, 1e-3);
  const sz = Math.max(size.z, 1e-3);
  const geomean = Math.cbrt(sx * sy * sz);
  const n = Math.cbrt(Math.max(targetChunks, 1));
  return {
    nx: Math.max(1, Math.round(n * (sx / geomean))),
    ny: Math.max(1, Math.round(n * (sy / geomean))),
    nz: Math.max(1, Math.round(n * (sz / geomean))),
  };
}

function clampInt(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, Math.floor(v)));
}

export class EdgeOverlay {
  private chunks: Chunk[] = [];
  private ranges = new Map<number, VertexRange>();
  /** Last role written per entity — lets recolor skip unchanged entities. */
  private lastRole = new Map<number, EdgeRole>();
  private disposed = false;
  private building = false;
  private buildMs: number | null = null;
  private itemCount = 0;
  private vertexCount = 0;
  private motionHidden = false;
  private restoreTimer: ReturnType<typeof setTimeout> | null = null;
  /** Same object every chunk (and the highlight overlay) is mounted under. */
  private parentObj: THREE.Object3D | null = null;
  private highlight: HighlightOverlay | null = null;
  private thresholdDeg: number = EDGES.thresholdAngleDeg.balanced;

  isBuilt(): boolean {
    return this.chunks.length > 0 && !this.disposed;
  }

  /** Wall-clock build duration in ms once built — for the task15 §2 gate. */
  getBuildMs(): number | null {
    return this.buildMs;
  }

  /** Total model item count seen during the last build (tasks/task18.md §1 instrumentation). */
  getItemCount(): number {
    return this.itemCount;
  }

  /** Edge vertex count of the built overlay (tasks/task18.md §1 instrumentation). */
  getVertexCount(): number {
    return this.vertexCount;
  }

  /** Populated spatial chunk count (tasks/task18.md §1/§7 instrumentation). */
  getChunkCount(): number {
    return this.chunks.length;
  }

  /** Base chunks currently submitted for rendering (tasks/task20.md §6 instrumentation) —
   * 0 while motion-hidden, since chunks are toggled invisible, not alpha-zeroed. */
  getVisibleChunkCount(): number {
    return this.chunks.reduce((n, c) => n + (c.lines.visible ? 1 : 0), 0);
  }

  /** True while base chunks are hidden for camera motion (tasks/task20.md §2). */
  isMotionHidden(): boolean {
    return this.motionHidden;
  }

  /** Vertex count of the small always-separate highlight overlay, or 0 (tasks/task20.md §2/§6). */
  getHighlightVertexCount(): number {
    if (!this.highlight) return 0;
    return (this.highlight.lines.geometry.getAttribute("position") as THREE.BufferAttribute).count;
  }

  /** Whether a highlight overlay drawable currently exists (tasks/task20.md §6). */
  hasHighlightOverlay(): boolean {
    return this.highlight !== null;
  }

  /**
   * Extract edges for every item with geometry and mount them as spatially
   * bounded `THREE.LineSegments` chunks under `parent` (the model's own
   * object, so every chunk inherits its transform).
   *
   * The geometry is fetched from the Fragments worker in a SINGLE call — the
   * worker prepares it off the main thread, and one round trip avoids the
   * per-batch postMessage serialization that measurably froze the viewer when
   * this was first written batched. Only the main-thread EdgesGeometry pass
   * (plus the cheap grid-bucketing of each entity's centroid) is sliced,
   * yielding between slices so orbit/pan/zoom stay responsive. Safe to
   * abandon via dispose() mid-build. Returns true when mounted.
   *
   * `thresholdDeg` (task18 §6) is chosen by the caller from the model's
   * provisional profile — a larger model builds at the coarser angle from
   * this first pass, not a second rebuild. `localIds`, if the caller already
   * fetched them (e.g. for provisional profile detection), avoids a second
   * `getLocalIds()` worker round trip.
   */
  async build(
    model: FRAGS.FragmentsModel,
    parent: THREE.Object3D,
    options?: { thresholdDeg?: number; localIds?: number[] },
  ): Promise<boolean> {
    if (this.disposed || this.building || this.chunks.length > 0) return this.isBuilt();
    this.building = true;
    this.parentObj = parent;
    this.thresholdDeg = options?.thresholdDeg ?? EDGES.thresholdAngleDeg.balanced;
    const started = performance.now();
    try {
      // All local ids, plain numbers on every model flavor. (The worker's
      // getItemsWithGeometry returns Item wrappers whose local id is async —
      // extracting from it silently yielded zero ids when this was first
      // written.) Items without geometry simply produce no meshes below.
      const localIds: number[] = options?.localIds ?? (await model.getLocalIds());
      this.itemCount = localIds.length;
      if (localIds.length === 0) return false;

      // One worker round trip for everything (measured 70 ms in the browser
      // for all 5,973 meshes of the current model).
      const perItem = await model.getItemsGeometry(localIds);
      if (this.disposed) return false;

      // The model's own bounding box drives the grid: prefer the Fragments-
      // reported box (cheap, already computed); fall back to accumulating one
      // from extracted positions if unavailable, since a grid needs SOME
      // extent to bucket into.
      let box: THREE.Box3;
      try {
        box = model.box ? model.box.clone() : new THREE.Box3();
      } catch {
        box = new THREE.Box3();
      }
      const boxKnownUpfront = !box.isEmpty();
      const targetChunks = clampInt(localIds.length / ITEMS_PER_CHUNK_TARGET, MIN_GRID_CHUNKS, MAX_GRID_CHUNKS);

      interface ChunkBuild {
        verts: Float32Array[];
        vertexCount: number;
        entities: Map<number, { start: number; count: number }>;
      }
      const chunkBuilds = new Map<string, ChunkBuild>();
      // Entities extracted before the box/grid is known (only possible when
      // `model.box` was empty) are buffered and bucketed in a second, still-
      // yielded pass once the accumulated box is available.
      const deferred: Array<{ localId: number; edges: Float32Array[]; vertexCount: number }> = [];
      const accumulatedBox = boxKnownUpfront ? null : new THREE.Box3();

      let totalVertexCount = 0;
      for (let offset = 0; offset < localIds.length; offset += EXTRACT_BATCH) {
        if (this.disposed) return false; // model switched away mid-build
        const end = Math.min(offset + EXTRACT_BATCH, localIds.length);
        for (let i = offset; i < end; i++) {
          const localId = localIds[i]!;
          const entityEdges: Float32Array[] = [];
          let entityVertexCount = 0;
          for (const mesh of perItem[i] ?? []) {
            const edge = this.extractEdges(mesh);
            if (!edge) continue;
            entityEdges.push(edge);
            entityVertexCount += edge.length / 3;
          }
          if (entityVertexCount === 0) continue;
          totalVertexCount += entityVertexCount;

          if (boxKnownUpfront) {
            this.bucketEntity(localId, entityEdges, entityVertexCount, box, targetChunks, chunkBuilds);
          } else {
            deferred.push({ localId, edges: entityEdges, vertexCount: entityVertexCount });
            for (const edge of entityEdges) {
              for (let v = 0; v < edge.length; v += 3) {
                accumulatedBox!.expandByPoint(new THREE.Vector3(edge[v], edge[v + 1], edge[v + 2]));
              }
            }
          }
        }
        // Yield so orbit/pan/zoom stay responsive during the one-time build.
        await yieldToLoop();
      }
      if (this.disposed || totalVertexCount === 0) return false;

      if (!boxKnownUpfront) {
        box = accumulatedBox!;
        for (let offset = 0; offset < deferred.length; offset += EXTRACT_BATCH) {
          if (this.disposed) return false;
          const end = Math.min(offset + EXTRACT_BATCH, deferred.length);
          for (let i = offset; i < end; i++) {
            const entry = deferred[i]!;
            this.bucketEntity(entry.localId, entry.edges, entry.vertexCount, box, targetChunks, chunkBuilds);
          }
          await yieldToLoop();
        }
        if (this.disposed) return false;
      }

      // Finalize: one BufferGeometry/LineSegments per populated cell, with a
      // real computed bounding sphere/box and frustumCulled left ON — the
      // opposite of the old single whole-model object, which forced it off
      // because culling an all-encompassing box was meaningless.
      const chunks: Chunk[] = [];
      const ranges = new Map<number, VertexRange>();
      for (const build of chunkBuilds.values()) {
        if (this.disposed) return false;
        const positions = new Float32Array(build.vertexCount * 3);
        let cursor = 0;
        for (const v of build.verts) {
          positions.set(v, cursor);
          cursor += v.length;
        }
        const colors = new Float32Array(build.vertexCount * 4);
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute("color", new THREE.BufferAttribute(colors, 4));
        geometry.computeBoundingSphere();
        geometry.computeBoundingBox();
        const material = new THREE.LineBasicMaterial({
          vertexColors: true,
          transparent: true, // per-vertex alpha (RGBA attribute) needs blending on
          depthWrite: false,
        });
        const lines = new THREE.LineSegments(geometry, material);
        lines.frustumCulled = true; // spatially bounded — real culling now applies
        lines.renderOrder = 1; // draw after the faces they outline
        parent.add(lines);

        const chunkIndex = chunks.length;
        chunks.push({ lines, colors, highlightCount: 0, lodCulled: false });
        for (const [localId, range] of build.entities) {
          ranges.set(localId, { chunkIndex, start: range.start, count: range.count });
        }
      }

      this.chunks = chunks;
      this.ranges = ranges;
      this.vertexCount = totalVertexCount;
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

  /** Bucket one entity's already-extracted edge vertices into its grid cell. */
  private bucketEntity(
    localId: number,
    entityEdges: Float32Array[],
    entityVertexCount: number,
    box: THREE.Box3,
    targetChunks: number,
    chunkBuilds: Map<
      string,
      { verts: Float32Array[]; vertexCount: number; entities: Map<number, { start: number; count: number }> }
    >,
  ): void {
    let sumX = 0;
    let sumY = 0;
    let sumZ = 0;
    for (const edge of entityEdges) {
      for (let v = 0; v < edge.length; v += 3) {
        sumX += edge[v]!;
        sumY += edge[v + 1]!;
        sumZ += edge[v + 2]!;
      }
    }
    const cx = sumX / entityVertexCount;
    const cy = sumY / entityVertexCount;
    const cz = sumZ / entityVertexCount;
    const key = this.cellKey(cx, cy, cz, box, targetChunks);

    let build = chunkBuilds.get(key);
    if (!build) {
      build = { verts: [], vertexCount: 0, entities: new Map() };
      chunkBuilds.set(key, build);
    }
    const start = build.vertexCount;
    for (const edge of entityEdges) {
      build.verts.push(edge);
      build.vertexCount += edge.length / 3;
    }
    build.entities.set(localId, { start, count: build.vertexCount - start });
  }

  private gridDimsCache: { dims: GridDims; size: THREE.Vector3 } | null = null;

  private cellKey(x: number, y: number, z: number, box: THREE.Box3, targetChunks: number): string {
    if (!this.gridDimsCache) {
      const size = new THREE.Vector3();
      box.getSize(size);
      this.gridDimsCache = { dims: chooseGridDims(size, targetChunks), size };
    }
    const { dims, size } = this.gridDimsCache;
    const ix = clampInt(((x - box.min.x) / (size.x || 1)) * dims.nx, 0, dims.nx - 1);
    const iy = clampInt(((y - box.min.y) / (size.y || 1)) * dims.ny, 0, dims.ny - 1);
    const iz = clampInt(((z - box.min.z) / (size.z || 1)) * dims.nz, 0, dims.nz - 1);
    return `${ix},${iy},${iz}`;
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
      const edges = new THREE.EdgesGeometry(geometry, this.thresholdDeg);
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
   * role actually CHANGED are rewritten, and only the touched span of each
   * TOUCHED chunk is uploaded to the GPU (BufferAttribute.addUpdateRange) —
   * so a focus click that flips 880 scattered primaries costs a handful of
   * small per-chunk uploads (strictly less total work than the old single
   * whole-model envelope upload for the same scattered change), and a no-op
   * repaint costs nothing. Never any geometry work.
   *
   * Also maintains the small highlight overlay (task20 §2): whenever an
   * entity's role enters or leaves `VISIBLE_DURING_MOTION`, its slot in
   * `highlightRanges` is added/removed and `rebuildHighlightOverlay()` is
   * called ONCE at the end if anything highlighted-related changed — never
   * from camera motion, only from a real role diff right here.
   */
  recolor(roleOf: (localId: number) => EdgeRole): void {
    if (this.chunks.length === 0) return;
    const rgba = roleRgba();
    const dirtyByChunk = new Map<number, { start: number; end: number }>();
    const highlightRanges = this.highlight?.ranges ?? new Map<number, VertexRange>();
    let highlightDirty = false;

    for (const [localId, range] of this.ranges) {
      const role = roleOf(localId);
      const prevRole = this.lastRole.get(localId);
      if (prevRole === role) continue;
      this.lastRole.set(localId, role);

      const chunk = this.chunks[range.chunkIndex]!;
      const wasHighlighted = prevRole !== undefined && VISIBLE_DURING_MOTION.has(prevRole);
      const isHighlighted = VISIBLE_DURING_MOTION.has(role);
      if (wasHighlighted) chunk.highlightCount -= 1;
      if (isHighlighted) chunk.highlightCount += 1;

      const [r, g, b, a] = rgba[role];
      const end = (range.start + range.count) * 4;
      for (let i = range.start * 4; i < end; i += 4) {
        chunk.colors[i] = r;
        chunk.colors[i + 1] = g;
        chunk.colors[i + 2] = b;
        chunk.colors[i + 3] = a;
      }
      const span = dirtyByChunk.get(range.chunkIndex);
      if (!span) dirtyByChunk.set(range.chunkIndex, { start: range.start * 4, end });
      else {
        if (range.start * 4 < span.start) span.start = range.start * 4;
        if (end > span.end) span.end = end;
      }

      if (isHighlighted) {
        highlightRanges.set(localId, range);
        highlightDirty = true;
      } else if (wasHighlighted) {
        highlightRanges.delete(localId);
        highlightDirty = true;
      }
    }

    for (const [chunkIndex, span] of dirtyByChunk) {
      const attr = this.chunks[chunkIndex]!.lines.geometry.getAttribute("color") as THREE.BufferAttribute;
      attr.clearUpdateRanges();
      attr.addUpdateRange(span.start, span.end - span.start);
      attr.needsUpdate = true;
    }
    if (highlightDirty) this.rebuildHighlightOverlay(highlightRanges);
  }

  /**
   * Rebuilds the small highlight overlay from the current `highlightRanges`
   * (task20 §2). Positions and colors are sliced directly out of the owning
   * base chunk's ALREADY-EXTRACTED typed arrays — no worker round trip, no
   * whole-model clone, bounded by the (small) highlighted vertex count. Only
   * called from `recolor()`'s diff above, never from `setMotion()`.
   */
  private rebuildHighlightOverlay(ranges: Map<number, VertexRange>): void {
    if (ranges.size === 0) {
      if (this.highlight) {
        this.highlight.lines.removeFromParent();
        this.highlight.lines.geometry.dispose();
        (this.highlight.lines.material as THREE.Material).dispose();
        this.highlight = null;
      }
      return;
    }

    let total = 0;
    for (const r of ranges.values()) total += r.count;
    const positions = new Float32Array(total * 3);
    const colors = new Float32Array(total * 4);
    let cursor = 0;
    for (const r of ranges.values()) {
      const chunk = this.chunks[r.chunkIndex]!;
      const posArr = (chunk.lines.geometry.getAttribute("position") as THREE.BufferAttribute)
        .array as Float32Array;
      positions.set(posArr.subarray(r.start * 3, (r.start + r.count) * 3), cursor * 3);
      colors.set(chunk.colors.subarray(r.start * 4, (r.start + r.count) * 4), cursor * 4);
      cursor += r.count;
    }

    if (!this.highlight) {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute("color", new THREE.BufferAttribute(colors, 4));
      const material = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false });
      const lines = new THREE.LineSegments(geometry, material);
      // Highlighted results can be scattered across the whole building, so a
      // bounding sphere here would be nearly as large as the model itself —
      // frustum culling would be as meaningless as it was for the old
      // whole-model object (task18 §7's reasoning applies identically).
      lines.frustumCulled = false;
      lines.renderOrder = 2; // draw after base chunks (renderOrder 1)
      // Only shown WHILE base chunks are hidden — at rest the base chunks
      // already draw these same vertices in the correct color, so keeping
      // both visible would just be redundant overdraw (task20 §2).
      lines.visible = this.motionHidden;
      this.parentObj?.add(lines);
      this.highlight = { lines, ranges };
    } else {
      const geometry = this.highlight.lines.geometry;
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      geometry.setAttribute("color", new THREE.BufferAttribute(colors, 4));
      this.highlight.ranges = ranges;
    }
  }

  /** Derives a chunk's actual visibility from motion + LOD state so the two
   * mechanisms can never fight each other (task20 §2). */
  private applyChunkVisibility(chunk: Chunk): void {
    chunk.lines.visible = !this.motionHidden && !chunk.lodCulled;
  }

  /**
   * Camera motion state (task20 §1/§2 — replaces task18 §5's per-vertex alpha
   * hiding). On movement start, EVERY populated base chunk is hidden via
   * `lines.visible = false` — a bounded O(chunks) boolean write, never a
   * per-vertex color rewrite, never a GPU color upload, never geometry work.
   * On rest, after `EDGE_RESTORE_DELAY_MS` (cancelled/restarted if movement
   * resumes first), chunks are restored through `applyChunkVisibility` so an
   * LOD-culled chunk doesn't incorrectly reappear. The small highlight
   * overlay (if any) is kept in lockstep so it is visible ONLY while base
   * chunks are hidden. `onDirty` is called (synchronously on hide, or from
   * the delayed restore) so the caller can request a render frame without
   * this class needing a scheduler reference.
   */
  setMotion(moving: boolean, onDirty: () => void): void {
    if (this.restoreTimer !== null) {
      clearTimeout(this.restoreTimer);
      this.restoreTimer = null;
    }
    if (moving) {
      if (this.motionHidden) return;
      this.motionHidden = true;
      for (const chunk of this.chunks) this.applyChunkVisibility(chunk);
      if (this.highlight) this.highlight.lines.visible = true;
      onDirty();
    } else {
      this.restoreTimer = setTimeout(() => {
        this.restoreTimer = null;
        if (!this.motionHidden) return;
        this.motionHidden = false;
        for (const chunk of this.chunks) this.applyChunkVisibility(chunk);
        if (this.highlight) this.highlight.lines.visible = false;
        onDirty();
      }, EDGE_RESTORE_DELAY_MS);
    }
  }

  /**
   * Screen-size LOD culling per chunk (task18 §8): approximates each chunk's
   * projected size from its bounding sphere (cheap — tens to ~160 chunks, not
   * a per-edge per-frame CPU projection across the whole model) and hides
   * chunks that have shrunk below a sub-pixel threshold, with hysteresis so
   * borderline chunks don't flicker. Chunks containing a selected/query-
   * primary entity use a stricter (closer) pair of thresholds so they stay
   * visible farther from the camera than base context (`highlightCount`,
   * maintained incrementally by `recolor()`).
   *
   * Called at a bounded rate by the caller (e.g. on camera rest, not every
   * frame during motion) — never a per-edge-per-frame cost.
   */
  updateLod(camera: THREE.PerspectiveCamera, viewportHeightPx: number): void {
    if (this.chunks.length === 0) return;
    const fovRad = THREE.MathUtils.degToRad(camera.fov);
    const halfTan = Math.tan(fovRad / 2);
    if (halfTan <= 0) return;
    const worldCenter = new THREE.Vector3();

    for (const chunk of this.chunks) {
      const sphere = chunk.lines.geometry.boundingSphere;
      if (!sphere || sphere.radius <= 0) continue;
      chunk.lines.localToWorld(worldCenter.copy(sphere.center));
      const distance = Math.max(camera.position.distanceTo(worldCenter), 1e-6);
      const projectedPx = sphere.radius / (distance * halfTan) * (viewportHeightPx / 2);

      const highlighted = chunk.highlightCount > 0;
      const enterPx = highlighted ? EDGES.lod.highlightFarEnterPx : EDGES.lod.farEnterPx;
      const exitPx = highlighted ? EDGES.lod.highlightFarExitPx : EDGES.lod.farExitPx;

      if (chunk.lodCulled) {
        if (projectedPx > exitPx) chunk.lodCulled = false;
      } else if (projectedPx < enterPx) {
        chunk.lodCulled = true;
      }
      this.applyChunkVisibility(chunk);
    }
  }

  dispose(): void {
    this.disposed = true;
    if (this.restoreTimer !== null) {
      clearTimeout(this.restoreTimer);
      this.restoreTimer = null;
    }
    for (const chunk of this.chunks) {
      chunk.lines.removeFromParent();
      chunk.lines.geometry.dispose();
      (chunk.lines.material as THREE.Material).dispose();
    }
    this.chunks = [];
    this.ranges.clear();
    this.lastRole.clear();
    this.gridDimsCache = null;
    if (this.highlight) {
      this.highlight.lines.removeFromParent();
      this.highlight.lines.geometry.dispose();
      (this.highlight.lines.material as THREE.Material).dispose();
      this.highlight = null;
    }
    this.parentObj = null;
  }
}
