// Projected-size rendering policy (tasks/task23.md issue 2).
//
// Reduces visualization load by hiding objects that are too small ON SCREEN to
// justify rendering non-fundamental detail. The rule depends ONLY on an object's
// projected screen size — never on its absolute distance from the camera, and
// never on whether the camera is moving. There is no navigation/motion/wake mode
// here: Task 22 removed that machinery precisely because per-gesture transition
// work was the source of interaction hitches, and this policy must not
// reintroduce it.
//
// Two independent inputs decide whether an object may be hidden:
//
//   1. CATEGORY ELIGIBILITY - a one-time, cached classification from deterministic
//      IFC metadata already present in the prepared artifact. Architectural
//      elements are retained at any size; everything else is a hide candidate.
//   2. PROJECTED SIZE - the object's bounding-sphere diameter in CSS pixels under
//      the active perspective camera, with hysteresis so borderline objects do
//      not flicker.
//
// Highlighted / manually selected objects bypass the filter entirely and are
// never hidden (the caller supplies them via `isExempt`).
import * as FRAGS from "@thatopen/fragments";
import * as THREE from "three";

import { geometryRole } from "./viewerTheme";

/** Enter/leave thresholds in CSS px (task23 issue 2). */
export const PROJECTED_SIZE = {
  /** Below this projected diameter a non-fundamental object is hidden. */
  enterPx: 20,
  /** It must grow past this before it is restored. */
  exitPx: 24,
} as const;

/**
 * Categories retained at ANY projected size.
 *
 * `IfcSlab` covers both roof slabs and ordinary floor slabs, which the task
 * requires retaining; the viewer's existing `geometryRole` already separates
 * roof slabs for COLOUR purposes, but for eligibility every slab qualifies.
 */
const ALWAYS_RETAINED_CATEGORY = (category: string): boolean => {
  const cls = category.trim().toLowerCase();
  if (cls === "ifcslab") return true;
  const role = geometryRole(category);
  return role === "wall" || role === "roof";
};

/**
 * Categories retained only when an explicit IFC boolean property says so.
 * Never inferred from name, geometry, position, material, or proximity: a
 * missing, null, or non-boolean value does NOT qualify (task23 issue 2).
 */
const CONDITIONAL_CATEGORIES: Record<string, string> = {
  ifcdoor: "IsExternal",
  ifcwindow: "IsExternal",
  ifccolumn: "LoadBearing",
};

/** Chunk size for worker round trips, so one huge model cannot stall the thread. */
const BATCH = 5000;

/** The Fragments surface this policy uses. Exported so tests can supply a double. */
export interface PolicyModel {
  getCategories(): Promise<string[]>;
  getItemsOfCategories(regexes: RegExp[]): Promise<Record<string, number[]>>;
  getItemsData(ids: number[], config: unknown): Promise<Record<string, unknown>[]>;
  getBoxes(ids: number[]): Promise<THREE.Box3[]>;
  setVisible(ids: number[] | undefined, visible: boolean): Promise<void>;
}

/** The subset of the Fragments item payload this policy reads. */
interface IfcValue {
  value?: unknown;
}
interface IfcProperty {
  Name?: IfcValue;
  NominalValue?: IfcValue;
}
interface IfcPropertySet {
  _category?: IfcValue;
  HasProperties?: IfcProperty[];
}

/**
 * Read one boolean IFC property from an item's `IsDefinedBy` property sets.
 *
 * Returns the value ONLY when it is an explicit boolean. Anything else —
 * absent, null, a string, an enumeration — returns null and therefore does not
 * qualify the object for retention.
 *
 * NOTE: the caller must request `attributesDefault: true`. With a pruned
 * attribute list the Fragments API returns the relation array empty, which
 * silently reads as "property absent" for every object.
 */
export function readExplicitBoolean(
  item: Record<string, unknown> | undefined,
  propertyName: string,
): boolean | null {
  const sets = item?.["IsDefinedBy"];
  if (!Array.isArray(sets)) return null;
  for (const set of sets as IfcPropertySet[]) {
    if (set?._category?.value !== "IFCPROPERTYSET") continue;
    const props = set?.HasProperties;
    if (!Array.isArray(props)) continue;
    for (const p of props) {
      if (p?.Name?.value !== propertyName) continue;
      const value = p?.NominalValue?.value;
      return typeof value === "boolean" ? value : null;
    }
  }
  return null;
}

/**
 * Projected diameter, in CSS px, of a bounding sphere under a perspective camera.
 *
 * `viewportHeightPx` is the CSS height of the render target. The camera's
 * horizontal view offset (task19 §2) rescales only the horizontal axis — it
 * passes `fullHeight === height` — so the vertical mapping used here stays
 * correct with or without an offset.
 *
 * A camera inside the sphere returns Infinity (treated as "large"), so an object
 * enclosing the viewer is never hidden.
 */
export function projectedDiameterPx(
  center: THREE.Vector3,
  radius: number,
  camera: THREE.PerspectiveCamera,
  viewportHeightPx: number,
): number {
  const distance = camera.position.distanceTo(center);
  if (!Number.isFinite(distance) || distance <= radius) return Infinity;
  const halfFov = THREE.MathUtils.degToRad(camera.fov) / 2;
  const worldHeightAtDistance = 2 * distance * Math.tan(halfFov);
  if (worldHeightAtDistance <= 0) return Infinity;
  return (2 * radius * viewportHeightPx) / worldHeightAtDistance;
}

export interface VisibilityDelta {
  hide: number[];
  show: number[];
}

export class ProjectedSizePolicy {
  /** Hide candidates only — architectural elements are never tracked or hidden. */
  private candidates: number[] = [];
  private centers = new Float32Array(0);
  private radii = new Float32Array(0);
  /** Hysteresis state, parallel to `candidates`: 1 = currently hidden. */
  private hiddenState = new Uint8Array(0);
  private indexOf = new Map<number, number>();
  private ready = false;
  private retainedCount = 0;

  isReady(): boolean {
    return this.ready;
  }

  /** Objects retained at any size (for tests/diagnostics). */
  getRetainedCount(): number {
    return this.retainedCount;
  }

  getCandidateCount(): number {
    return this.candidates.length;
  }

  isHidden(localId: number): boolean {
    const i = this.indexOf.get(localId);
    return i === undefined ? false : this.hiddenState[i] === 1;
  }

  /** Every id currently hidden by this policy. */
  hiddenIds(): number[] {
    const out: number[] = [];
    for (let i = 0; i < this.candidates.length; i++) {
      if (this.hiddenState[i] === 1) out.push(this.candidates[i]!);
    }
    return out;
  }

  /**
   * One-time classification + bounding-volume cache for a freshly loaded model.
   *
   * Runs entirely against the prepared artifact — no backend, database,
   * embedding, or LLM call, here or later. Resolves false when the required
   * Fragments APIs are unavailable, in which case the caller must leave every
   * object visible (fail-safe: the policy is an optimization, never a
   * correctness requirement).
   *
   * Candidates self-restrict to geometry-bearing items: `getBoxes` returns an
   * empty box for an item with no geometry, and those are skipped below. Only a
   * rendered object can be hidden, so this is the correct universe.
   */
  async prepare(model: PolicyModel, renderableIds: number[]): Promise<boolean> {
    this.reset();
    if (typeof model.getBoxes !== "function" || typeof model.setVisible !== "function") {
      return false;
    }
    try {
      const renderable = new Set(renderableIds);
      const retained = await this.classifyRetained(model, renderable);
      this.retainedCount = retained.size;
      this.candidates = renderableIds.filter((id) => !retained.has(id));

      const centers = new Float32Array(this.candidates.length * 3);
      const radii = new Float32Array(this.candidates.length);
      const size = new THREE.Vector3();
      const center = new THREE.Vector3();
      let written = 0;
      const kept: number[] = [];

      for (let start = 0; start < this.candidates.length; start += BATCH) {
        const slice = this.candidates.slice(start, start + BATCH);
        const boxes = await model.getBoxes(slice);
        for (let i = 0; i < slice.length; i++) {
          const box = boxes[i];
          if (!box || box.isEmpty?.()) continue; // no geometry -> nothing to hide
          box.getCenter(center);
          box.getSize(size);
          const radius = size.length() / 2;
          if (!Number.isFinite(radius) || radius <= 0) continue;
          centers[written * 3] = center.x;
          centers[written * 3 + 1] = center.y;
          centers[written * 3 + 2] = center.z;
          radii[written] = radius;
          kept.push(slice[i]!);
          written += 1;
        }
      }

      this.candidates = kept;
      this.centers = centers.subarray(0, written * 3);
      this.radii = radii.subarray(0, written);
      this.hiddenState = new Uint8Array(written);
      this.indexOf = new Map(kept.map((id, i) => [id, i]));
      this.ready = true;
      return true;
    } catch {
      this.reset();
      return false;
    }
  }

  /**
   * Which categories are retained at any projected size.
   *
   * Always-retained categories are taken wholesale. Conditional categories
   * (doors/windows/columns) are read per item from explicit IFC booleans.
   */
  private async classifyRetained(
    model: PolicyModel,
    renderable: Set<number>,
  ): Promise<Set<number>> {
    const retained = new Set<number>();
    const categories = await model.getCategories();

    const always = categories.filter(ALWAYS_RETAINED_CATEGORY);
    if (always.length) {
      const byCategory = await model.getItemsOfCategories(
        always.map((c) => new RegExp(`^${c}$`)),
      );
      for (const ids of Object.values(byCategory)) {
        for (const id of ids ?? []) {
          if (renderable.has(id)) retained.add(id);
        }
      }
    }

    for (const category of categories) {
      const property = CONDITIONAL_CATEGORIES[category.trim().toLowerCase()];
      if (!property) continue;
      const byCategory = await model.getItemsOfCategories([new RegExp(`^${category}$`)]);
      // Filter to renderable items BEFORE the per-item property read, which is
      // by far the most expensive step on a large model.
      const ids = Object.values(byCategory)
        .flat()
        .filter((id) => renderable.has(id));
      for (let start = 0; start < ids.length; start += BATCH) {
        const slice = ids.slice(start, start + BATCH);
        // `attributesDefault: true` is REQUIRED — see readExplicitBoolean.
        const data = await model.getItemsData(slice, {
          attributesDefault: true,
          relations: { IsDefinedBy: { attributes: true, relations: true } },
        });
        for (let i = 0; i < slice.length; i++) {
          if (readExplicitBoolean(data[i], property) === true) retained.add(slice[i]!);
        }
      }
    }
    return retained;
  }

  /**
   * Recompute the hysteresis state for the current camera and return only the
   * ids whose visibility actually CHANGED, so the caller issues one bounded
   * visibility write instead of touching the whole model.
   *
   * `isExempt` marks highlighted / manually selected objects, which are always
   * shown regardless of size or category.
   */
  evaluate(
    camera: THREE.PerspectiveCamera,
    viewportHeightPx: number,
    isExempt: (localId: number) => boolean,
  ): VisibilityDelta {
    const delta: VisibilityDelta = { hide: [], show: [] };
    if (!this.ready || viewportHeightPx <= 0) return delta;

    const halfFov = THREE.MathUtils.degToRad(camera.fov) / 2;
    const tanHalfFov = Math.tan(halfFov);
    if (!Number.isFinite(tanHalfFov) || tanHalfFov <= 0) return delta;

    const cam = camera.position;
    for (let i = 0; i < this.candidates.length; i++) {
      const id = this.candidates[i]!;
      const wasHidden = this.hiddenState[i] === 1;

      if (isExempt(id)) {
        if (wasHidden) {
          this.hiddenState[i] = 0;
          delta.show.push(id);
        }
        continue;
      }

      const dx = this.centers[i * 3]! - cam.x;
      const dy = this.centers[i * 3 + 1]! - cam.y;
      const dz = this.centers[i * 3 + 2]! - cam.z;
      const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
      const radius = this.radii[i]!;

      let px: number;
      if (!Number.isFinite(distance) || distance <= radius) {
        px = Infinity;
      } else {
        px = (2 * radius * viewportHeightPx) / (2 * distance * tanHalfFov);
      }

      // Hysteresis: between the thresholds an object keeps its previous state.
      if (!wasHidden && px < PROJECTED_SIZE.enterPx) {
        this.hiddenState[i] = 1;
        delta.hide.push(id);
      } else if (wasHidden && px > PROJECTED_SIZE.exitPx) {
        this.hiddenState[i] = 0;
        delta.show.push(id);
      }
    }
    return delta;
  }

  /** Clear hysteresis state and report everything that must be made visible again. */
  restoreAll(): number[] {
    const shown = this.hiddenIds();
    this.hiddenState.fill(0);
    return shown;
  }

  reset(): void {
    this.candidates = [];
    this.centers = new Float32Array(0);
    this.radii = new Float32Array(0);
    this.hiddenState = new Uint8Array(0);
    this.indexOf = new Map();
    this.ready = false;
    this.retainedCount = 0;
  }
}

/** Narrowing helper so the adapter can pass its concrete model in safely. */
export function asPolicyModel(model: FRAGS.FragmentsModel): PolicyModel {
  return model as unknown as PolicyModel;
}
