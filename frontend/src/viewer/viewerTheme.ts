// Centralized viewer theme (tasks/task14.md §1). THE single place to edit any
// viewer material, color, or opacity. No roof/wall/default/highlight color may
// live in an adapter or a React component.
//
// Design language: "measured drawing" (spec_v006 §7). The organizing rule here
// is deliberate and load-bearing:
//
//     Base model geometry and context are gray. Matches and manual picks are blue.
//
// Roof/wall/other/context are cool grays; primary/manual use blueprint blue. So
// "is this object a query result?" is answered
// by the *presence of color*, not by discriminating one hue from another — which
// stays legible under any color-vision deficiency and over the varied grey/beige
// materials typical of BIM models. The gray ladder (roof L*~49, wall L*~79,
// other L*~88) then separates the base classes from each other and from the
// sheet background (L*~93) on lightness alone.
//
// Roof reads darkest because that is the poché convention of the drawing this
// interface imitates: cut/capping material is filled dark, everything beyond it
// is lighter.
import * as FRAGS from "@thatopen/fragments";
import * as THREE from "three";

// ===========================================================================
// EDITABLE VALUES — everything a designer would touch is in this block
// ===========================================================================

export const VIEWER_COLORS = {
  /** Roof geometry: dark gray. */
  roof: "#67737f",
  /** Wall geometry (incl. IfcWallStandardCase): light gray. */
  wall: "#bcc6d0",
  /** All other model geometry: very light gray. */
  other: "#dce2e8",

  /** Primary query match: strong, distinct — blueprint blue. */
  primary: "#1f6feb",
  /**
   * Unfocused primary results while one or more results are manually focused
   * (task15 §3): the same blueprint blue, lowered opacity — never teal.
   */
  primaryUnfocused: "#1f6feb",
  /** Context is intentionally uncolored and recedes with non-results. */
  context: "#c7ced6",
  /** Manual selection uses the same blue as a query match. */
  manual: "#1f6feb",

  /** Non-result geometry while query highlighting is active. */
  dim: "#c7ced6",

  /** Base plane / grid: quiet neutral. */
  plane: "#c4cdd6",
  /** Scene background — the "sheet". */
  background: "#e9edf1",
} as const;

export const VIEWER_OPACITY = {
  roof: 1,
  wall: 1,
  other: 1,
  primary: 1,
  /** Unfocused primaries recede while a result is focused, but stay clearly blue. */
  primaryUnfocused: 0.45,
  /** Context is not a colored result. */
  context: 0.16,
  manual: 1,
  /**
   * Query-highlight transparency (task18 §9). Benchmarked on model 2 against
   * 3 candidates: (1) the original 0.16 + motion-hidden edges; (2) fully
   * opaque (1.0) light-neutral with edges disabled; (3) moderate 0.3-0.4 with
   * edges disabled. Candidate 2 was REJECTED after live testing: opaque
   * non-result geometry occluded every sampled interior/hidden query-primary
   * result from every external camera angle, violating "primary and manual
   * selections must remain clearly blue and legible" — a real risk for a
   * query tool where results are frequently interior elements (partition
   * walls, MEP, doors), not just exterior-visible surfaces. Candidate 3 (this
   * value) was selected: it keeps every primary visible through the
   * translucency (same guarantee as the original), while disabling non-result
   * edges (`EDGES.alpha.dim` below) measurably reduces visual line density
   * versus the original 0.16 treatment.
   */
  dim: 0.35,
  /** Light enough never to obscure underground geometry. */
  plane: 0.3,
} as const;

/**
 * Entity edge overlay (task15 §2) — one merged LineSegments over all entities.
 *
 * Edges follow the entity's CURRENT face color (base role or highlight role),
 * multiplied by `darken` so a same-color edge stays visible on its own face.
 * For transparent faces the edge alpha is deliberately HIGHER than the face
 * opacity, so dimmed/unfocused entities keep a legible outline.
 */
export const EDGES = {
  enabled: true,
  /** Multiplier applied to the current face color (1 = identical color). */
  darken: 0.72,
  /**
   * Feature-edge angle threshold in degrees (THREE.EdgesGeometry), profile-
   * adaptive (task18 §6). A higher threshold keeps fewer, stricter edges —
   * chosen once per model load from the provisional profile (bytes + item
   * count, before the edge build starts) so a genuinely large model builds
   * its overlay at the coarser angle from the first pass, not a second one.
   */
  thresholdAngleDeg: {
    balanced: 25,
    largeModel: 40,
  },
  /** Edge alpha per role. Where the face is transparent, the edge is more opaque. */
  alpha: {
    roof: 0.9,
    wall: 0.9,
    other: 0.85,
    primary: 1,
    primaryUnfocused: 0.75, // face 0.45
    context: 0.4, //           face 0.16
    manual: 1,
    dim: 0, //                 face 0.35 (candidate 3, task18 §9) — context edges disabled
    /**
     * Object hidden by the projected-size policy (task23 issue 2). Its faces are
     * not rendered, so its custom edges must not be either — otherwise a hidden
     * object leaves a floating wireframe. Eligibility/visibility only: nothing
     * about the object's class mapping, color, or semantic role changes.
     */
    hidden: 0,
  },
  /**
   * Projected screen-size hysteresis for base-model edge chunk culling
   * (task18 §8). Below `farEnterPx` a chunk stops rendering custom edges;
   * it must grow past `farExitPx` before edges return, so borderline chunks
   * don't flicker. Selected/query-primary chunks use a stricter, closer pair
   * so they stay legible farther from the camera than base context.
   */
  lod: {
    farEnterPx: 2,
    farExitPx: 4,
    highlightFarEnterPx: 0.75,
    highlightFarExitPx: 1.5,
  },
} as const;

/** Delay after camera rest before base-model edges reappear (task18 §5). */
export const EDGE_RESTORE_DELAY_MS = 150;

/** Camera / framing constants (task14 §2). */
export const VIEWER_CAMERA = {
  /** 50 mm lens on a 36x24 mm full-frame camera. */
  focalLengthMm: 50,
  filmGaugeMm: 36,
  filmHeightMm: 24,
  /** Maximum camera-target distance as a multiple of the model bbox diagonal. */
  maxDistanceDiagonalFactor: 3,
  /** Floor for tiny/test models so the bound is never uselessly small (metres). */
  minMaxDistance: 25,
  /** Fit framing: grow the target box so surroundings stay visible. */
  fitExpand: 1.9,
  /** Metres — floor so a small element never fills the viewport. */
  minFitSize: 2.5,
  /** px of pointer travel that separates a click-select from a left-drag pan. */
  clickMoveTolerance: 4,
  /**
   * Floor on the effective (unobstructed) viewport width, as a fraction of
   * the full canvas width (task19 §2). Guards the camera-view-offset centering
   * math against a degenerate near-zero or negative visible region — e.g. a
   * very narrow window with both panels open — rather than letting the fit
   * distance blow up toward infinity.
   */
  minEffectiveWidthFraction: 0.35,
} as const;

/** Isolated component preview (task14 §5; height doubled by task15 §4). */
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
 */
const WALL_CLASSES = new Set(["ifcwall", "ifcwallstandardcase", "ifcwallelementedcase"]);

const ROOF_CLASSES = new Set(["ifcroof"]);

/** An IfcSlab counts as roof ONLY when its explicit predefined type says so. */
const SLAB_CLASS = "ifcslab";
const ROOF_PREDEFINED_TYPE = "roof";

export type GeometryRole = "roof" | "wall" | "other";

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
// Derived Fragments materials — do not edit; change the blocks above instead
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

/** Field of view for the configured lens at a given aspect ratio (task14 §2). */
export function verticalFovDeg(aspect: number): number {
  // three.js applies filmGauge to the *wider* dimension; derive the effective
  // vertical film height for the current aspect the same way, rather than
  // hard-coding an arbitrary narrow FOV.
  const { focalLengthMm, filmGaugeMm, filmHeightMm } = VIEWER_CAMERA;
  const filmH = aspect > 1 ? filmGaugeMm / aspect : filmHeightMm;
  return 2 * THREE.MathUtils.radToDeg(Math.atan(filmH / 2 / focalLengthMm));
}
