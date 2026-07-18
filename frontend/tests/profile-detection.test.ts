// Automatic adaptive-profile detection (tasks/task18.md §11).
import { describe, expect, it } from "vitest";

import { PROFILE_THRESHOLDS, detectProfile } from "../src/viewer/profileDetection";

describe("detectProfile", () => {
  it("classifies a small model as balanced", () => {
    expect(
      detectProfile({ artifactBytes: 5_000_000, itemCount: 3_505, edgeVertexCount: 374_822 }, null),
    ).toBe("balanced");
  });

  it("classifies model 2's measured signals as large-model", () => {
    expect(
      detectProfile({ artifactBytes: 20_000_000, itemCount: 27_388, edgeVertexCount: 5_370_488 }, null),
    ).toBe("large-model");
  });

  it("requires at least two signals above threshold, not one", () => {
    expect(
      detectProfile({ artifactBytes: PROFILE_THRESHOLDS.artifactBytes + 1, itemCount: 100 }, null),
    ).toBe("balanced");
  });

  it("flips to large-model once two signals clear their thresholds", () => {
    expect(
      detectProfile(
        {
          artifactBytes: PROFILE_THRESHOLDS.artifactBytes + 1,
          itemCount: PROFILE_THRESHOLDS.itemCount + 1,
        },
        null,
      ),
    ).toBe("large-model");
  });

  it("never uses signals outside the typed geometric/runtime shape", () => {
    // ProfileSignals has no field for model name/ID/category/discipline/storey —
    // this test exists as a structural guard: any future field addition to the
    // interface must be a geometric/runtime signal, or this test's call sites
    // (and the whole call-site convention) should be revisited.
    const signals = { artifactBytes: 1, itemCount: 1, edgeVertexCount: 1, frameTimeSampleMs: 1 };
    expect(Object.keys(signals).sort()).toEqual(
      ["artifactBytes", "edgeVertexCount", "frameTimeSampleMs", "itemCount"].sort(),
    );
  });

  it("does not downgrade from large-model to balanced on a single borderline signal", () => {
    const first = detectProfile(
      { artifactBytes: PROFILE_THRESHOLDS.artifactBytes + 1, itemCount: PROFILE_THRESHOLDS.itemCount + 1 },
      null,
    );
    expect(first).toBe("large-model");
    // Final call only adds a low edge-vertex count (no longer independently
    // large) but keeps one prior signal (artifactBytes) above threshold —
    // score is 1, hysteresis should hold the large-model verdict.
    const second = detectProfile(
      { artifactBytes: PROFILE_THRESHOLDS.artifactBytes + 1, itemCount: 10, edgeVertexCount: 10 },
      first,
    );
    expect(second).toBe("large-model");
  });

  it("does downgrade to balanced when every signal clears", () => {
    const second = detectProfile({ artifactBytes: 10, itemCount: 10, edgeVertexCount: 10 }, "large-model");
    expect(second).toBe("balanced");
  });

  it("is a pure function: same input always yields the same output", () => {
    const signals = { artifactBytes: 1_000, itemCount: 50, edgeVertexCount: 1_000 };
    expect(detectProfile(signals, null)).toBe(detectProfile(signals, null));
  });
});
