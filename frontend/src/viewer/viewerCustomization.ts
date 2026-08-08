// THE easy-to-edit source for the viewer's user-facing appearance, quality and
// navigation values (Task 31 §1).
//
// This file is deliberately **constants only**. It contains no functions, no
// derived Three.js/Fragments materials, no class-mapping logic, no state, no
// event handling, no API behavior and no rendering algorithm. Editing a number
// or a hex string here is the whole edit — nothing else has to be touched, and
// nothing here can break at runtime.
//
// What lives here: colors, opacity, line appearance, the Fine/Standard/Fast
// visualization matrix, and navigation/framing values.
//
// What deliberately does NOT live here (operational/internal, not customization):
// batching sizes and worker timing (`EdgeOverlay`), cache limits
// (`storage/artifactCache`), API/result limits, plan render-order safety and
// the coplanar cut inset and clipping-plane ULP tolerance (`viewerTheme.PLAN`),
// stale-token guards, and the isolated preview's profile-driven fps/pixel-ratio
// budget (`viewerTheme.PREVIEW`), which Task 31 §2.4 requires leaving alone.
//
// `viewerTheme.ts` imports every value below and keeps only the DERIVED
// artifacts (Three.js/Fragments materials, `geometryRole`, `verticalFovDeg`) —
// it holds no duplicate numeric or color literal of its own.

// ===========================================================================
// 1. COLORS
// ===========================================================================
//
// Design language: "measured drawing" (spec_v006 §7). The organizing rule is
// deliberate and load-bearing:
//
//     Base model geometry and context are gray. Matches and manual picks are blue.
//
// So "is this object a query result?" is answered by the *presence of color*,
// not by discriminating one hue from another — legible under any color-vision
// deficiency and over the varied grey/beige materials typical of BIM models.
// The gray ladder (roof L*~49, wall L*~79, other L*~88) then separates the base
// classes from each other and from the sheet background (L*~93) on lightness
// alone.

export const VIEWER_COLORS = {
  // ---- base geometry ------------------------------------------------------
  /** Roof geometry: dark gray. Darkest because cut/capping material is filled
   *  dark in the drawing convention this interface imitates. */
  roof: "#67737f",
  /** Wall geometry (incl. IfcWallStandardCase): light gray. */
  wall: "#bcc6d0",
  /** All other model geometry: very light gray. */
  other: "#dce2e8",

  // ---- semantic highlights ------------------------------------------------
  /** Primary query match: strong, distinct — blueprint blue. */
  primary: "#1f6feb",
  /** Unfocused primary results while one or more results are manually focused
   *  (task15 §3): the same blueprint blue, lowered opacity — never teal. */
  primaryUnfocused: "#1f6feb",
  /** Relationship context is intentionally uncolored and recedes with non-results. */
  context: "#c7ced6",
  /** Manual selection uses the same blue as a query match. */
  manual: "#1f6feb",
  /** Non-result geometry while query highlighting is active. */
  dim: "#c7ced6",

  // ---- background / reference plane ---------------------------------------
  /** Base plane / grid: quiet neutral. */
  plane: "#c4cdd6",
  /** Scene background — the "sheet". */
  background: "#e9edf1",

  // ---- floor-plan graphics ------------------------------------------------
  /** Non-wall floor-plan cut contour (task28 §4.2): the darkest ink among the
   *  projected layers, so true cut geometry outranks every edge below it. */
  planCut: "#000000",
  /** Restrained poché fill inside a non-wall cut contour. */
  planFill: "#96a2af",
  /**
   * WALL cut fill and contour in floor-plan mode (task31 §5.1) — pure black,
   * the poché convention for cut masonry. Applies ONLY to cut geometry produced
   * at the active section plane for `IfcWall`/`IfcWallStandardCase`/
   * `IfcWallElementedCase`; normal 3D wall faces and 3D wall edges are never
   * black. A query-primary wall is excluded from this layer entirely, so blue
   * semantic graphics can never be covered or tinted by it.
   */
  planWallCut: "#000000",
} as const;

// ===========================================================================
// 2. OPACITY / TRANSPARENCY
// ===========================================================================
//
// Face alpha per role. 1 = fully opaque.

export const VIEWER_OPACITY = {
  roof: 1,
  wall: 1,
  other: 1,
  primary: 1,
  /** Unfocused primaries recede while a result is focused, but stay clearly blue. */
  primaryUnfocused: 0.45,
  /**
   * Relationship context is not a colored result, and Task 31 §3 lowered it
   * from 0.16 so a context object recedes further behind the blue matches.
   */
  context: 0.1,
  manual: 1,
  /**
   * Query-highlight transparency for NON-result geometry. Task 18 §9 selected a
   * moderate translucency with non-result edges disabled (over both the original
   * 0.16 and a fully opaque variant, which occluded every interior query-primary
   * result). Task 31 §3 lowered it again, from 0.35, so interior matches read
   * more clearly through the surrounding building.
   */
  dim: 0.2,
  /** Light enough never to obscure underground geometry. */
  plane: 0.3,
  /** Cut contour: fully opaque — it is the strongest line on the sheet. */
  planCut: 1,
  /** Cut fill: present but restrained, so highlighted cut geometry stays legible. */
  planFill: 0.55,
} as const;

// ===========================================================================
// 3. LINE APPEARANCE
// ===========================================================================
//
// INSTALLED-RENDERER LIMITATION, stated once for the whole block: the viewer
// draws every line through `THREE.LineBasicMaterial` + `THREE.LineSegments`, and
// the WebGL renderer ignores `linewidth` — the WebGL core profile only
// guarantees 1-px lines, so on every major browser these are always exactly one
// device line wide. There is therefore NO thickness constant here: exposing one
// would be a knob that silently does nothing. Making thickness real would need a
// wide-line library (Line2/LineMaterial) or a patched Three.js, which Task 31 §1
// explicitly forbids. Line *presence*, *color* and *alpha* — the values below —
// are honored exactly.

export const EDGES = {
  enabled: true,
  /** Multiplier applied to the entity's current face color (1 = identical color). */
  darken: 0.72,
  /**
   * Edge alpha per role. Where the face is transparent the edge is normally
   * MORE opaque, so a dimmed entity keeps a legible outline.
   */
  alpha: {
    roof: 0.9,
    wall: 0.9,
    other: 0.85,
    primary: 1,
    /**
     * Task 31 §3: the translucent unfocused-primary role has NO entity-edge
     * overlay (was 0.75). Its blue face stays visible at
     * `VIEWER_OPACITY.primaryUnfocused`, but removing the outline stops the
     * unfocused matches from competing as line weight with the focused ones.
     * This affects the 3D entity-edge overlay only — plan-mode blue cut
     * contours are a separate layer and are unchanged.
     */
    primaryUnfocused: 0,
    context: 0.4, //           face 0.10
    manual: 1,
    dim: 0, //                 face 0.20 — non-result edges disabled (task18 §9)
    /**
     * Object hidden by the projected-size policy (task23 issue 2). Its faces are
     * not rendered, so its edges must not be either — otherwise a hidden object
     * leaves a floating wireframe.
     */
    hidden: 0,
  },
  /**
   * Projected screen-size hysteresis for base-model edge CHUNK culling
   * (task18 §8), in CSS px. Below `farEnterPx` a chunk stops rendering edges; it
   * must grow past `farExitPx` before they return, so borderline chunks don't
   * flicker. Chunks containing a selected/query-primary entity use the stricter
   * `highlight*` pair so they stay legible farther from the camera.
   */
  lod: {
    farEnterPx: 2,
    farExitPx: 4,
    highlightFarEnterPx: 0.75,
    highlightFarExitPx: 1.5,
  },
} as const;

// ===========================================================================
// 4. VISUALIZATION MODES (Fine / Standard / Fast)
// ===========================================================================
//
// A user-selectable visualization-QUALITY choice (task31 §2). It changes ONLY
// the four threshold values below; every algorithm around them — Fragments'
// own mesh LOD and update cadence, continuous rendering, projected-size category
// eligibility and its cached bounding volumes, the always-retained architectural
// categories, highlight exemption, plan-mode suspension, chunked frustum-culled
// edges, base-model culling, picking, fit, disposal — is identical in all three.
//
// This is NOT the removed Task 18 automatic/manual performance-profile control.
// Nothing here selects a mode on the user's behalf. The separate deterministic
// balanced/large-model signal still picks WHICH edge angle of the selected mode
// applies; it never picks the mode.

export type VisualizationMode = "fine" | "standard" | "fast";

export interface VisualizationModeThresholds {
  /** Below this projected diameter (CSS px) a hide candidate enters the reduced state. */
  projectedSizeHidePx: number;
  /** It must grow past this (CSS px) before it is restored. Hysteresis: between
   *  the two values an object keeps its previous state. */
  projectedSizeRestorePx: number;
  /** `THREE.EdgesGeometry` feature-edge angle, in degrees, on a balanced model.
   *  Higher keeps fewer, stricter edges. */
  edgeAngleBalancedDeg: number;
  /** The same angle on a model the deterministic signal classified large. */
  edgeAngleLargeModelDeg: number;
}

export const VISUALIZATION_MODES: Record<VisualizationMode, VisualizationModeThresholds> = {
  /** Reproduces the pre-Task-31 thresholds exactly. */
  fine: {
    projectedSizeHidePx: 20,
    projectedSizeRestorePx: 24,
    edgeAngleBalancedDeg: 25,
    edgeAngleLargeModelDeg: 40,
  },
  /** The default: same algorithms, entering the reduced state earlier. */
  standard: {
    projectedSizeHidePx: 32,
    projectedSizeRestorePx: 38,
    edgeAngleBalancedDeg: 40,
    edgeAngleLargeModelDeg: 55,
  },
  /** Reduces earliest and retains the fewest feature edges. */
  fast: {
    projectedSizeHidePx: 48,
    projectedSizeRestorePx: 58,
    edgeAngleBalancedDeg: 55,
    edgeAngleLargeModelDeg: 70,
  },
};

/** Standard is the initial mode and the mode Reset App returns to (task31 §2.1). */
export const DEFAULT_VISUALIZATION_MODE: VisualizationMode = "standard";

/** Display order of the three-option control, finest first. */
export const VISUALIZATION_MODE_ORDER: readonly VisualizationMode[] = [
  "fine",
  "standard",
  "fast",
];

export const VISUALIZATION_MODE_LABELS: Record<VisualizationMode, string> = {
  fine: "Fine",
  standard: "Standard",
  fast: "Fast",
};

// ===========================================================================
// 5. NAVIGATION AND FRAMING
// ===========================================================================

export const VIEWER_NAVIGATION = {
  /**
   * Orthographic floor-plan wheel-zoom speed (task31 §5.2). The installed
   * View/Plan mode assigns a much more abrupt 6 when the view is given a world,
   * so the adapter re-asserts this value after the plan camera exists. The
   * installed camera-controls build drives BOTH its dolly and its zoom action
   * from `dollySpeed`, so this single value is the plan wheel speed. Perspective
   * 3D zoom, pan speed, fit framing, zoom bounds and button mapping are
   * untouched by it.
   */
  planWheelZoomSpeed: 2,

  // ---- 50 mm lens on a 36x24 mm full-frame camera (task14 §2) --------------
  focalLengthMm: 50,
  filmGaugeMm: 36,
  filmHeightMm: 24,

  // ---- framing ------------------------------------------------------------
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

// ===========================================================================
// 6. OTHER DIRECTLY USER-VISIBLE VIEWER VALUES
// ===========================================================================

export const PLAN_GRAPHICS = {
  /**
   * Nominal horizontal cut above the selected floor, as a presentation-only
   * SCENE distance in metres (the installed Fragments/viewer coordinate path is
   * metre-scale). It never rewrites a stored measurement and never touches
   * Task 27's IFC-native unit contract.
   */
  cutOffsetM: 1.2,
} as const;
