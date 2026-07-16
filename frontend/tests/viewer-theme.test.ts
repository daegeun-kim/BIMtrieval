// Centralized viewer theme + semantic class mapping (tasks/task14.md §1, §8).
import * as THREE from "three";
import { describe, expect, it } from "vitest";

import {
  BASE_MATERIALS,
  CONTEXT_MATERIAL,
  DIM_MATERIAL,
  MANUAL_MATERIAL,
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

  it("keeps base geometry achromatic and every query role chromatic", () => {
    // This is the accessibility contract: role membership reads as presence of
    // color, not as one hue vs another.
    for (const gray of [VIEWER_COLORS.roof, VIEWER_COLORS.wall, VIEWER_COLORS.other]) {
      expect(chroma(gray)).toBeLessThan(0.15);
    }
    for (const role of [VIEWER_COLORS.primary, VIEWER_COLORS.context, VIEWER_COLORS.manual]) {
      expect(chroma(role)).toBeGreaterThan(0.45);
    }
  });

  it("keeps the three highlight roles distinct from each other", () => {
    const hues = [VIEWER_COLORS.primary, VIEWER_COLORS.context, VIEWER_COLORS.manual].map((c) => {
      const hsl = { h: 0, s: 0, l: 0 };
      new THREE.Color(c).getHSL(hsl);
      return hsl.h;
    });
    expect(new Set(hues).size).toBe(3);
  });

  it("dims non-results to a highly transparent gray", () => {
    expect(VIEWER_OPACITY.dim).toBeLessThan(0.25);
    expect(DIM_MATERIAL.transparent).toBe(true);
    expect(chroma(VIEWER_COLORS.dim)).toBeLessThan(0.15);
  });

  it("keeps the base plane quiet enough not to obscure underground geometry", () => {
    expect(VIEWER_OPACITY.plane).toBeLessThanOrEqual(0.35);
  });

  it("builds opaque primary/manual and a muted translucent context material", () => {
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
