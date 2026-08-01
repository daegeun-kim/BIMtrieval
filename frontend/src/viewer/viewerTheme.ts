// Derived viewer theme (tasks/task14.md §1; rehomed by tasks/task31.md §1).
//
// The EDITABLE values — colors, opacity, line appearance, the Fine/Standard/Fast
// visualization matrix, navigation/framing — now live in `./viewerCustomization`,
// which is constants only. This module keeps what that file must not contain:
// derived Three.js/Fragments materials, the IFC class -> color-role mapping, the
// lens math, and the operational plan-section constants (render order, clipping
// tolerance, coplanar inset) that are implementation details rather than UI
// customization.
//
// There is no duplicate numeric or color literal here: every design value below
// is imported from `viewerCustomization` and re-exported unchanged, so existing
// importers keep one source of truth.
import * as FRAGS from "@thatopen/fragments";
import * as THREE from "three";

import {
  EDGES,
  PLAN_GRAPHICS,
  VIEWER_COLORS,
  VIEWER_NAVIGATION,
  VIEWER_OPACITY,
} from "./viewerCustomization";

// Re-exported so existing call sites keep importing the theme, while the values
// themselves have exactly one definition (task31 §1).
export { EDGES, VIEWER_COLORS, VIEWER_OPACITY };

/** Delay after camera rest before base-model edges reappear (task18 §5).
 *  Timing, not appearance — deliberately not a customization value. */
export const EDGE_RESTORE_DELAY_MS = 150;

/**
 * Camera / framing constants (task14 §2).
 *
 * The user-facing lens and framing values come from `VIEWER_NAVIGATION`; only
 * the degenerate-viewport guard below is an internal safety value.
 */
export const VIEWER_CAMERA = {
  ...VIEWER_NAVIGATION,
  /**
   * Floor on the effective (unobstructed) viewport width, as a fraction of
   * the full canvas width (task19 §2). Guards the camera-view-offset centering
   * math against a degenerate near-zero or negative visible region — e.g. a
   * very narrow window with both panels open — rather than letting the fit
   * distance blow up toward infinity. A safety bound, not a design choice.
   */
  minEffectiveWidthFraction: 0.35,
} as const;

/**
 * Floor-plan mode (task28 §3, §4.2). A mode of the existing viewer: the plan is
 * a live clipped rendering of the same Fragments model, never a raster or a
 * separately generated drawing.
 *
 * `cutOffsetM` is the one directly user-visible value here and is owned by
 * `viewerCustomization`; everything else is render-order and floating-point
 * safety.
 */
export const PLAN = {
  cutOffsetM: PLAN_GRAPHICS.cutOffsetM,
  /**
   * Float32 ULPs of separation between the upper cut and the next band's lowest
   * surface, so two clipping planes can never coincide. Scaled by the model's
   * own magnitudes in `planeTolerance` — never a per-file tuned value.
   */
  toleranceUlps: 8,
  /**
   * Draw order of the plan-only cut layers. All sit above the base edge chunks
   * (1) and the highlight edge overlay (2). The black wall cut (task31 §5.1)
   * sits above the base cut, and query-primary cut geometry is drawn LAST so a
   * highlighted cut stays legible over both (task28 §4.2).
   */
  baseFillRenderOrder: 3,
  baseContourRenderOrder: 4,
  wallFillRenderOrder: 5,
  wallContourRenderOrder: 6,
  primaryFillRenderOrder: 7,
  primaryContourRenderOrder: 8,
  /**
   * Presentation-only downward nudge, in scene metres, of the cut overlay off
   * the clipping plane that produced it. Section geometry is exactly coplanar
   * with that plane, where the GPU's clip test is a floating-point coin flip and
   * would stipple the contour away. Two millimetres is invisible at any plan
   * zoom, is comfortably above Float32 noise at building-scale coordinates, and
   * is a single global constant — not a per-model or per-file adjustment. The
   * separate `toleranceUlps` above governs clipping-plane SEPARATION.
   */
  cutInsetM: 0.002,
} as const;

/** Isolated component preview (task14 §5; height doubled by task15 §4).
 *  Its profile-driven budget is deliberately left alone by task31 §2.4. */
export const PREVIEW = {
  background: null as THREE.Color | null, // transparent — the panel shows through
  autoRotateSpeed: 0.6,
  /** ms of stillness after interaction before auto-rotation resumes. */
  resumeIdleMs: 2000,
  fitExpand: 1.35,
  /** Preview viewport height; the canvas uses min(this, 36vh) to stay
   * responsive on short application viewports. */
  viewportHeightPx: 320,
  /** Finite auto-rotation lifetime (task18 §10) — replaces indefinite pause/resume. */
  autoRotateLifetimeMs: 12000,
  /** Auto-rotation frame-rate cap by profile (task18 §10). */
  autoRotateFpsCap: {
    balanced: 30,
    largeModel: 20,
  },
  /** Preview renderer pixel ratio by motion state (task18 §10). */
  pixelRatio: {
    moving: 1.0,
    stationary: 1.25,
  },
} as const;

// ===========================================================================
// Class mapping (task14 §1)
// ===========================================================================

/**
 * Wall includes every IfcWall subtype represented in the artifact. This mirrors
 * the backend's class expansion (spec_v003 §19.2): the live model holds 648
 * `IfcWall` + 232 `IfcWallStandardCase`, so omitting the subtype would leave a
 * quarter of the walls colored as "other".
 *
 * The same set is the viewer's single wall-class definition for the black
 * floor-plan wall cut (task31 §5.1) — exposed through `isWallClass` so the plan
 * layer cannot drift into a second, private list.
 */
const WALL_CLASSES = new Set(["ifcwall", "ifcwallstandardcase", "ifcwallelementedcase"]);

const ROOF_CLASSES = new Set(["ifcroof"]);

/** An IfcSlab counts as roof ONLY when its explicit predefined type says so. */
const SLAB_CLASS = "ifcslab";
const ROOF_PREDEFINED_TYPE = "roof";

export type GeometryRole = "roof" | "wall" | "other";

/** The viewer's one wall-class test (`IfcWall`, `IfcWallStandardCase`,
 *  `IfcWallElementedCase`). */
export function isWallClass(ifcClass: string): boolean {
  return WALL_CLASSES.has((ifcClass ?? "").trim().toLowerCase());
}

/**
 * Map an IFC class (+ its explicit predefined type) to a base color role.
 *
 * Never guesses: an `IfcSlab` becomes roof only on an explicit `ROOF` predefined
 * type, and anything unrecognized falls back to `other`.
 */
export function geometryRole(ifcClass: string, predefinedType?: string | null): GeometryRole {
  const cls = (ifcClass ?? "").trim().toLowerCase();
  if (ROOF_CLASSES.has(cls)) return "roof";
  if (cls === SLAB_CLASS && (predefinedType ?? "").trim().toLowerCase() === ROOF_PREDEFINED_TYPE) {
    return "roof";
  }
  if (WALL_CLASSES.has(cls)) return "wall";
  return "other";
}

// ===========================================================================
// Derived Fragments materials — do not edit; change viewerCustomization instead
// ===========================================================================

function material(color: string, opacity: number): FRAGS.MaterialDefinition {
  return {
    color: new THREE.Color(color),
    opacity,
    transparent: opacity < 1,
    renderedFaces: 0 as FRAGS.RenderedFaces,
  };
}

/** Semantic base materials, restored whenever query highlighting is cleared. */
export const BASE_MATERIALS: Record<GeometryRole, FRAGS.MaterialDefinition> = {
  roof: material(VIEWER_COLORS.roof, VIEWER_OPACITY.roof),
  wall: material(VIEWER_COLORS.wall, VIEWER_OPACITY.wall),
  other: material(VIEWER_COLORS.other, VIEWER_OPACITY.other),
};

export const PRIMARY_MATERIAL = material(VIEWER_COLORS.primary, VIEWER_OPACITY.primary);
export const PRIMARY_UNFOCUSED_MATERIAL = material(
  VIEWER_COLORS.primaryUnfocused,
  VIEWER_OPACITY.primaryUnfocused,
);
export const CONTEXT_MATERIAL = material(VIEWER_COLORS.context, VIEWER_OPACITY.context);
export const MANUAL_MATERIAL = material(VIEWER_COLORS.manual, VIEWER_OPACITY.manual);
export const DIM_MATERIAL = material(VIEWER_COLORS.dim, VIEWER_OPACITY.dim);

export const SCENE_BACKGROUND = new THREE.Color(VIEWER_COLORS.background);
export const PLANE_COLOR = new THREE.Color(VIEWER_COLORS.plane);
export const PLANE_OPACITY = VIEWER_OPACITY.plane;

export const PLAN_CUT_COLOR = new THREE.Color(VIEWER_COLORS.planCut);
export const PLAN_CUT_OPACITY = VIEWER_OPACITY.planCut;
export const PLAN_FILL_COLOR = new THREE.Color(VIEWER_COLORS.planFill);
export const PLAN_FILL_OPACITY = VIEWER_OPACITY.planFill;

/** Black wall cut fill/contour in floor-plan mode (task31 §5.1). Both layers
 *  use the SAME color; only their alpha differs, matching the non-wall pair. */
export const PLAN_WALL_CUT_COLOR = new THREE.Color(VIEWER_COLORS.planWallCut);

/** Field of view for the configured lens at a given aspect ratio (task14 §2). */
export function verticalFovDeg(aspect: number): number {
  // three.js applies filmGauge to the *wider* dimension; derive the effective
  // vertical film height for the current aspect the same way, rather than
  // hard-coding an arbitrary narrow FOV.
  const { focalLengthMm, filmGaugeMm, filmHeightMm } = VIEWER_CAMERA;
  const filmH = aspect > 1 ? filmGaugeMm / aspect : filmHeightMm;
  return 2 * THREE.MathUtils.radToDeg(Math.atan(filmH / 2 / focalLengthMm));
}
