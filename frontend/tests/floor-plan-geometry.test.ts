// Floor-plan range derivation (tasks/task28.md §3, §8.2).
//
// Pure arithmetic over already-resolved SCENE elevations — no WebGL, no worker,
// no Fragments. The point of these cases is that the numbers are exactly the
// ones the task specifies, and that a floor which cannot be mapped safely is
// disabled rather than shown at a guessed height.
import { describe, expect, it } from "vitest";

import {
  FLOAT32_EPSILON,
  planAvailability,
  planeTolerance,
  resolvePlanRange,
  storeyLocalY,
  type SceneBand,
} from "../src/viewer/floorPlan";
import { PLAN } from "../src/viewer/viewerTheme";

function band(bandIndex: number, minSceneY: number, maxSceneY = minSceneY): SceneBand {
  return { bandIndex, label: `Floor ${bandIndex + 1}`, minSceneY, maxSceneY, resolved: true };
}

function unresolved(bandIndex: number): SceneBand {
  return {
    bandIndex,
    label: `Floor ${bandIndex + 1}`,
    minSceneY: Number.NaN,
    maxSceneY: Number.NaN,
    resolved: false,
  };
}

/** Ground + two upper floors, 3 m apart, model bottom at -0.4. */
const THREE_FLOORS = [band(0, 0), band(1, 3), band(2, 6)];
const MODEL_MIN = -0.4;

describe("scene elevation is derived, never taken from the database (task28 §3)", () => {
  it("adds the artifact's own coordinate height, mirroring Views.createFromIfcStoreys", () => {
    // A model coordinated 5 m down: the stored elevation 3 is NOT the scene Y.
    expect(storeyLocalY(3, -5)).toBe(-2);
    expect(storeyLocalY(3, 0)).toBe(3);
  });

  it("never treats a raw elevation as a scene Y when the two differ", () => {
    const rawElevation = 12.5;
    const coordinateHeight = -8;
    expect(storeyLocalY(rawElevation, coordinateHeight)).not.toBe(rawElevation);
  });
});

describe("upper cut plane (task28 §3.1)", () => {
  it("cuts 1.2 scene metres above the band's HIGHEST constituent storey", () => {
    // A band of three sub-levels: the cut is measured from the top one.
    const bands = [band(0, -0.15, 0.0), band(1, 2.92, 3.0)];
    const result = resolvePlanRange(bands, 0, MODEL_MIN);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.cut).toBeCloseTo(0.0 + PLAN.cutOffsetM, 10);
    expect(result.range.constrainedByNextBand).toBe(false);
  });

  it("uses the nominal 1.2 m cut for the uppermost floor", () => {
    const result = resolvePlanRange(THREE_FLOORS, 2, MODEL_MIN);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.cut).toBeCloseTo(7.2, 10);
    expect(result.range.constrainedByNextBand).toBe(false);
  });

  it("constrains the cut below the next band when 1.2 m would overshoot it", () => {
    // Floor 2 sits only 0.8 m above floor 1, so the nominal cut would slice it.
    const bands = [band(0, 0), band(1, 0.8), band(2, 4)];
    const result = resolvePlanRange(bands, 0, MODEL_MIN);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.constrainedByNextBand).toBe(true);
    expect(result.range.cut).toBeLessThan(0.8);
    expect(result.range.cut).toBeCloseTo(0.8 - planeTolerance(0.8, 0), 12);
  });

  it("leaves the nominal cut alone when the next band is comfortably higher", () => {
    const result = resolvePlanRange(THREE_FLOORS, 0, MODEL_MIN);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.cut).toBeCloseTo(1.2, 10);
  });

  it("is not constrained by an UNRESOLVED band above", () => {
    const bands = [band(0, 0), unresolved(1)];
    const result = resolvePlanRange(bands, 0, MODEL_MIN);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.cut).toBeCloseTo(1.2, 10);
  });

  it("disables the floor when the next band leaves no room above it", () => {
    // Two bands at the same elevation cannot both be cut.
    const bands = [band(0, 3), band(1, 3)];
    const result = resolvePlanRange(bands, 0, MODEL_MIN);
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.reason).toMatch(/no room above/i);
  });
});

describe("clipping-plane tolerance (task28 §3.1)", () => {
  it("is derived from Float32 precision at the model's own scale", () => {
    expect(planeTolerance(1)).toBeCloseTo(FLOAT32_EPSILON * PLAN.toleranceUlps, 20);
    // A model expressed at 100x the magnitude gets a 100x tolerance.
    expect(planeTolerance(100)).toBeCloseTo(planeTolerance(1) * 100, 15);
  });

  it("is strictly positive but small enough to be invisible", () => {
    const tolerance = planeTolerance(1000, 0);
    expect(tolerance).toBeGreaterThan(0);
    expect(tolerance).toBeLessThan(1e-3);
  });

  it("never collapses to zero for tiny or non-finite magnitudes", () => {
    expect(planeTolerance(0)).toBeGreaterThan(0);
    expect(planeTolerance(Number.NaN, Infinity)).toBeGreaterThan(0);
  });

  it("keeps the constrained cut strictly below the next band", () => {
    const bands = [band(0, 0), band(1, 0.5)];
    const result = resolvePlanRange(bands, 0, MODEL_MIN);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.cut).toBeLessThan(0.5);
  });
});

describe("lower range boundary (task28 §3.2)", () => {
  it("is the midpoint between the band below and the selected band", () => {
    const result = resolvePlanRange(THREE_FLOORS, 1, MODEL_MIN);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.lower).toBeCloseTo(1.5, 10); // (0 + 3) / 2
  });

  it("uses the midpoint of the ACTUAL surfaces, not the band ordinals", () => {
    const bands = [band(0, -0.2, 0.1), band(1, 2.9, 3.1)];
    const result = resolvePlanRange(bands, 1, MODEL_MIN);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.lower).toBeCloseTo((0.1 + 2.9) / 2, 10);
  });

  it("uses the model's geometric minimum for the lowest band", () => {
    const result = resolvePlanRange(THREE_FLOORS, 0, MODEL_MIN);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.lower).toBe(MODEL_MIN);
  });

  it("falls back to the geometric minimum when the band below is unresolved", () => {
    const bands = [unresolved(0), band(1, 3)];
    const result = resolvePlanRange(bands, 1, MODEL_MIN);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.lower).toBe(MODEL_MIN);
  });

  it("bounds the view so a lower floor cannot appear through the selected one", () => {
    const result = resolvePlanRange(THREE_FLOORS, 1, MODEL_MIN);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    // Floor 1's own surfaces (y = 0) sit BELOW the active range.
    expect(result.range.lower).toBeGreaterThan(0);
    expect(result.range.cut).toBeGreaterThan(result.range.lower);
  });

  it("disables the floor when neither a lower band nor a finite minimum exists", () => {
    const result = resolvePlanRange([band(0, 3)], 0, Number.NaN);
    expect(result.ok).toBe(false);
  });
});

describe("unresolved and invalid mappings disable only the affected floor (task28 §6)", () => {
  it("disables an unresolved band with a concise reason", () => {
    const bands = [band(0, 0), unresolved(1), band(2, 6)];
    const availability = bands.map((b) => planAvailability(bands, b.bandIndex, MODEL_MIN));
    expect(availability[0]!.enabled).toBe(true);
    expect(availability[1]!.enabled).toBe(false);
    expect(availability[1]!.reason).toMatch(/could not be located/i);
    expect(availability[2]!.enabled).toBe(true);
  });

  it("never places a guessed plane for a non-finite band", () => {
    const bands: SceneBand[] = [
      { bandIndex: 0, label: "Floor 1", minSceneY: 0, maxSceneY: Infinity, resolved: true },
    ];
    expect(resolvePlanRange(bands, 0, MODEL_MIN).ok).toBe(false);
  });

  it("rejects a band index the model does not have", () => {
    const result = resolvePlanRange(THREE_FLOORS, 9, MODEL_MIN);
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.reason).toMatch(/not part of this model/i);
  });
});

describe("a single logical floor still produces a plan (task28 §1.1)", () => {
  it("uses the nominal cut and the geometric minimum", () => {
    const result = resolvePlanRange([band(0, 0)], 0, -0.3);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.cut).toBeCloseTo(1.2, 10);
    expect(result.range.lower).toBe(-0.3);
  });
});

describe("scale independence", () => {
  it("works for a model coordinated far from the origin", () => {
    // Same building, scene elevations shifted by 4,000 m.
    const bands = [band(0, 4000), band(1, 4003)];
    const result = resolvePlanRange(bands, 0, 3999.6);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.cut).toBeCloseTo(4001.2, 6);
    expect(result.range.lower).toBe(3999.6);
  });

  it("works for a model whose floors sit below scene zero", () => {
    const bands = [band(0, -9), band(1, -6)];
    const result = resolvePlanRange(bands, 1, -9.4);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.range.cut).toBeCloseTo(-4.8, 10);
    expect(result.range.lower).toBeCloseTo(-7.5, 10);
  });
});
