// Automatic adaptive-profile detection (tasks/task18.md §11).
//
// Signals are geometric/runtime evidence ONLY — artifact byte size, model
// item count, edge vertex count, and an optional bounded initial frame-time
// sample. Never the model name, source-model ID, IFC category, discipline, or
// storey: this function's input type has no field for any of those, so a
// caller cannot accidentally feed one in.
export type Profile = "balanced" | "large-model";

export interface ProfileSignals {
  /** Downloaded artifact size in bytes (`bytes.byteLength` in loadModel). */
  artifactBytes: number;
  /** Total model item count (model.getLocalIds().length). */
  itemCount: number;
  /** Edge overlay vertex count, once known — absent before the edge build resolves. */
  edgeVertexCount?: number;
  /** Bounded initial frame-time sample in ms, averaged over a short window after fitAll(). */
  frameTimeSampleMs?: number;
}

/**
 * Default cutoffs, derived from the one real reference artifact's measured
 * numbers documented in EdgeOverlay.ts (3,505 items / ~374k edge vertices for
 * the Schependomlaan model), scaled ~1.5-1.7x so that reference model itself
 * classifies "balanced". Provisional pending a second large-model data point;
 * model 2 (27,388 items / 5.37M edge vertices, measured tasks/task18.md §1)
 * clears every one of these by a wide margin.
 */
export const PROFILE_THRESHOLDS = {
  artifactBytes: 8_000_000,
  itemCount: 6_000,
  edgeVertexCount: 300_000,
  frameTimeSampleMs: 20,
} as const;

/** Signals required to flip to "large-model" (out of up to 4 available). */
const LARGE_MODEL_SCORE = 2;

/**
 * Weighted-signal verdict with hysteresis against the previous call's result.
 * Called twice per load (task18 §11): provisionally right after the artifact
 * downloads (bytes + item count only), then finally once the edge overlay
 * build resolves (adds edge vertex count, and optionally a frame-time
 * sample) — a single controlled upgrade, not per-frame flip-flopping.
 */
export function detectProfile(signals: ProfileSignals, previous: Profile | null): Profile {
  let score = 0;
  if (signals.artifactBytes > PROFILE_THRESHOLDS.artifactBytes) score += 1;
  if (signals.itemCount > PROFILE_THRESHOLDS.itemCount) score += 1;
  if (signals.edgeVertexCount !== undefined && signals.edgeVertexCount > PROFILE_THRESHOLDS.edgeVertexCount) {
    score += 1;
  }
  if (signals.frameTimeSampleMs !== undefined && signals.frameTimeSampleMs > PROFILE_THRESHOLDS.frameTimeSampleMs) {
    score += 1;
  }

  const raw: Profile = score >= LARGE_MODEL_SCORE ? "large-model" : "balanced";
  // Once a load has been classified large-model, don't fall back to balanced
  // on a single borderline signal (e.g. the frame-time sample alone dropping
  // out when edgeVertexCount is added on the final call) — require the score
  // to clear entirely first. This guards the two-phase provisional->final
  // upgrade above, not continuous runtime re-evaluation (profile is decided
  // per model load, never per frame).
  if (previous === "large-model" && score >= 1) return "large-model";
  return raw;
}
