// Centralized viewer theme + semantic class mapping (tasks/task14.md §1, §8).
import * as THREE from "three";
import { describe, expect, it } from "vitest";

import {
  BASE_MATERIALS,
  CONTEXT_MATERIAL,
  DIM_MATERIAL,
  EDGES,
  MANUAL_MATERIAL,
  PLAN,
  PRIMARY_MATERIAL,
  VIEWER_CAMERA,
  VIEWER_COLORS,
  VIEWER_OPACITY,
  geometryRole,
  verticalFovDeg,
} from "../src/viewer/viewerTheme";

// Relative luminance-ish lightness proxy, good enough to assert an ordering.
function lightness(hex: string): number {
  const c = new THREE.Color(hex);
  return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
}

/**
 * Absolute sRGB chroma (max channel - min channel), 0..1.
 *
 * Parsed straight from the hex the theme declares, for two reasons:
 *
 * - NOT HSL saturation: HSL inflates saturation for near-white colors, so
 *   `#dce2e8` — a 12/255 channel spread that is plainly gray — reports S=0.21.
 * - NOT `THREE.Color`'s channels: three.js converts sRGB to linear-sRGB on
 *   construction, which stretches the mid-grays' spread. The design values are
 *   authored and shipped as sRGB, so that is what we measure.
 */
function chroma(hex: string): number {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  if (!m) throw new Error(`not a 6-digit hex color: ${hex}`);
  const [r, g, b] = m.slice(1).map((h) => parseInt(h, 16) / 255);
  return Math.max(r!, g!, b!) - Math.min(r!, g!, b!);
}

describe("class -> base color mapping", () => {
  it("maps every wall subtype in the artifact to the wall role", () => {
    expect(geometryRole("IfcWall")).toBe("wall");
    expect(geometryRole("IfcWallStandardCase")).toBe("wall");
    expect(geometryRole("ifcwallstandardcase")).toBe("wall");
  });

  it("maps IfcRoof to the roof role", () => {
    expect(geometryRole("IfcRoof")).toBe("roof");
  });

  it("treats a slab as roof ONLY with an explicit ROOF predefined type", () => {
    expect(geometryRole("IfcSlab", "ROOF")).toBe("roof");
    expect(geometryRole("IfcSlab", "roof")).toBe("roof");
    expect(geometryRole("IfcSlab", "FLOOR")).toBe("other");
    expect(geometryRole("IfcSlab", null)).toBe("other");
    expect(geometryRole("IfcSlab")).toBe("other");
  });

  it("falls back to the very-light-gray default for everything else", () => {
    expect(geometryRole("IfcDoor")).toBe("other");
    expect(geometryRole("IfcWindow")).toBe("other");
    expect(geometryRole("IfcCurtainWall")).toBe("other");
    expect(geometryRole("")).toBe("other");
  });
});

describe("semantic color roles", () => {
  it("orders base geometry roof < wall < other by lightness", () => {
    expect(lightness(VIEWER_COLORS.roof)).toBeLessThan(lightness(VIEWER_COLORS.wall));
    expect(lightness(VIEWER_COLORS.wall)).toBeLessThan(lightness(VIEWER_COLORS.other));
  });

  it("keeps 'other' geometry distinguishable from the sheet background", () => {
    const delta = Math.abs(lightness(VIEWER_COLORS.other) - lightness(VIEWER_COLORS.background));
    expect(delta).toBeGreaterThan(0.01);
  });

  it("uses only blue for matches/selections and gray for context/base geometry", () => {
    // This is the accessibility contract: role membership reads as presence of
    // color, not as one hue vs another.
    for (const gray of [VIEWER_COLORS.roof, VIEWER_COLORS.wall, VIEWER_COLORS.other]) {
      expect(chroma(gray)).toBeLessThan(0.15);
    }
    for (const role of [VIEWER_COLORS.primary, VIEWER_COLORS.manual]) {
      expect(chroma(role)).toBeGreaterThan(0.45);
    }
    expect(chroma(VIEWER_COLORS.context)).toBeLessThan(0.15);
    expect(VIEWER_COLORS.manual).toBe(VIEWER_COLORS.primary);
    expect(VIEWER_COLORS.context).toBe(VIEWER_COLORS.dim);
  });

  it("dims non-results to the accepted transparency (task31 §3)", () => {
    // Task 31 §3 lowered the task18 §9 value from 0.35 to 0.20, and the
    // relationship-context face from 0.16 to 0.10, so interior matches read
    // more clearly through the surrounding building. Still translucent, never
    // opaque: an opaque non-result occluded every interior query-primary result
    // when that was benchmarked (task18 §9 candidate 2).
    expect(VIEWER_OPACITY.dim).toBe(0.2);
    expect(VIEWER_OPACITY.context).toBe(0.1);
    expect(DIM_MATERIAL.transparent).toBe(true);
    expect(chroma(VIEWER_COLORS.dim)).toBeLessThan(0.15);
    expect(EDGES.alpha.dim).toBe(0); // non-result edges disabled, task18 §9
  });

  it("removes only the translucent unfocused-primary 3D entity edge (task31 §3)", () => {
    // The blue face survives at the established face opacity; only its edge
    // overlay is gone.
    expect(EDGES.alpha.primaryUnfocused).toBe(0);
    expect(VIEWER_OPACITY.primaryUnfocused).toBeGreaterThan(0);
    // Opaque focused-primary and manual-selection blue edges are untouched.
    expect(EDGES.alpha.primary).toBe(1);
    expect(EDGES.alpha.manual).toBe(1);
    // Base grey geometry keeps its edges.
    for (const role of ["roof", "wall", "other"] as const) {
      expect(EDGES.alpha[role]).toBeGreaterThan(0);
    }
  });

  it("keeps the base plane quiet enough not to obscure underground geometry", () => {
    expect(VIEWER_OPACITY.plane).toBeLessThanOrEqual(0.35);
  });

  it("builds opaque blue primary/manual and gray translucent context material", () => {
    expect(PRIMARY_MATERIAL.transparent).toBe(false);
    expect(MANUAL_MATERIAL.transparent).toBe(false);
    expect(CONTEXT_MATERIAL.opacity).toBeLessThan(1);
  });

  it("exposes a material for every base role", () => {
    expect(Object.keys(BASE_MATERIALS).sort()).toEqual(["other", "roof", "wall"]);
  });
});

describe("50 mm full-frame camera math", () => {
  it("derives the FOV from focal length and film gauge, not a hard-coded number", () => {
    // A 50 mm lens on 36x24 mm full frame is ~26.99 deg vertical at 3:2.
    const fov = verticalFovDeg(1.5);
    expect(fov).toBeGreaterThan(26);
    expect(fov).toBeLessThan(28);
  });

  it("narrows the vertical FOV as the viewport gets wider", () => {
    expect(verticalFovDeg(2.4)).toBeLessThan(verticalFovDeg(1.5));
  });

  it("uses the full 24 mm film height for portrait/square aspects", () => {
    // 2*atan(12/50) ~= 26.99 deg
    expect(verticalFovDeg(1)).toBeCloseTo(26.99, 1);
    expect(verticalFovDeg(0.8)).toBeCloseTo(26.99, 1);
  });

  it("declares the documented 50 mm / 36x24 mm configuration", () => {
    expect(VIEWER_CAMERA.focalLengthMm).toBe(50);
    expect(VIEWER_CAMERA.filmGaugeMm).toBe(36);
    expect(VIEWER_CAMERA.filmHeightMm).toBe(24);
  });

  it("bounds zoom-out at ~3x the model diagonal", () => {
    expect(VIEWER_CAMERA.maxDistanceDiagonalFactor).toBe(3);
    expect(VIEWER_CAMERA.minMaxDistance).toBeGreaterThan(0);
  });
});

describe("floor-plan cut hierarchy (task28 §4.2)", () => {
  it("makes the cut contour the darkest ink in the viewer", () => {
    const cut = lightness(VIEWER_COLORS.planCut);
    for (const role of ["roof", "wall", "other", "dim", "context", "plane"] as const) {
      expect(cut).toBeLessThan(lightness(VIEWER_COLORS[role]));
    }
    // Darker than any base edge, which is a base colour multiplied by `darken`.
    expect(cut).toBeLessThan(lightness(VIEWER_COLORS.roof) * EDGES.darken);
  });

  it("keeps the cut fill restrained relative to its own contour", () => {
    expect(lightness(VIEWER_COLORS.planFill)).toBeGreaterThan(lightness(VIEWER_COLORS.planCut));
    expect(VIEWER_OPACITY.planCut).toBe(1);
    expect(VIEWER_OPACITY.planFill).toBeLessThan(1);
    expect(VIEWER_OPACITY.planFill).toBeGreaterThan(0);
  });

  it("draws every cut layer above the base and highlight edge overlays", () => {
    // Base edge chunks render at 1 and the highlight overlay at 2 (task20 §2).
    for (const order of [
      PLAN.baseFillRenderOrder,
      PLAN.baseContourRenderOrder,
      PLAN.primaryFillRenderOrder,
      PLAN.primaryContourRenderOrder,
    ]) {
      expect(order).toBeGreaterThan(2);
    }
    // A contour always outranks the fill it outlines, and query-primary cut
    // geometry outranks the base cut it sits on.
    expect(PLAN.baseContourRenderOrder).toBeGreaterThan(PLAN.baseFillRenderOrder);
    expect(PLAN.primaryContourRenderOrder).toBeGreaterThan(PLAN.primaryFillRenderOrder);
    expect(PLAN.primaryFillRenderOrder).toBeGreaterThan(PLAN.baseContourRenderOrder);
  });

  it("declares the nominal 1.2 m cut and a scale-free plane tolerance", () => {
    expect(PLAN.cutOffsetM).toBe(1.2);
    expect(PLAN.toleranceUlps).toBeGreaterThan(0);
    // The coplanar-render inset is imperceptible at any plan zoom.
    expect(PLAN.cutInsetM).toBeGreaterThan(0);
    expect(PLAN.cutInsetM).toBeLessThan(0.01);
  });

  it("reuses the existing semantic roles rather than inventing plan colours", () => {
    // Query-primary cut geometry uses the established blueprint blue, and
    // manual selection keeps its own existing colour (task28 §5).
    expect(PRIMARY_MATERIAL.color).toEqual(new THREE.Color(VIEWER_COLORS.primary));
    expect(MANUAL_MATERIAL.color).toEqual(new THREE.Color(VIEWER_COLORS.manual));
  });
});
