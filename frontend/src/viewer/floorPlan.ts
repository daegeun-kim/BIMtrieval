// Floor-plan range derivation (tasks/task28.md §3). PURE arithmetic over
// already-resolved SCENE elevations — no Three.js scene access, no Fragments
// call, no React. The imperative half (views, clipping, section geometry) lives
// in ViewerAdapter; this module owns the numbers so they can be tested exactly.
//
// The load-bearing distinction this module exists to enforce:
//
//     A database `IfcBuildingStorey.Elevation` is NOT a Three.js Y value.
//
// The backend's `/floors` contract reports elevations in the model's own project
// length unit, for diagnostics only. A band is mapped into the loaded artifact's
// scene space by reading each constituent storey's ARTIFACT-native elevation and
// the model's own public coordinate/placement information — the same path the
// installed `Views.createFromIfcStoreys` takes (`Elevation + coordinates[1]`,
// then the model object's own world matrix). No model-specific offset, no
// `model.box.min.y` as a floor height, no geometry centroid.
import { PLAN } from "./viewerTheme";

/**
 * Smallest meaningful step of a Float32 value near 1.0. Scene coordinates reach
 * the GPU as Float32, so this — not `Number.EPSILON` — is the precision floor
 * that matters for two clipping planes that must not coincide.
 */
export const FLOAT32_EPSILON = 1.1920929e-7;

/**
 * Separation between the upper cut and the next band's lowest surface, so the
 * two clipping planes can never land on the same value.
 *
 * Derived from Float32 precision AT THE MODEL'S OWN SCALE (a few ULPs of the
 * larger operand), never from a model name, file, or hand-tuned constant: a
 * millimetre-unit model and a metre-unit model each get a tolerance
 * proportional to the magnitudes actually being compared.
 */
export function planeTolerance(...magnitudes: number[]): number {
  const scale = Math.max(1, ...magnitudes.map((m) => Math.abs(m)).filter(Number.isFinite));
  return scale * FLOAT32_EPSILON * PLAN.toleranceUlps;
}

/**
 * Scene-space Y of one storey, in the loaded artifact's own coordinates.
 *
 * `elevation` is the artifact-native `Elevation` attribute and `coordinateHeight`
 * is `(await model.getCoordinates())[1]` — exactly the pair the installed
 * `Views.createFromIfcStoreys` adds together. That sum is in the model object's
 * LOCAL space, so callers must still push it through the model's own world
 * matrix (see `ViewerAdapter.resolveSceneBands`) before comparing it with
 * `model.box`, which Fragments already reports in world space.
 */
export function storeyLocalY(elevation: number, coordinateHeight: number): number {
  return elevation + coordinateHeight;
}

/** One logical floor band, already mapped into scene space (or explicitly not). */
export interface SceneBand {
  bandIndex: number;
  label: string;
  /** Lowest resolved scene Y among the band's constituent storeys. */
  minSceneY: number;
  /** Highest resolved scene Y among the band's constituent storeys. */
  maxSceneY: number;
  /** False when the artifact could not resolve a finite scene elevation. */
  resolved: boolean;
}

/** The active plan view range: everything between `lower` and `cut`. */
export interface PlanRange {
  /** Upper horizontal cut, in scene Y. */
  cut: number;
  /** Lower range boundary, in scene Y. */
  lower: number;
  /** True when the nominal 1.2 m cut was pulled down under the next band. */
  constrainedByNextBand: boolean;
}

export type PlanRangeResult = { ok: true; range: PlanRange } | { ok: false; reason: string };

const UNRESOLVED_REASON =
  "This floor's elevation could not be located in the prepared 3D model.";

/**
 * The clipped range for one selected band (task28 §3.1, §3.2).
 *
 *   base  = highest resolved scene elevation in the selected band
 *   cut   = base + 1.2 m, pulled below the next band up when one exists
 *   lower = midway between the band below's highest surface and this band's
 *           lowest surface, or the model's finite geometric minimum for the
 *           lowest band
 *
 * `bands` must be in ascending band order. `modelMinSceneY` is the loaded
 * model's own geometric minimum (`model.box.min.y`) — used ONLY as the lowest
 * band's lower boundary, never as a floor elevation.
 *
 * Returns a bounded reason instead of a guessed plane whenever the numbers do
 * not support a truthful view: the caller keeps that floor's button visible but
 * disabled.
 */
export function resolvePlanRange(
  bands: SceneBand[],
  bandIndex: number,
  modelMinSceneY: number,
): PlanRangeResult {
  const selected = bands.find((b) => b.bandIndex === bandIndex);
  if (!selected) return { ok: false, reason: "That floor is not part of this model." };
  if (!selected.resolved) return { ok: false, reason: UNRESOLVED_REASON };
  const base = selected.maxSceneY;
  if (!Number.isFinite(base) || !Number.isFinite(selected.minSceneY)) {
    return { ok: false, reason: UNRESOLVED_REASON };
  }

  const position = bands.indexOf(selected);
  const above = bands[position + 1];
  const below = bands[position - 1];

  // ---- upper cut (task28 §3.1) -------------------------------------------
  let cut = base + PLAN.cutOffsetM;
  let constrainedByNextBand = false;
  // An unresolved band above cannot constrain anything, and the uppermost floor
  // uses the nominal cut rather than inventing a nonexistent next level.
  if (above?.resolved && Number.isFinite(above.minSceneY)) {
    const ceiling = above.minSceneY - planeTolerance(above.minSceneY, base);
    if (ceiling < cut) {
      cut = ceiling;
      constrainedByNextBand = true;
    }
  }
  if (!Number.isFinite(cut) || cut <= base) {
    return {
      ok: false,
      reason: "There is no room above this floor for a plan cut in this model.",
    };
  }

  // ---- lower boundary (task28 §3.2) --------------------------------------
  let lower: number;
  if (below?.resolved && Number.isFinite(below.maxSceneY)) {
    lower = (below.maxSceneY + selected.minSceneY) / 2;
  } else if (Number.isFinite(modelMinSceneY)) {
    lower = modelMinSceneY;
  } else {
    return { ok: false, reason: UNRESOLVED_REASON };
  }
  if (!Number.isFinite(lower) || lower >= cut) {
    return {
      ok: false,
      reason: "This floor's plan range could not be established in this model.",
    };
  }

  return { ok: true, range: { cut, lower, constrainedByNextBand } };
}

/** Whether a band can produce a plan at all, with the reason when it cannot. */
export function planAvailability(
  bands: SceneBand[],
  bandIndex: number,
  modelMinSceneY: number,
): { enabled: boolean; reason: string | null } {
  const result = resolvePlanRange(bands, bandIndex, modelMinSceneY);
  return result.ok ? { enabled: true, reason: null } : { enabled: false, reason: result.reason };
}
