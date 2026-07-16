// Centralized viewer theme (tasks/task14.md §1). THE single place to edit any
// viewer material, color, or opacity. No roof/wall/default/highlight color may
// live in an adapter or a React component.
//
// Design language: "measured drawing" (spec_v006 §7). The organizing rule here
// is deliberate and load-bearing:
//
//     Base model geometry is ACHROMATIC. Every semantic role is CHROMATIC.
//
// Roof/wall/other are pure cool grays; primary/context/manual are saturated
// blueprint blue / ochre / teal. So "is this object a query result?" is answered
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
  /** Relationship/context match: distinct but muted — ochre. */
  context: "#e8a94f",
  /** Manual selection: distinct from both query roles — teal. */
  manual: "#0fb5c9",

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
  /** Slightly translucent so context reads as secondary to primary. */
  context: 0.92,
  manual: 1,
  /** Highly transparent: non-results recede but keep spatial context. */
  dim: 0.16,
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
  /** Feature-edge angle threshold in degrees (THREE.EdgesGeometry). */
  thresholdAngleDeg: 25,
  /** Edge alpha per role. Where the face is transparent, the edge is more opaque. */
  alpha: {
    roof: 0.9,
    wall: 0.9,
    other: 0.85,
    primary: 1,
    primaryUnfocused: 0.75, // face 0.45
    context: 1, //             face 0.92
    manual: 1,
    dim: 0.4, //               face 0.16
  },
} as const;

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
