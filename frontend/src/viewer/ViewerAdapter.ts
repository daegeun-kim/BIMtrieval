// Typed viewer adapter (spec_v006 §11; tasks/task11, task14 §1-§3). All
// imperative That Open / Three.js scene mutation lives here; React components
// never touch the scene directly. One active Fragments model at a time.
//
// Every color/opacity/camera constant comes from ./viewerTheme — none may be
// written inline here (task14 §1).
//
// Desktop control mapping (task14 §2):
//   left click (no meaningful movement) -> select
//   left drag                           -> pan
//   middle/wheel drag                   -> rotate about a cursor-derived pivot
//   wheel                               -> zoom
//   Ctrl/Shift + click                  -> additive selection (max 5)
import * as OBC from "@thatopen/components";
import * as FRAGS from "@thatopen/fragments";
// Bundle the fragments worker locally instead of OBC.FragmentsManager.getWorker(),
// which fetches it from the unpkg CDN at runtime — this app must work fully
// offline against the local backend (spec_v006 §2, §17).
import fragmentsWorkerUrl from "@thatopen/fragments/worker?url";
import * as THREE from "three";

import { EdgeOverlay, type EdgeRole } from "./EdgeOverlay";
import {
  planAvailability,
  resolvePlanRange,
  storeyLocalY,
  type SceneBand,
} from "./floorPlan";
import { type Profile, detectProfile } from "./profileDetection";
import { ProjectedSizePolicy, asPolicyModel, projectedSizeThresholds } from "./ProjectedSizePolicy";
import {
  DEFAULT_VISUALIZATION_MODE,
  EDGES,
  VIEWER_NAVIGATION,
  VISUALIZATION_MODES,
  type VisualizationMode,
} from "./viewerCustomization";
import {
  BASE_MATERIALS,
  DIM_MATERIAL,
  MANUAL_MATERIAL,
  PLAN,
  PLAN_CUT_COLOR,
  PLAN_CUT_OPACITY,
  PLAN_FILL_COLOR,
  PLAN_FILL_OPACITY,
  PLAN_WALL_CUT_COLOR,
  PLANE_COLOR,
  PLANE_OPACITY,
  PRIMARY_MATERIAL,
  PRIMARY_UNFOCUSED_MATERIAL,
  SCENE_BACKGROUND,
  VIEWER_CAMERA,
  geometryRole,
  type GeometryRole,
} from "./viewerTheme";

// camera-controls ACTION values. Read from the live instance's own constructor
// rather than importing camera-controls (a transitive dependency of
// @thatopen/components) so no new direct dependency is introduced.
const ACTION = { NONE: 0, ROTATE: 1, TRUCK: 2, DOLLY: 16, ZOOM: 32 } as const;

export interface ViewerCallbacks {
  onManualSelectionChange?: (guids: string[]) => void;
  onSelectionLimitReached?: () => void;
}

export interface RoleApplyResult {
  missing: string[];
}

/**
 * One logical floor band as the backend's read-only `/floors` contract reports
 * it (task28 §2.1). `min_elevation`/`max_elevation` are deliberately absent:
 * those are stored project-unit diagnostics, NOT scene coordinates, so the
 * adapter cannot accidentally use them as Three.js Y values. Scene heights come
 * only from the loaded artifact, resolved through `storey_global_ids`.
 */
export interface FloorContractBand {
  band_index: number;
  label: string;
  storey_global_ids: string[];
}

/** Whether one floor can actually be shown, for the button's enabled state. */
export interface FloorPlanState {
  bandIndex: number;
  label: string;
  enabled: boolean;
  /** Concise reason when the floor cannot be mapped into scene coordinates. */
  reason: string | null;
}

export interface PlanModeResult {
  ok: boolean;
  /** A concise, non-blocking limitation to surface, if any. */
  reason?: string;
}

/** Classified base-color membership for the loaded model (task14 §1). */
interface BaseClassification {
  roof: number[];
  wall: number[];
}

type ViewerWorld = OBC.SimpleWorld<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>;

/** Detach and release one plan-only drawable's geometry and material. */
function disposeDrawable(object: THREE.Object3D): void {
  try {
    object.removeFromParent();
    const drawable = object as THREE.Mesh;
    drawable.geometry?.dispose();
    const material = drawable.material as THREE.Material | THREE.Material[] | undefined;
    if (Array.isArray(material)) material.forEach((m) => m?.dispose());
    else material?.dispose();
  } catch {
    // disposal is best-effort; never fail a mode change over it
  }
}

export class ViewerAdapter {
  private components: OBC.Components | null = null;
  private world: ViewerWorld | null = null;
  private fragments: OBC.FragmentsManager | null = null;
  private model: FRAGS.FragmentsModel | null = null;
  private modelId: string | null = null;

  private manual = new Map<string, number>(); // guid -> localId
  private queryPrimary: number[] = [];
  // Resolved local-id sets for picking eligibility and edge recoloring
  // (task15 §3): membership checks never call the backend or an LLM.
  private queryPrimarySet = new Set<number>();
  private rolesActive = false;
  private selectionEnabled = true;
  private edgeOverlay: EdgeOverlay | null = null;

  private pointerDown: { x: number; y: number; button: number } | null = null;
  private readonly maxSelection: number;
  private callbacks: ViewerCallbacks = {};

  private basePlane: THREE.Object3D | null = null;
  /** Scene-space Y of the visual base plane — the model's lowest geometric point (task19 §3). */
  private groundY = 0;
  /**
   * Width, in CSS px, occupied by visible right-side panels — from the App
   * layer, the single source of truth for panel geometry (task19 §2). Read by
   * `applyViewOffset` on every fit and every panel-geometry change.
   */
  private rightObstructionPx = 0;
  private classification: BaseClassification = { roof: [], wall: [] };
  private disposers: Array<() => void> = [];
  /**
   * Adaptive profile is retained ONLY to size the isolated component preview
   * (fps cap / pixel ratio; task18 §10). It no longer drives any main-viewer
   * rendering decision — the adaptive main-viewer machinery (manual scheduler,
   * pixel-ratio stepping, motion edge-hiding, Fragments throttling) was removed
   * as the source of interaction-time hitches (spec_v006 §28).
   */
  private profile: Profile = "balanced";
  private profileOverride: Profile | null = null;
  private lastDetectedProfile: Profile = "balanced";
  /**
   * Projected-size rendering policy (task23 issue 2). Hides non-fundamental
   * objects that are too small on screen. Evaluated only on load, camera rest,
   * resize, and view-offset changes — never per frame and never per motion tick,
   * so it cannot reintroduce the Task 18/20 interaction hitches Task 22 removed.
   */
  private sizePolicy = new ProjectedSizePolicy();
  private sizePolicyActive = false;

  /**
   * User-selected visualization quality (task31 §2). Session-level, never
   * persisted, and deliberately NOT reset by a model switch or unload — only
   * Reset App returns it to Standard, which the controller does explicitly.
   *
   * It changes exactly two things: the projected-size hysteresis pair handed to
   * `sizePolicy`, and the feature-edge angle the edge overlay is extracted with.
   * Every other rendering mechanism is identical in all three modes.
   */
  private visualizationMode: VisualizationMode = DEFAULT_VISUALIZATION_MODE;
  /** Every renderable local id of the loaded model, resolved once at load and
   *  reused by an edge rebuild and the plan wall layer — never re-fetched. */
  private allLocalIds: number[] = [];
  /** Monotonic token so a superseded edge-overlay build can never mount
   *  (task31 §2.3): another mode change, a model switch, unload, or dispose. */
  private edgeToken = 0;

  // -------------------------------------------------------------------------
  // Floor-plan mode (task28). Every mutable object here is imperative viewer
  // state — cameras, clipping planes, section meshes — so none of it belongs in
  // the serializable application store (task28 §6).
  // -------------------------------------------------------------------------
  private views: OBC.Views | null = null;
  private planView: OBC.View | null = null;
  /** The active logical band, or null in normal 3D mode. */
  private planBandIndex: number | null = null;
  /** Logical bands mapped into this artifact's scene space, ascending. */
  private sceneBands: SceneBand[] = [];
  /**
   * The perspective pose to return to. Captured only when FIRST leaving 3D, so
   * switching floor-to-floor never overwrites it (task28 §1.2).
   */
  private savedPose: { position: THREE.Vector3; target: THREE.Vector3 } | null = null;
  /** Live cut contour/fill layers for the ACTIVE floor only (task28 §4.3). */
  private planSection: { group: THREE.Group } | null = null;
  /**
   * Monotonic token so an older floor's asynchronous section result can never
   * overwrite a newer selection (task28 §4.3, §6).
   */
  private planToken = 0;
  /** The active plan range, for tests/diagnostics. */
  private planRange: { cut: number; lower: number } | null = null;
  /** True while the projected-size policy is suspended for plan mode. */
  private sizePolicySuspended = false;

  constructor(maxSelection = 5) {
    this.maxSelection = maxSelection;
    this.sizePolicy.setThresholds(projectedSizeThresholds(this.visualizationMode));
  }

  setCallbacks(cb: ViewerCallbacks): void {
    this.callbacks = cb;
  }

  isInitialized(): boolean {
    return this.components !== null;
  }

  hasModel(): boolean {
    return this.model !== null;
  }

  /**
   * Scene-space Y of the visual base plane, i.e. the loaded model's lowest
   * geometric point — exposed for tests (task19 §3). Not an IFC elevation.
   */
  getGroundY(): number {
    return this.groundY;
  }

  async init(container: HTMLElement): Promise<void> {
    if (this.components) return;

    const components = new OBC.Components();
    const worlds = components.get(OBC.Worlds);
    const world = worlds.create<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>();

    world.scene = new OBC.SimpleScene(components);
    world.scene.setup();
    world.scene.three.background = SCENE_BACKGROUND.clone();

    world.renderer = new OBC.SimpleRenderer(components, container);
    world.camera = new OBC.OrthoPerspectiveCamera(components);

    components.init();

    const fragments = components.get(OBC.FragmentsManager);
    fragments.init(fragmentsWorkerUrl);

    // Continuous, automatic rendering (SimpleRenderer's default mode). Refresh
    // Fragments LOD/visibility when the camera settles and when a model loads.
    //
    // Task 18/20's adaptive main-viewer machinery — a manual invalidation
    // scheduler, adaptive pixel ratio, motion-based edge hiding, and per-motion
    // Fragments throttling — was removed here: on the owner's RTX 5080 the raw
    // per-frame cost was never the bottleneck, but the per-gesture transition
    // work (a forced Fragments update on every rest, edge hide/restore, and
    // pixel-ratio toggling on every wake) produced a visible hitch on every
    // start/stop of a pan or orbit. Continuous fixed-quality rendering is
    // heavier while idle but smooth during interaction (spec_v006 §28).
    world.camera.controls.addEventListener("rest", () => {
      // Re-evaluate projected sizes at rest, then refresh Fragments once. The
      // policy runs BEFORE the update so a single Fragments refresh covers both
      // the LOD change and the visibility change (task23 issue 2).
      void this.applyProjectedSizePolicy().then(() => this.updateFragments());
    });
    fragments.list.onItemSet.add(({ value: model }) => {
      model.useCamera(world.camera.three as THREE.PerspectiveCamera);
      world.scene.three.add(model.object);
      void this.updateFragments();
    });

    this.components = components;
    this.world = world;
    this.fragments = fragments;

    this.configureControls();
    this.applyLens();
    this.attachPointer(container);
    // Catches an obstruction set via setViewportObstruction before init
    // finished (task19 §2) — a no-op re-application otherwise.
    this.applyViewOffset();
  }

  // -------------------------------------------------------------------------
  // Camera + controls (task14 §2)
  // -------------------------------------------------------------------------

  /**
   * Desktop BIM control mapping: left-drag pans, middle-drag orbits, wheel
   * zooms. camera-controls defaults to left=rotate, so this must be set
   * explicitly.
   */
  private configureControls(): void {
    const controls = this.world?.camera.controls;
    if (!controls) return;
    try {
      controls.mouseButtons.left = ACTION.TRUCK; // pan
      controls.mouseButtons.middle = ACTION.ROTATE; // orbit
      controls.mouseButtons.wheel = ACTION.DOLLY; // zoom
      controls.mouseButtons.right = ACTION.TRUCK;
    } catch {
      // controls shape can differ across versions; never fail init over it
    }
  }

  /**
   * Plan navigation on the floor-plan camera (task28 §1.2): every drag pans and
   * the wheel zooms the orthographic frustum — no button orbits.
   *
   * The library's own `PlanMode` (set when the View is given a world) already
   * zeroes the rotate speeds and maps left-drag to truck; this makes the middle
   * and right buttons pan too, so the desktop mapping stays consistent with 3D
   * mode instead of leaving a dead button.
   *
   * It also re-asserts the accepted wheel-zoom speed (task31 §5.2). Assigning a
   * world to a `View` sets `dollySpeed = 6` on that view's own camera, which is
   * abrupt enough to overshoot a floor on a single notch; this runs AFTER the
   * plan camera and mode exist, so the library default cannot win. The installed
   * camera-controls build drives both its dolly and its zoom action from
   * `dollySpeed`, so this one assignment is the plan wheel speed. The
   * perspective camera's controls are a different instance and are untouched.
   */
  private configurePlanControls(camera: OBC.OrthoPerspectiveCamera): void {
    const controls = camera.controls;
    if (!controls) return;
    try {
      controls.mouseButtons.left = ACTION.TRUCK;
      controls.mouseButtons.middle = ACTION.TRUCK;
      controls.mouseButtons.right = ACTION.TRUCK;
      controls.mouseButtons.wheel = ACTION.ZOOM; // orthographic zoom, not dolly
      controls.dollySpeed = VIEWER_NAVIGATION.planWheelZoomSpeed;
    } catch {
      // controls shape can differ across versions; never fail plan mode over it
    }
  }

  /** The plan camera's current wheel-zoom speed, for tests (task31 §5.2). */
  getPlanZoomSpeed(): number | null {
    return this.planView?.camera.controls?.dollySpeed ?? null;
  }

  /** The perspective camera's zoom speed, which plan mode must never change. */
  getPerspectiveZoomSpeed(): number | null {
    return this.world?.camera.controls?.dollySpeed ?? null;
  }

  // -------------------------------------------------------------------------
  // Visualization modes (task31 §2)
  // -------------------------------------------------------------------------

  getVisualizationMode(): VisualizationMode {
    return this.visualizationMode;
  }

  /**
   * Apply a visualization mode to the CURRENTLY loaded model — no download, no
   * reconversion, no page reload (task31 §2.3).
   *
   * Two effects, both bounded:
   *
   *   1. the projected-size hysteresis pair is swapped and the policy is
   *      re-evaluated against the cached classification/bounding volumes, then
   *      Fragments is refreshed once through the established update path;
   *   2. if the applicable feature-edge angle changed, the edge overlay is
   *      regenerated asynchronously — the angle is baked in when `EdgesGeometry`
   *      extracts the edges, so it cannot be recolored into place.
   *
   * Nothing here touches query/manual identities, the camera pose, the active
   * floor, or any panel state.
   */
  async setVisualizationMode(mode: VisualizationMode): Promise<void> {
    if (mode === this.visualizationMode) return;
    this.visualizationMode = mode;

    this.sizePolicy.setThresholds(projectedSizeThresholds(mode));
    await this.applyProjectedSizePolicy();
    await this.updateFragments();

    // Compared against the angle the LIVE overlay was extracted with (including
    // one still building), not against the outgoing mode's nominal angle, so a
    // profile upgrade between the two can never skip a needed rebuild.
    const current = this.edgeOverlay?.getThresholdDeg() ?? null;
    if (current !== null && current !== this.edgeAngleDeg()) this.rebuildEdgeOverlay();
  }

  /**
   * The feature-edge angle in force: the selected mode's value for the model's
   * DETECTED balanced/large-model signal (task31 §2.2). That signal still
   * chooses which of the mode's two angles applies; it never chooses the mode.
   */
  private edgeAngleDeg(): number {
    const thresholds = VISUALIZATION_MODES[this.visualizationMode];
    return this.lastDetectedProfile === "large-model"
      ? thresholds.edgeAngleLargeModelDeg
      : thresholds.edgeAngleBalancedDeg;
  }

  /** The angle the active overlay was actually extracted with, for tests. */
  getEdgeThresholdDeg(): number | null {
    return this.edgeOverlay?.getThresholdDeg() ?? null;
  }

  /**
   * Discard the current entity-edge overlay and extract a new one at the
   * in-force angle, in the same yielded batches the initial build uses so
   * interaction stays usable (task31 §2.3).
   *
   * The old overlay is disposed FIRST, so a rebuild can never leave two
   * overlays in the scene or an undisposed buffer behind; the model is briefly
   * without edges while the new one extracts. The token retires a build whose
   * mode, model, or adapter changed underneath it — such a build mounts
   * nothing and disposes itself.
   */
  private rebuildEdgeOverlay(): void {
    if (!EDGES.enabled) return;
    const model = this.model;
    if (!model) return;

    const token = ++this.edgeToken;
    this.edgeOverlay?.dispose();
    this.edgeOverlay = null;

    const overlay = new EdgeOverlay();
    this.edgeOverlay = overlay;
    const thresholdDeg = this.edgeAngleDeg();
    void overlay
      .build(model, model.object, { thresholdDeg, localIds: this.allLocalIds })
      .then((built) => {
        if (token !== this.edgeToken || this.edgeOverlay !== overlay) {
          // Superseded mid-build: drop whatever it mounted rather than leaving
          // a stale-angle overlay beside the current one.
          overlay.dispose();
          return;
        }
        if (built) this.recolorEdges();
      });
  }

  /**
   * 50 mm lens on a 36x24 mm full-frame camera (task14 §2).
   *
   * Uses three.js's own focal-length/film-gauge support rather than hard-coding
   * a FOV, so the vertical FOV stays correct as the aspect ratio changes.
   */
  private applyLens(): void {
    const cam = this.world?.camera.three;
    if (!cam || !(cam as THREE.PerspectiveCamera).isPerspectiveCamera) return;
    const perspective = cam as THREE.PerspectiveCamera;
    perspective.filmGauge = VIEWER_CAMERA.filmGaugeMm;
    perspective.setFocalLength(VIEWER_CAMERA.focalLengthMm);
    perspective.updateProjectionMatrix();
  }

  /**
   * Width, in CSS px, currently occupied by visible right-side panels
   * (task19 §2) — called by the App layer whenever a panel opens, closes,
   * collapses, or resizes, reusing its own live panel width/component-open
   * state rather than a hard-coded copy in the viewer. Only updates the
   * camera's projection offset (`applyViewOffset`); never moves, refits, or
   * resets the camera on its own, so panel changes never unexpectedly jump
   * the user's current view.
   */
  setViewportObstruction(px: number): void {
    const next = Math.max(0, px);
    if (next === this.rightObstructionPx) return;
    this.rightObstructionPx = next;
    this.applyViewOffset();
    // A projection change can alter projected sizes (task23 issue 2).
    void this.applyProjectedSizePolicy().then(() => this.updateFragments());
  }

  /**
   * Shifts/scopes the camera's projection matrix, via three.js's own
   * `setViewOffset`, so that fitted content centers within the unobstructed
   * left region rather than the full canvas (task19 §2) — a pure
   * camera-framing calculation; the model is never translated.
   *
   * `setViewOffset(fullWidth, fullHeight, x, y, width, height)` sets
   * `camera.aspect = fullWidth / fullHeight` and renders a `width x height`
   * window of that virtual frustum. Passing `fullWidth = leftWidth` (the
   * visible region) with `width = canvasWidth` (the full, unshrunk render
   * target) means: (a) `camera.aspect` becomes `leftWidth / canvasHeight`,
   * exactly what `CameraControls.fitToBox` needs to size a fit so content
   * fits the NARROWER visible region rather than the full canvas — the fix
   * only centers, per the task's required behavior, this sizing side-effect
   * is what keeps a fit-to-full-width object from being clipped once
   * recentered; and (b) the rendered width/height ratio is provably
   * `width/height = canvasWidth/canvasHeight` regardless of `fullWidth`, so
   * the final image is never stretched. With `offsetX = 0`, content
   * `fitToBox` centered on the look axis lands exactly at pixel
   * `leftWidth / 2` — the visible-region centroid — with no extra shift term
   * needed. Because this only edits the projection matrix (not camera
   * position), THREE's raycasting — and therefore Fragments' own
   * camera+mouse+dom picking — stays pixel-correct automatically. Applied
   * before every `fitToBox` call (so the fit distance itself uses the
   * correct aspect) and re-applied standalone on any panel/resize change
   * (which reshapes/repositions the SAME already-framed view without moving
   * the camera).
   *
   * The same call is correct for the floor-plan mode's ORTHOGRAPHIC camera
   * (task28 §4.3): `OrthographicCamera.updateProjectionMatrix` widens the
   * horizontal frustum by exactly `width / fullWidth`, so a box that
   * `fitToBox` sized against the full canvas width lands filling precisely
   * the `leftWidth` visible region, centered on it — never clipped and never
   * stretched, since `fullHeight === height` leaves the vertical mapping
   * untouched. `OrthoPerspectiveCamera`'s own aspect handling re-applies the
   * stored offset on every projection update, so it survives resizes.
   */
  private applyViewOffset(): void {
    const cam = this.world?.camera.three as
      | (THREE.Camera & Partial<THREE.PerspectiveCamera> & Partial<THREE.OrthographicCamera>)
      | undefined;
    const dom = this.rendererDom();
    if (!cam || !(cam.isPerspectiveCamera || cam.isOrthographicCamera) || !dom) return;
    if (!cam.setViewOffset || !cam.clearViewOffset) return;
    const canvasW = dom.clientWidth || 1;
    const canvasH = dom.clientHeight || 1;
    const effectiveWidth = this.effectiveViewportWidth(canvasW);
    // The orthographic frustum must be reshaped BEFORE the offset is written:
    // `fitToBox` reads `right - left` synchronously to size an orthographic fit.
    this.applyOrthoScale(cam, effectiveWidth, canvasH);
    if (effectiveWidth >= canvasW - 0.5) {
      cam.clearViewOffset();
      return;
    }
    cam.setViewOffset(effectiveWidth, canvasH, 0, 0, canvasW, canvasH);
  }

  /** The unobstructed viewer region's width in CSS px, floored by the guard. */
  private effectiveViewportWidth(canvasW: number): number {
    const minLeftWidth = canvasW * VIEWER_CAMERA.minEffectiveWidthFraction;
    return Math.min(canvasW, Math.max(canvasW - this.rightObstructionPx, minLeftWidth));
  }

  /**
   * Equal scale on both plan axes (task31 §5.3).
   *
   * One scene unit horizontally must occupy the same number of CSS pixels as one
   * scene unit vertically, so a square reads square and perpendicular geometry
   * stays perpendicular in every model's floor plan.
   *
   * With the view offset above applied, three.js renders the frustum's vertical
   * span `(top - bottom) / zoom` across `canvasH` px, and its horizontal span
   * `(right - left) / zoom * canvasW / effectiveWidth` across `canvasW` px. So:
   *
   *     px per unit horizontally = effectiveWidth * zoom / (right - left)
   *     px per unit vertically   = canvasH       * zoom / (top - bottom)
   *
   * and the two are equal exactly when
   *
   *     (right - left) / (top - bottom) === effectiveWidth / canvasH.
   *
   * The installed library never establishes that: `OrthoPerspectiveCamera`
   * builds its orthographic frustum from `window.innerWidth / window.innerHeight`
   * — the WINDOW aspect, not the canvas's — and its resize handler leaves a
   * View's own camera untouched because that camera never saw a world creation
   * event, so nothing corrects it afterwards either. The result is a horizontally
   * compressed plan in every model, worsened by the panel obstruction.
   *
   * This rewrites only the HORIZONTAL half-extent, symmetric about the frustum's
   * existing centre, and leaves `top`/`bottom` (and `zoom`) alone: the vertical
   * mapping is the authoritative one, exactly as a fixed vertical FOV is for the
   * perspective camera. Because the resulting px-per-unit is
   * `canvasH * zoom / (top - bottom)` — independent of `effectiveWidth` — a
   * panel opening, closing or resizing narrows the visible region without
   * rescaling the drawing at all. No model is scaled or transformed, no section
   * geometry is touched, no package is patched, and no per-model factor exists.
   * Perspective cameras are returned untouched, so 3D projection and
   * pixel-correct picking are unaffected.
   */
  private applyOrthoScale(
    cam: THREE.Camera & Partial<THREE.OrthographicCamera>,
    effectiveWidth: number,
    canvasH: number,
  ): void {
    if (!cam.isOrthographicCamera) return;
    const { left, right, top, bottom } = cam;
    if (
      left === undefined ||
      right === undefined ||
      top === undefined ||
      bottom === undefined
    ) {
      return;
    }
    const verticalSpan = top - bottom;
    if (!Number.isFinite(verticalSpan) || verticalSpan <= 0) return;
    if (!Number.isFinite(effectiveWidth) || effectiveWidth <= 0 || canvasH <= 0) return;

    const halfWidth = (verticalSpan * (effectiveWidth / canvasH)) / 2;
    if (!Number.isFinite(halfWidth) || halfWidth <= 0) return;
    const centerX = (right + left) / 2;
    if (Math.abs(right - left - halfWidth * 2) < 1e-9) return; // already correct
    cam.left = centerX - halfWidth;
    cam.right = centerX + halfWidth;
    cam.updateProjectionMatrix?.();
  }

  /**
   * CSS px per scene unit on each axis under the active camera — exposed so the
   * equal-scale guarantee (task31 §5.3) is measurable rather than asserted.
   * `null` outside orthographic (plan) mode.
   */
  getPlanPixelScale(): { horizontal: number; vertical: number } | null {
    const cam = this.world?.camera.three as
      | (THREE.Camera & Partial<THREE.OrthographicCamera>)
      | undefined;
    const dom = this.rendererDom();
    if (!cam?.isOrthographicCamera || !dom) return null;
    const { left, right, top, bottom, zoom } = cam;
    if (left === undefined || right === undefined || top === undefined || bottom === undefined) {
      return null;
    }
    const canvasW = dom.clientWidth || 1;
    const canvasH = dom.clientHeight || 1;
    const scale = zoom ?? 1;
    return {
      horizontal: (this.effectiveViewportWidth(canvasW) * scale) / (right - left),
      vertical: (canvasH * scale) / (top - bottom),
    };
  }

  /**
   * Current performance profile (tasks/task18.md §11) — now consumed ONLY by
   * the isolated component preview for its fps cap / pixel ratio. It no longer
   * affects any main-viewer rendering (spec_v006 §28).
   */
  getProfile(): Profile {
    return this.profile;
  }

  /**
   * User profile override — `null` means automatic detection. Retained so the
   * preview can be pinned; takes effect the next time a preview is opened.
   */
  setProfileOverride(profile: Profile | null): void {
    this.profileOverride = profile;
    this.profile = profile ?? this.lastDetectedProfile;
  }

  getProfileOverride(): Profile | null {
    return this.profileOverride;
  }

  /** Applies an automatically DETECTED profile, unless a user override is active. */
  private applyDetectedProfile(profile: Profile): void {
    this.lastDetectedProfile = profile;
    if (this.profileOverride === null) this.profile = profile;
  }

  /** Current vertical FOV — exposed for tests (task14 §8). */
  getFieldOfView(): number | null {
    const cam = this.world?.camera.three as THREE.PerspectiveCamera | undefined;
    return cam?.isPerspectiveCamera ? cam.fov : null;
  }

  /** Current camera-controls max dolly distance — exposed for tests. */
  getMaxDistance(): number | null {
    return this.world?.camera.controls?.maxDistance ?? null;
  }

  /**
   * Finite zoom-out bound of ~3x the model bounding-box diagonal, with a floor
   * for tiny/test models. Recomputed on every model load; never restricts
   * zooming *into* the model.
   */
  private applyZoomBound(box: THREE.Box3 | null): void {
    const controls = this.world?.camera.controls;
    if (!controls) return;
    if (!box || box.isEmpty()) {
      controls.maxDistance = Infinity;
      return;
    }
    const size = new THREE.Vector3();
    box.getSize(size);
    const diagonal = size.length();
    controls.maxDistance = Math.max(
      VIEWER_CAMERA.minMaxDistance,
      diagonal * VIEWER_CAMERA.maxDistanceDiagonalFactor,
    );
  }

  // -------------------------------------------------------------------------
  // Pointer: click-vs-drag, rotation pivot, cursor state
  // -------------------------------------------------------------------------

  private attachPointer(container: HTMLElement): void {
    const dom = this.rendererDom() ?? container;

    const onDown = (e: PointerEvent) => {
      this.pointerDown = { x: e.clientX, y: e.clientY, button: e.button };
      if (e.button === 1) {
        // Middle button starts an orbit: set the pivot from what is under the
        // cursor before camera-controls begins rotating.
        void this.setPivotFromCursor(e);
        this.setCursor(dom, "grabbing");
      } else if (e.button === 0) {
        this.setCursor(dom, "grabbing");
      }
    };

    const onUp = (e: PointerEvent) => {
      const start = this.pointerDown;
      this.pointerDown = null;
      this.setCursor(dom, "grab");
      if (!start || !this.selectionEnabled) return;
      if (start.button !== 0) return; // only a plain left click selects
      const moved = Math.hypot(e.clientX - start.x, e.clientY - start.y);
      if (moved > VIEWER_CAMERA.clickMoveTolerance) return; // that was a pan
      void this.handlePick(e);
    };

    dom.addEventListener("pointerdown", onDown);
    dom.addEventListener("pointerup", onUp);
    // Middle-drag would otherwise trigger the browser's autoscroll on Windows.
    const onAux = (e: MouseEvent) => {
      if (e.button === 1) e.preventDefault();
    };
    dom.addEventListener("auxclick", onAux);
    const onContext = (e: MouseEvent) => e.preventDefault();
    dom.addEventListener("contextmenu", onContext);

    this.setCursor(dom, "grab");
    this.disposers.push(() => {
      dom.removeEventListener("pointerdown", onDown);
      dom.removeEventListener("pointerup", onUp);
      dom.removeEventListener("auxclick", onAux);
      dom.removeEventListener("contextmenu", onContext);
    });
  }

  private setCursor(dom: HTMLElement, cursor: "grab" | "grabbing"): void {
    try {
      dom.style.cursor = cursor;
    } catch {
      // ignore
    }
  }

  /**
   * Orbit pivot resolution (task14 §2):
   *   1. raycast under the cursor against visible model geometry;
   *   2. otherwise intersect the visual base plane (task19 §3);
   *   3. otherwise retain the current orbit target.
   *
   * Never alters selection to establish a pivot.
   */
  private async setPivotFromCursor(event: PointerEvent): Promise<void> {
    const controls = this.world?.camera.controls;
    const camera = this.world?.camera.three;
    const dom = this.rendererDom();
    if (!controls || !camera || !dom) return;

    // 1. geometry under the cursor
    if (this.model) {
      try {
        const hit = await this.model.raycast({
          camera,
          mouse: new THREE.Vector2(event.clientX, event.clientY),
          dom,
        });
        if (hit?.point) {
          controls.setOrbitPoint(hit.point.x, hit.point.y, hit.point.z);
          return;
        }
      } catch {
        // fall through to the ground plane
      }
    }

    // 2. visual base plane
    const point = this.intersectGroundPlane(event, camera, dom);
    if (point) {
      controls.setOrbitPoint(point.x, point.y, point.z);
      return;
    }
    // 3. keep the current target — do nothing.
  }

  private intersectGroundPlane(
    event: PointerEvent,
    camera: THREE.Camera,
    dom: HTMLElement,
  ): THREE.Vector3 | null {
    try {
      const rect = dom.getBoundingClientRect();
      const ndc = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(ndc, camera);
      const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -this.groundY);
      const point = new THREE.Vector3();
      return raycaster.ray.intersectPlane(plane, point) ? point : null;
    } catch {
      return null;
    }
  }

  private rendererDom(): HTMLCanvasElement | null {
    const three = this.world?.renderer?.three as THREE.WebGLRenderer | undefined;
    return three?.domElement ?? null;
  }

  /**
   * Resolves the local ID a click should select, or null for "no pick" (task19
   * §1).
   *
   * While one or more blue query-primary results exist, transparent/dimmed
   * non-result geometry must not block the ray: this branch collects EVERY
   * intersection along the ray (`raycastAll`, one local worker round trip, no
   * backend/LLM call), sorts by distance, and returns the nearest hit whose
   * local ID is already in `queryPrimarySet` — never mutating visibility or
   * building a per-entity picking mesh. A ray with no blue hit returns null,
   * which `handlePick` treats exactly like a total miss (the existing
   * empty-space-clears-selection path), since non-results are meant to be
   * transparent to picking, not a wall that merely no-ops.
   *
   * Without active roles, behavior is unchanged: a single nearest-hit raycast
   * against whatever is visible.
   */
  private async resolvePickLocalId(event: PointerEvent, dom: HTMLCanvasElement): Promise<number | null> {
    if (!this.model || !this.world) return null;
    const camera = this.world.camera.three;
    const mouse = new THREE.Vector2(event.clientX, event.clientY);

    if (this.rolesActive && this.queryPrimarySet.size > 0) {
      let hits: FRAGS.RaycastResult[] | null = null;
      try {
        hits = await this.model.raycastAll({ camera, mouse, dom });
      } catch {
        hits = null;
      }
      if (!hits || hits.length === 0) return null;
      let nearest: FRAGS.RaycastResult | null = null;
      for (const hit of hits) {
        if (!this.queryPrimarySet.has(hit.localId)) continue;
        if (!nearest || hit.distance < nearest.distance) nearest = hit;
      }
      return nearest?.localId ?? null;
    }

    let result: FRAGS.RaycastResult | null = null;
    try {
      result = await this.model.raycast({ camera, mouse, dom });
    } catch {
      result = null;
    }
    // An object hidden by the projected-size policy cannot be picked (task23
    // issue 2). Belt-and-braces: Fragments should not raycast invisible items,
    // but selection identity must not depend on that implementation detail.
    if (result && this.isHiddenBySize(result.localId)) return null;
    return result?.localId ?? null;
  }

  private async handlePick(event: PointerEvent): Promise<void> {
    if (!this.model || !this.world) return;
    const dom = this.rendererDom();
    if (!dom) return;
    const additive = event.ctrlKey || event.shiftKey || event.metaKey;

    const localId = await this.resolvePickLocalId(event, dom);

    if (localId === null) {
      if (!additive && this.manual.size > 0) {
        this.manual.clear();
        this.emitManual();
        await this.renderHighlights();
      }
      return;
    }

    const guids = await this.model.getGuidsByLocalIds([localId]);
    const guid = guids[0];
    if (!guid) return; // element without a stable GlobalId — ignore

    if (additive) {
      if (this.manual.has(guid)) {
        this.manual.delete(guid);
      } else if (this.manual.size >= this.maxSelection) {
        this.callbacks.onSelectionLimitReached?.();
        return;
      } else {
        this.manual.set(guid, localId);
      }
    } else {
      this.manual.clear();
      this.manual.set(guid, localId);
    }
    this.emitManual();
    await this.renderHighlights();
  }

  private emitManual(): void {
    this.callbacks.onManualSelectionChange?.([...this.manual.keys()]);
  }

  removeManualSelection(guid: string): void {
    if (this.manual.delete(guid)) {
      this.emitManual();
      void this.renderHighlights();
    }
  }

  clearManualSelection(): void {
    if (this.manual.size === 0) return;
    this.manual.clear();
    this.emitManual();
    void this.renderHighlights();
  }

  setSelectionEnabled(enabled: boolean): void {
    this.selectionEnabled = enabled;
  }

  // -------------------------------------------------------------------------
  // Model lifecycle
  // -------------------------------------------------------------------------

  async loadModel(bytes: ArrayBuffer, modelId: string): Promise<void> {
    if (!this.fragments) throw new Error("viewer not initialized");
    await this.unloadModel();
    const model = await this.fragments.core.load(bytes, { modelId });
    this.model = model;
    this.modelId = modelId;
    await this.updateFragments();

    await this.resolveGroundY();
    this.classification = await this.classifyGeometry();
    await this.renderHighlights();
    this.createBasePlane();

    // Provisional adaptive profile (task18 §11): geometric/runtime signals
    // ONLY (artifact bytes + item count) — never model name/ID/category/
    // discipline/storey. Decided now, before the edge build, so the correct
    // profile-specific edge-angle threshold (task18 §6) and pixel-ratio/
    // Fragments-throttle defaults apply from the first frame, not after a
    // second pass. One `getLocalIds()` call is shared with the edge build
    // below via `options.localIds` so this never costs a second worker
    // round trip.
    let localIds: number[] = [];
    try {
      localIds = await model.getLocalIds();
    } catch {
      // profile detection is best-effort; an empty list just yields "balanced"
    }
    this.allLocalIds = localIds;
    let profile: Profile = detectProfile({ artifactBytes: bytes.byteLength, itemCount: localIds.length }, null);
    this.applyDetectedProfile(profile);

    // Projected-size policy (task23 issue 2): classify categories and cache
    // bounding volumes once, from the artifact only. Failure leaves the policy
    // inactive and every object visible — it is an optimization, never a
    // correctness requirement.
    //
    // Candidates self-restrict to geometry-bearing items: `getBoxes` returns an
    // empty box for an item with no geometry, and `prepare` skips those. This is
    // deliberately NOT done via `getItemsWithGeometry()`, which was measured
    // stalling for minutes on the 283k-item reference model.
    this.sizePolicyActive = await this.sizePolicy.prepare(asPolicyModel(model), localIds);
    if (this.sizePolicyActive) await this.applyProjectedSizePolicy();

    // Optional edge overlay (task15 §2): built asynchronously AFTER the scene
    // is ready and usable, in yielded batches, so it never delays load or
    // blocks input. When it finishes it paints itself from the current roles.
    if (EDGES.enabled) {
      const token = ++this.edgeToken;
      const overlay = new EdgeOverlay();
      this.edgeOverlay = overlay;
      // The angle comes from the SELECTED visualization mode's entry for this
      // model's detected profile (task31 §2.2), so a mode chosen before the load
      // applies from the first extraction rather than triggering a rebuild.
      const thresholdDeg = this.edgeAngleDeg();
      void overlay.build(model, model.object, { thresholdDeg, localIds }).then((built) => {
        // Ignore a build that finished after the model or the mode changed
        // underneath it — and release whatever it managed to mount.
        if (token !== this.edgeToken || this.edgeOverlay !== overlay) {
          overlay.dispose();
          return;
        }
        if (built) {
          this.recolorEdges();
          // Final profile (task18 §11): adds edge vertex count, the last of
          // the three signals. A single controlled upgrade from provisional —
          // detectProfile's hysteresis prevents this from flip-flopping. Only
          // the component preview reads the resulting profile now.
          profile = detectProfile(
            { artifactBytes: bytes.byteLength, itemCount: localIds.length, edgeVertexCount: overlay.getVertexCount() },
            profile,
          );
          this.applyDetectedProfile(profile);
        }
      });
    }

    let box: THREE.Box3 | null = null;
    try {
      box = model.box ? model.box.clone() : null;
    } catch {
      box = null;
    }
    this.applyZoomBound(box);
    await this.fitAll();
  }

  /**
   * Visual base-plane Y: the loaded model's lowest geometric point (task19 §3),
   * `model.box.min.y` in the same scene-space coordinates used to render the
   * model — i.e. AFTER the Fragments coordination transform, never derived
   * from it directly. Previously this used the coordination matrix's IFC/world
   * elevation 0, which could sit above or below the model's actual geometry;
   * that reading is a presentation-only choice for where the reference plane
   * touches, and must never be reported as an `IfcBuildingStorey` elevation or
   * the IFC coordinate origin. Falls back to scene 0 when the box is missing,
   * empty, or non-finite — the model itself is never translated or rebased to
   * make this true.
   */
  private async resolveGroundY(): Promise<void> {
    this.groundY = 0;
    if (!this.model) return;
    try {
      const box = this.model.box;
      if (box && !box.isEmpty() && Number.isFinite(box.min.y)) {
        this.groundY = box.min.y;
      }
    } catch {
      // a missing/broken box falls back to scene 0
    }
  }

  /**
   * Classify geometry into base-color roles (task14 §1). Wall includes every
   * IfcWall subtype in the artifact; an IfcSlab is roof ONLY when its explicit
   * predefined type says ROOF.
   */
  private async classifyGeometry(): Promise<BaseClassification> {
    const result: BaseClassification = { roof: [], wall: [] };
    if (!this.model) return result;
    try {
      const categories = await this.model.getCategories();
      const wanted = categories.filter((c) => {
        const role = geometryRole(c);
        return role !== "other" || c.trim().toLowerCase() === "ifcslab";
      });
      if (wanted.length === 0) return result;

      const byCategory = await this.model.getItemsOfCategories(
        wanted.map((c) => new RegExp(`^${c}$`)),
      );

      for (const [category, ids] of Object.entries(byCategory)) {
        if (!ids?.length) continue;
        const role = geometryRole(category);
        if (role === "roof") {
          result.roof.push(...ids);
        } else if (role === "wall") {
          result.wall.push(...ids);
        } else if (category.trim().toLowerCase() === "ifcslab") {
          result.roof.push(...(await this.roofSlabs(ids)));
        }
      }
    } catch {
      // classification is cosmetic; a failure must leave the viewer usable
    }
    return result;
  }

  /** Slabs whose explicit PredefinedType is ROOF — never inferred by name. */
  private async roofSlabs(slabIds: number[]): Promise<number[]> {
    if (!this.model) return [];
    try {
      const data = await this.model.getItemsData(slabIds, {
        attributesDefault: false,
        attributes: ["PredefinedType", "_localId"],
      });
      const roofs: number[] = [];
      data.forEach((item, index) => {
        const attr = item?.PredefinedType as { value?: unknown } | undefined;
        const value = typeof attr?.value === "string" ? attr.value : null;
        if (geometryRole("IfcSlab", value) === "roof") {
          const local = item?._localId as { value?: unknown } | undefined;
          const id = typeof local?.value === "number" ? local.value : slabIds[index];
          if (typeof id === "number") roofs.push(id);
        }
      });
      return roofs;
    } catch {
      return [];
    }
  }

  async unloadModel(): Promise<void> {
    // Model unload / model switch returns the viewer to its normal 3D mode and
    // disposes every plan resource (task28 §1.2). Plan state is never persisted.
    await this.exitPlanMode();
    this.sceneBands = [];
    this.savedPose = null;
    this.sizePolicySuspended = false;
    this.manual.clear();
    this.queryPrimary = [];
    this.queryPrimarySet = new Set();
    this.rolesActive = false;
    this.classification = { roof: [], wall: [] };
    this.allLocalIds = [];
    this.sizePolicy.reset();
    this.sizePolicyActive = false;
    // Retires any in-flight edge build for the outgoing model (task31 §2.3).
    // The visualization MODE itself deliberately survives a model switch.
    this.edgeToken++;
    this.edgeOverlay?.dispose();
    this.edgeOverlay = null;
    this.removeBasePlane();
    this.groundY = 0; // stored plane height resets on unload/model switch (task19 §3)
    if (this.fragments && this.modelId) {
      try {
        await this.fragments.core.disposeModel(this.modelId);
      } catch {
        // model may already be gone; ignore
      }
    }
    this.model = null;
    this.modelId = null;
  }

  // -------------------------------------------------------------------------
  // Base plane at the model's geometric minimum (task19 §3, amends task14 §2)
  // -------------------------------------------------------------------------

  /**
   * Quiet drafting grid at the loaded model's lowest geometric point
   * (`groundY`, resolved in `resolveGroundY`), a presentation-only reference —
   * never a redefinition of IFC level/elevation semantics. Below-plane
   * geometry stays visible and unclipped: the grid is a thin, transparent,
   * non-depth-writing overlay, not a clip plane.
   */
  private createBasePlane(): void {
    this.removeBasePlane();
    if (!this.world || !this.model) return;
    try {
      const box = this.model.box;
      const size = new THREE.Vector3();
      if (box) box.getSize(size);
      const extent = Math.max(size.x, size.z, 10) * 2;

      const grid = new THREE.GridHelper(extent, Math.max(10, Math.round(extent / 2)));
      const mat = grid.material as THREE.Material & { color?: THREE.Color; opacity?: number };
      if (mat.color) mat.color.copy(PLANE_COLOR);
      mat.opacity = PLANE_OPACITY;
      mat.transparent = true;
      mat.depthWrite = false; // never occlude underground geometry
      grid.position.y = this.groundY;
      grid.renderOrder = -1;

      this.world.scene.three.add(grid);
      this.basePlane = grid;
    } catch {
      // the plane is decorative; never fail a load over it
    }
  }

  private removeBasePlane(): void {
    if (!this.basePlane) return;
    try {
      this.basePlane.removeFromParent();
      const grid = this.basePlane as THREE.GridHelper;
      grid.geometry?.dispose();
      (grid.material as THREE.Material)?.dispose();
    } catch {
      // ignore
    }
    this.basePlane = null;
  }

  hasBasePlane(): boolean {
    return this.basePlane !== null;
  }

  /** The decorative grid is hidden while a plan is shown (task28 §4.2). */
  private setBasePlaneVisible(visible: boolean): void {
    if (this.basePlane) this.basePlane.visible = visible;
  }

  isBasePlaneVisible(): boolean {
    return this.basePlane?.visible ?? false;
  }

  // -------------------------------------------------------------------------
  // Floor-plan mode (task28 §3, §4)
  // -------------------------------------------------------------------------

  isPlanMode(): boolean {
    return this.planBandIndex !== null;
  }

  getPlanBandIndex(): number | null {
    return this.planBandIndex;
  }

  /** The active plan range in SCENE Y, for tests/diagnostics. */
  getPlanRange(): { cut: number; lower: number } | null {
    return this.planRange ? { ...this.planRange } : null;
  }

  /** Bands as mapped into this artifact's scene space, for tests/diagnostics. */
  getSceneBands(): SceneBand[] {
    return this.sceneBands.map((b) => ({ ...b }));
  }

  hasPlanSection(): boolean {
    return this.planSection !== null;
  }

  /**
   * Adopt the backend's logical floor contract and map each band into THIS
   * artifact's scene space (task28 §3), returning what the floor buttons may
   * offer.
   *
   * Scene heights are read from the loaded artifact only: each constituent
   * storey's own `Elevation` attribute plus the model's public coordinate
   * height — the same pair `Views.createFromIfcStoreys` adds — pushed through
   * the model object's own world matrix so the result is comparable with
   * `model.box`, which Fragments already reports in world space. The contract's
   * stored `min_elevation`/`max_elevation` are never used as scene Y values, and
   * no model-specific offset is introduced.
   *
   * A band whose storeys cannot resolve a finite scene elevation stays visible
   * but disabled with a concise reason — never a guessed plane.
   */
  async setFloorContract(floors: FloorContractBand[]): Promise<FloorPlanState[]> {
    this.sceneBands = [];
    if (!this.model || floors.length === 0) {
      return floors.map((f) => ({
        bandIndex: f.band_index,
        label: f.label,
        enabled: false,
        reason: "The 3D model is not ready yet.",
      }));
    }

    const elevations = await this.readStoreySceneElevations(floors);
    this.sceneBands = [...floors]
      .sort((a, b) => a.band_index - b.band_index)
      .map((band) => {
        const ys = band.storey_global_ids
          .map((gid) => elevations.get(gid))
          .filter((y): y is number => typeof y === "number" && Number.isFinite(y));
        return {
          bandIndex: band.band_index,
          label: band.label,
          minSceneY: ys.length ? Math.min(...ys) : Number.NaN,
          maxSceneY: ys.length ? Math.max(...ys) : Number.NaN,
          // Every constituent storey must resolve; a partially resolved band
          // would silently cut at the wrong height (task28 §3).
          resolved: ys.length === band.storey_global_ids.length && ys.length > 0,
        };
      });

    const min = this.modelMinSceneY();
    return this.sceneBands.map((band) => ({
      bandIndex: band.bandIndex,
      label: band.label,
      ...planAvailability(this.sceneBands, band.bandIndex, min),
    }));
  }

  /**
   * Artifact-native scene Y per storey GlobalId.
   *
   * Two bounded worker round trips for the whole contract (one id resolution,
   * one attribute read) — never one per floor, and never a scan of the model.
   */
  private async readStoreySceneElevations(
    floors: FloorContractBand[],
  ): Promise<Map<string, number>> {
    const out = new Map<string, number>();
    if (!this.model) return out;
    const gids = [...new Set(floors.flatMap((f) => f.storey_global_ids))];
    if (gids.length === 0) return out;
    try {
      const localIds = await this.model.getLocalIdsByGuids(gids);
      const known: { gid: string; localId: number }[] = [];
      localIds.forEach((id, i) => {
        if (typeof id === "number") known.push({ gid: gids[i]!, localId: id });
      });
      if (known.length === 0) return out;

      const data = await this.model.getItemsData(
        known.map((k) => k.localId),
        { attributesDefault: false, attributes: ["Elevation"] },
      );
      const [, coordinateHeight] = await this.model.getCoordinates();
      if (!Number.isFinite(coordinateHeight)) return out;

      // The stored elevation + coordinate height is in the model object's LOCAL
      // space; the model's own world matrix carries it into scene space.
      const toScene = this.modelLocalToSceneY();
      known.forEach((k, i) => {
        const attr = data[i]?.Elevation as { value?: unknown } | undefined;
        const raw = attr?.value;
        if (typeof raw !== "number" || !Number.isFinite(raw)) return;
        out.set(k.gid, toScene(storeyLocalY(raw, coordinateHeight)));
      });
    } catch {
      // An unreadable artifact leaves every band unresolved, which disables the
      // affected floors rather than placing a guessed plane.
    }
    return out;
  }

  /** Local -> scene Y through the loaded model object's own world matrix. */
  private modelLocalToSceneY(): (localY: number) => number {
    const object = this.model?.object;
    if (!object) return (y) => y;
    try {
      object.updateWorldMatrix(true, false);
      const matrix = object.matrixWorld;
      const point = new THREE.Vector3();
      return (localY: number) => point.set(0, localY, 0).applyMatrix4(matrix).y;
    } catch {
      return (y) => y;
    }
  }

  /**
   * The loaded model's finite geometric minimum in scene Y — the lowest logical
   * band's lower boundary (task28 §3.2). Never a floor elevation.
   */
  private modelMinSceneY(): number {
    try {
      const box = this.model?.box;
      if (box && !box.isEmpty() && Number.isFinite(box.min.y)) return box.min.y;
    } catch {
      // fall through
    }
    return Number.NaN;
  }

  /**
   * Switch the existing viewer into a top-down orthographic plan of one logical
   * floor (task28 §1.2).
   *
   * Same components, same world, same canvas, same Fragments model: only the
   * camera in use and two clipping planes change. Selection, query roles, chat,
   * and panels are untouched — this issues no query and calls no LLM.
   */
  async enterPlanMode(bandIndex: number): Promise<PlanModeResult> {
    const world = this.world;
    const components = this.components;
    if (!world || !components || !this.model) {
      return { ok: false, reason: "The 3D model is not ready yet." };
    }

    const range = resolvePlanRange(this.sceneBands, bandIndex, this.modelMinSceneY());
    if (!range.ok) return { ok: false, reason: range.reason };

    // Only the FIRST departure from 3D captures the pose to return to, so
    // switching floor-to-floor never overwrites it (task28 §1.2).
    if (this.planBandIndex === null) this.savePerspectivePose();

    const token = ++this.planToken;
    this.disposePlanSection();
    this.closePlanView();

    try {
      const views = this.ensureViews(world);
      const plane = new THREE.Plane(new THREE.Vector3(0, -1, 0), range.range.cut);
      const view = views.createFromPlane(plane, { id: `floor-plan-${token}`, world });
      // The View's far plane sits `range` below the cut, which is exactly the
      // lower boundary this task requires — so lower floors cannot appear
      // through openings (task28 §3.2).
      view.range = range.range.cut - range.range.lower;
      views.open(view.id);
      this.planView = view;
      this.planBandIndex = bandIndex;
      this.planRange = { cut: range.range.cut, lower: range.range.lower };
    } catch {
      this.closePlanView();
      this.planBandIndex = null;
      this.planRange = null;
      return { ok: false, reason: "This floor plan could not be opened for this model." };
    }

    this.configurePlanControls(this.planView.camera);
    // Fragments' own LOD/culling must follow the camera actually rendering.
    try {
      this.model.useCamera(this.planView.camera.three as THREE.PerspectiveCamera);
    } catch {
      // best-effort; a stale LOD camera degrades detail, never correctness
    }
    this.setBasePlaneVisible(false);
    await this.suspendSizePolicy();
    this.applyViewOffset();
    await this.fitPlanFootprint(range.range);
    await this.updateFragments();

    // Contours are requested for the ACTIVE floor only, never precomputed for
    // every floor at load, and a stale result can never replace a newer one.
    const contoured = await this.buildPlanSection(this.planView.plane, token);
    if (!contoured && token === this.planToken) {
      return {
        ok: true,
        reason: "Cut outlines aren't available for this floor; showing the clipped model.",
      };
    }
    return { ok: true };
  }

  /**
   * Return to the normal perspective 3D view (task28 §1.2).
   *
   * Removes both clipping boundaries and every plan-only overlay, then restores
   * the exact pose and target that existed before plan mode. Remains available
   * even after a plan-rendering failure (task28 §6).
   */
  async exitPlanMode(): Promise<void> {
    const wasPlan = this.planBandIndex !== null || this.planView !== null;
    this.planToken++; // retire any in-flight section for the outgoing floor
    this.disposePlanSection();
    this.closePlanView();
    this.planBandIndex = null;
    this.planRange = null;
    if (!wasPlan) return;

    // Fragments LOD follows the perspective camera again.
    try {
      const cam = this.world?.camera.three;
      if (cam) this.model?.useCamera(cam as THREE.PerspectiveCamera);
    } catch {
      // best-effort
    }
    this.setBasePlaneVisible(true);
    // 50 mm lens, desktop control mapping, and panel-aware centering are
    // re-asserted on the restored perspective camera before the pose, so the
    // projection is already correct when the camera lands.
    this.applyLens();
    this.configureControls();
    this.applyViewOffset();
    this.restorePerspectivePose();
    await this.resumeSizePolicy();
    await this.updateFragments();
  }

  private ensureViews(world: ViewerWorld): OBC.Views {
    if (!this.views) {
      const views = this.components!.get(OBC.Views);
      // This adapter saves and restores the pose itself, so the component's own
      // camera snapshot is turned off rather than left to fight with it.
      views.restoreCameraOnClose = false;
      this.views = views;
    }
    this.views.world = world;
    return this.views;
  }

  private closePlanView(): void {
    const view = this.planView;
    this.planView = null;
    if (!view || !this.views) return;
    try {
      // Deleting the entry closes it if open and disposes its camera, helpers,
      // and clipping planes — the component's documented lifecycle.
      this.views.list.delete(view.id);
    } catch {
      try {
        this.views.close(view.id);
      } catch {
        // never fail a return to 3D over cleanup
      }
    }
  }

  private savePerspectivePose(): void {
    const controls = this.world?.camera.controls;
    if (!controls) return;
    try {
      const position = new THREE.Vector3();
      const target = new THREE.Vector3();
      controls.getPosition(position);
      controls.getTarget(target);
      this.savedPose = { position, target };
    } catch {
      this.savedPose = null;
    }
  }

  private restorePerspectivePose(): void {
    const pose = this.savedPose;
    this.savedPose = null;
    const controls = this.world?.camera.controls;
    if (!pose || !controls) return;
    try {
      const { position: p, target: t } = pose;
      controls.setLookAt(p.x, p.y, p.z, t.x, t.y, t.z, false);
    } catch {
      // a failed restore must never block the return to 3D
    }
  }

  /** The saved perspective pose, for tests (task28 §8.2). Cloned — a caller
   *  must not be able to mutate the pose the viewer will restore. */
  getSavedPose(): { position: THREE.Vector3; target: THREE.Vector3 } | null {
    if (!this.savedPose) return null;
    return {
      position: this.savedPose.position.clone(),
      target: this.savedPose.target.clone(),
    };
  }

  /**
   * Frame the model footprint, clipped to the active range, inside the currently
   * unobstructed viewer region — the same `fitBox` path (and therefore the same
   * view-offset centering) every other fit uses.
   */
  private async fitPlanFootprint(range: { cut: number; lower: number }): Promise<void> {
    const box = this.model?.box;
    if (!box || box.isEmpty()) return;
    const footprint = box.clone();
    footprint.min.y = Math.max(footprint.min.y, range.lower);
    footprint.max.y = Math.min(footprint.max.y, range.cut);
    if (footprint.min.y > footprint.max.y) {
      footprint.min.y = range.lower;
      footprint.max.y = range.cut;
    }
    await this.fitBox(footprint);
  }

  /**
   * Real cut geometry at the upper plane, via the loaded model's public
   * `getSection` (task28 §4.2).
   *
   * The heavy work happens in the existing Fragments worker, for the ACTIVE
   * floor only. Nothing is fabricated: no door swings, no window/furniture/
   * stair symbols, no room tags, dimensions, annotations, north arrows, or
   * scale bars — only the intersection of the plane with geometry the prepared
   * artifact actually contains.
   *
   * Up to three disjoint layers, so the established semantic roles survive into
   * the plan (task28 §4.2, §5; task31 §5.1): non-wall geometry in plan ink,
   * then wall cuts in black, then the query-primary cut in the existing
   * blueprint blue drawn over both. The three id sets do not overlap — a
   * query-primary wall is in the blue layer and in neither other layer — so
   * black can never cover or tint a blue result, and no layer restates another
   * at partial alpha.
   *
   * The plane is transformed into the model object's local space before the
   * call (and the results mounted UNDER that object) because `getSection`
   * computes and returns geometry in the model's own space, exactly as
   * Fragments does for its own clipping planes.
   */
  private async buildPlanSection(worldPlane: THREE.Plane, token: number): Promise<boolean> {
    const model = this.model;
    if (!model) return false;
    try {
      const inverse = new THREE.Matrix4().copy(model.object.matrixWorld).invert();
      const localPlane = worldPlane.clone().applyMatrix4(inverse);

      const group = new THREE.Group();
      // Off the plane that produced it, so the GPU's coplanar clip test cannot
      // stipple the contour away (see PLAN.cutInsetM).
      group.position.y = -PLAN.cutInsetM;

      // Wall cuts are drawn as their own black layer (task31 §5.1), so the
      // walls are withheld from the base layer rather than being over-painted:
      // an over-paint would blend the base poché through the black at the
      // established fill alpha, which is not the accepted colour. With no wall
      // classification (or no resolvable id universe) the split degrades to the
      // previous single base layer — truthful, just without black walls.
      const split = this.planWallSplit();
      const base = await this.sectionLayer(localPlane, split?.others, {
        color: PLAN_CUT_COLOR,
        contourOpacity: PLAN_CUT_OPACITY,
        fillColor: PLAN_FILL_COLOR,
        fillOpacity: PLAN_FILL_OPACITY,
        fillRenderOrder: PLAN.baseFillRenderOrder,
        contourRenderOrder: PLAN.baseContourRenderOrder,
      });
      if (token !== this.planToken) {
        base.forEach(disposeDrawable);
        return false;
      }
      base.forEach((object) => group.add(object));

      if (split && split.walls.length > 0) {
        const walls = await this.sectionLayer(localPlane, split.walls, {
          // Same colour for fill and contour — the poché convention for cut
          // masonry. The fill keeps the established plan-fill alpha; only the
          // colour changed.
          color: PLAN_WALL_CUT_COLOR,
          contourOpacity: PLAN_CUT_OPACITY,
          fillColor: PLAN_WALL_CUT_COLOR,
          fillOpacity: PLAN_FILL_OPACITY,
          fillRenderOrder: PLAN.wallFillRenderOrder,
          contourRenderOrder: PLAN.wallContourRenderOrder,
        });
        if (token !== this.planToken) {
          base.forEach(disposeDrawable);
          walls.forEach(disposeDrawable);
          return false;
        }
        walls.forEach((object) => group.add(object));
      }

      if (this.rolesActive && this.queryPrimary.length > 0) {
        const primary = await this.sectionLayer(localPlane, this.queryPrimary, {
          color: PRIMARY_MATERIAL.color as THREE.Color,
          contourOpacity: 1,
          fillColor: PRIMARY_MATERIAL.color as THREE.Color,
          fillOpacity: PLAN_FILL_OPACITY,
          fillRenderOrder: PLAN.primaryFillRenderOrder,
          contourRenderOrder: PLAN.primaryContourRenderOrder,
        });
        if (token !== this.planToken) {
          base.forEach(disposeDrawable);
          primary.forEach(disposeDrawable);
          return false;
        }
        primary.forEach((object) => group.add(object));
      }

      if (group.children.length === 0) return false;
      if (token !== this.planToken) {
        group.children.slice().forEach(disposeDrawable);
        return false;
      }
      model.object.add(group);
      this.planSection = { group };
      return true;
    } catch {
      // Section generation is a visual layer: on failure the truthful clipped
      // orthographic view remains, and no other floor's contours are shown.
      return false;
    }
  }

  /**
   * The plan cut's disjoint id sets: walls to draw black, everything else to
   * draw in the existing plan ink (task31 §5.1).
   *
   * Membership is the `classifyGeometry` wall set already computed at load,
   * which is exactly the viewer's one wall-class definition (`geometryRole`
   * over `IfcWall`/`IfcWallStandardCase`/`IfcWallElementedCase`, also exposed
   * as `isWallClass`) — no IFC re-read, no new query, no change to wall
   * membership itself. Query-primary objects are withheld from
   * BOTH sets: they are drawn by the blue primary layer, which must not be
   * blended with black underneath it.
   *
   * Returns `null` when the model's id universe or its wall classification is
   * unavailable, in which case the caller keeps the previous single
   * everything-in-plan-ink layer rather than guessing a split.
   */
  private planWallSplit(): { walls: number[]; others: number[] } | null {
    if (this.allLocalIds.length === 0 || this.classification.wall.length === 0) return null;
    const wallIds = new Set(this.classification.wall);
    const primaries = this.rolesActive ? this.queryPrimarySet : new Set<number>();
    const walls: number[] = [];
    const others: number[] = [];
    for (const id of this.allLocalIds) {
      if (primaries.has(id)) continue;
      if (wallIds.has(id)) walls.push(id);
      else others.push(id);
    }
    return { walls, others };
  }

  /** One `getSection` call turned into a contour + fill pair, or an empty list. */
  private async sectionLayer(
    localPlane: THREE.Plane,
    localIds: number[] | undefined,
    style: {
      color: THREE.Color;
      contourOpacity: number;
      fillColor: THREE.Color;
      fillOpacity: number;
      fillRenderOrder: number;
      contourRenderOrder: number;
    },
  ): Promise<THREE.Object3D[]> {
    const model = this.model;
    if (!model) return [];
    const section = await model.getSection(localPlane, localIds);
    const vertexCount = section?.index ?? 0;
    if (!section?.buffer || vertexCount <= 0) return [];

    // Copy out of the worker's fixed 600k-float scratch buffer so the overlay
    // retains only the vertices it actually uses (task28 §4.3).
    const positions = new Float32Array(section.buffer.subarray(0, vertexCount * 3));
    const out: THREE.Object3D[] = [];

    const indices = section.fillsIndices ?? [];
    if (indices.length >= 3) {
      const fillGeometry = new THREE.BufferGeometry();
      fillGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      fillGeometry.setIndex(indices);
      const fill = new THREE.Mesh(
        fillGeometry,
        new THREE.MeshBasicMaterial({
          color: style.fillColor.clone(),
          opacity: style.fillOpacity,
          transparent: true,
          side: THREE.DoubleSide,
          depthWrite: false,
        }),
      );
      fill.frustumCulled = false;
      fill.renderOrder = style.fillRenderOrder;
      out.push(fill);
    }

    const contourGeometry = new THREE.BufferGeometry();
    contourGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const contour = new THREE.LineSegments(
      contourGeometry,
      new THREE.LineBasicMaterial({
        color: style.color.clone(),
        opacity: style.contourOpacity,
        transparent: style.contourOpacity < 1,
        depthWrite: false,
      }),
    );
    contour.frustumCulled = false;
    contour.renderOrder = style.contourRenderOrder;
    out.push(contour);
    return out;
  }

  /**
   * Rebuild the active floor's cut layers after a highlight change, so query
   * and selection roles stay synchronized while plan mode is active (task28
   * §1.3). A no-op outside plan mode.
   */
  private async refreshPlanSection(): Promise<void> {
    const view = this.planView;
    if (!view || this.planBandIndex === null) return;
    const token = ++this.planToken;
    this.disposePlanSection();
    await this.buildPlanSection(view.plane, token);
  }

  private disposePlanSection(): void {
    const section = this.planSection;
    this.planSection = null;
    if (!section) return;
    try {
      section.group.children.slice().forEach(disposeDrawable);
      section.group.removeFromParent();
    } catch {
      // never fail a floor switch or a return to 3D over cleanup
    }
  }

  /**
   * Suspend the perspective-only projected-size policy and make every object it
   * hid visible again, so the plan is not missing geometry (task28 §4.3).
   */
  private async suspendSizePolicy(): Promise<void> {
    if (this.sizePolicySuspended) return;
    this.sizePolicySuspended = true;
    if (!this.sizePolicyActive || !this.model) return;
    const restore = this.sizePolicy.restoreAll();
    if (restore.length === 0) return;
    try {
      await asPolicyModel(this.model).setVisible(restore, true);
      this.recolorEdges();
    } catch {
      // visibility failures must never crash the viewer
    }
  }

  /** Re-evaluate the policy against the restored perspective camera. */
  private async resumeSizePolicy(): Promise<void> {
    if (!this.sizePolicySuspended) return;
    this.sizePolicySuspended = false;
    await this.applyProjectedSizePolicy();
  }

  isSizePolicySuspended(): boolean {
    return this.sizePolicySuspended;
  }

  // -------------------------------------------------------------------------
  // Projected-size policy (task23 issue 2)
  // -------------------------------------------------------------------------

  /**
   * An object that must stay visible regardless of size or category: every
   * query-primary result and every manual selection. The rendering optimization
   * must never drop or broaden the identities the query pipeline returned.
   */
  private isSizeExempt = (localId: number): boolean =>
    this.queryPrimarySet.has(localId) || this.manualLocalIds().has(localId);

  private manualLocalIds(): Set<number> {
    return new Set(this.manual.values());
  }

  /**
   * Re-evaluate projected sizes and apply ONLY the visibility changes.
   *
   * Cheap by construction: classification and bounding volumes are cached at
   * load, so this is a numeric pass over cached centers/radii plus one bounded
   * `setVisible` call per direction. It never re-reads IFC data, never rebuilds
   * geometry, and never calls the backend.
   *
   * Does NOT call `updateFragments()` itself — callers batch that, so a rest
   * event performs exactly one Fragments refresh.
   */
  private async applyProjectedSizePolicy(): Promise<void> {
    if (!this.sizePolicyActive || !this.model || !this.world) return;
    // Suspended for floor-plan mode (task28 §4.3): the projected-size rule is
    // derived from a perspective FOV and must never run against an orthographic
    // camera as though it were perspective. `enterPlanMode` restored every
    // hidden object so nothing is missing from the plan, and `exitPlanMode`
    // re-evaluates against the restored perspective camera.
    if (this.sizePolicySuspended) return;
    const camera = this.world.camera.three as THREE.PerspectiveCamera;
    if (!camera?.isPerspectiveCamera) return;
    const dom = this.rendererDom();
    const height = dom?.clientHeight ?? 0;
    if (height <= 0) return;

    const delta = this.sizePolicy.evaluate(camera, height, this.isSizeExempt);
    if (delta.hide.length === 0 && delta.show.length === 0) return;

    try {
      const model = asPolicyModel(this.model);
      if (delta.hide.length) await model.setVisible(delta.hide, false);
      if (delta.show.length) await model.setVisible(delta.show, true);
      // Hidden faces must not leave floating edges behind.
      this.recolorEdges();
    } catch {
      // A visibility failure must never crash or freeze the viewer.
    }
  }

  /** True when an object is currently hidden by the projected-size policy. */
  isHiddenBySize(localId: number): boolean {
    return this.sizePolicyActive && this.sizePolicy.isHidden(localId);
  }

  /** Diagnostics/tests: how many objects the policy currently hides. */
  getSizeHiddenCount(): number {
    return this.sizePolicyActive ? this.sizePolicy.hiddenIds().length : 0;
  }

  /** Diagnostics/tests: objects retained at any projected size. */
  getSizeRetainedCount(): number {
    return this.sizePolicy.getRetainedCount();
  }

  isSizePolicyActive(): boolean {
    return this.sizePolicyActive;
  }

  // -------------------------------------------------------------------------
  // Fragments LOD/visibility update
  // -------------------------------------------------------------------------

  /**
   * Refresh the Fragments model's LOD/visibility for the current camera. Called
   * on model load, on camera rest, and after a highlight/material change — the
   * same rest-and-load cadence the viewer used before the Task 18 adaptive
   * throttling was introduced (spec_v006 §28). Never called on a per-frame or
   * per-motion tick, so it cannot introduce interaction-time worker stalls.
   */
  private async updateFragments(): Promise<void> {
    if (!this.fragments) return;
    try {
      await this.fragments.core.update(true);
    } catch {
      // an update failure must never crash the viewer
    }
  }

  // -------------------------------------------------------------------------
  // Framing
  // -------------------------------------------------------------------------

  resize(): void {
    try {
      this.world?.renderer?.resize(undefined);
      this.world?.camera.updateAspect();
    } catch {
      // resize can fire before the renderer exists; ignore
    }
    // Kept out of the try above: `updateAspect` recomputes the projection from
    // the camera's fov, so the lens must be re-applied even if the renderer
    // resize failed — otherwise a transient error silently drops the 50 mm
    // equivalence for the rest of the session.
    this.applyLens();
    // Canvas dimensions changed — the view-offset centering math must use the
    // fresh size, without moving the camera (task19 §2).
    this.applyViewOffset();
    // Projected size is measured in CSS px, so a viewport change alters it even
    // though the camera did not move (task23 issue 2).
    void this.applyProjectedSizePolicy().then(() => this.updateFragments());
  }

  async fitAll(): Promise<void> {
    if (!this.model || !this.world) return;
    try {
      const box = this.model.box;
      if (box) await this.fitBox(box.clone());
    } catch {
      // fit is best-effort
    }
  }

  private async fitBox(box: THREE.Box3): Promise<void> {
    if (!this.world) return;
    const size = new THREE.Vector3();
    box.getSize(size);
    const center = new THREE.Vector3();
    box.getCenter(center);
    // grow for moderate framing + floor so small items don't fill the viewport
    const half = new THREE.Vector3(
      Math.max((size.x * VIEWER_CAMERA.fitExpand) / 2, VIEWER_CAMERA.minFitSize),
      Math.max((size.y * VIEWER_CAMERA.fitExpand) / 2, VIEWER_CAMERA.minFitSize),
      Math.max((size.z * VIEWER_CAMERA.fitExpand) / 2, VIEWER_CAMERA.minFitSize),
    );
    const framed = new THREE.Box3(center.clone().sub(half), center.clone().add(half));
    // Sets camera.aspect from the current unobstructed left region BEFORE
    // fitToBox reads it synchronously to compute fit distance (task19 §2) —
    // every fit/focus call (fitAll, query-result fit, citation fit, component
    // fit) funnels through this one method, so all share the same effective
    // viewport logic.
    this.applyViewOffset();
    await this.world.camera.controls.fitToBox(framed, true);
  }

  async fitToGuids(guids: string[]): Promise<RoleApplyResult> {
    if (!this.model) return { missing: guids };
    const { localIds, missing } = await this.resolveGuids(guids);
    if (localIds.length === 0) return { missing };
    await this.fitToLocalIds(localIds);
    return { missing };
  }

  private async fitToLocalIds(localIds: number[]): Promise<void> {
    if (!this.model) return;
    try {
      const box = await this.model.getMergedBox(localIds);
      await this.fitBox(box.clone());
    } catch {
      // ignore
    }
  }

  // -------------------------------------------------------------------------
  // Highlighting
  // -------------------------------------------------------------------------

  async applyQueryRoles(primaryGuids: string[], contextGuids: string[]): Promise<RoleApplyResult> {
    if (!this.model) return { missing: [...primaryGuids, ...contextGuids] };
    const primary = await this.resolveGuids(primaryGuids);
    // Context evidence can inform the answer but is intentionally not colored.
    void contextGuids;
    this.queryPrimary = primary.localIds;
    this.queryPrimarySet = new Set(primary.localIds);
    this.rolesActive = primary.localIds.length > 0;
    await this.renderHighlights();
    if (primary.localIds.length > 0) await this.fitToLocalIds(primary.localIds);
    return { missing: primary.missing };
  }

  async clearQueryRoles(): Promise<void> {
    this.queryPrimary = [];
    this.queryPrimarySet = new Set();
    this.rolesActive = false;
    await this.renderHighlights();
  }

  private async resolveGuids(guids: string[]): Promise<{ localIds: number[]; missing: string[] }> {
    if (!this.model || guids.length === 0) return { localIds: [], missing: [] };
    const ids = await this.model.getLocalIdsByGuids(guids);
    const localIds: number[] = [];
    const missing: string[] = [];
    ids.forEach((id, i) => {
      if (typeof id === "number") localIds.push(id);
      else missing.push(guids[i]!);
    });
    return { localIds, missing };
  }

  /**
   * Single source of truth for what is drawn in what color.
   *
   * With query roles active, non-results are dimmed so the matches carry the
   * only saturated color on screen; manually focused results stay opaque blue
   * while the remaining primaries drop to translucent blue
   * (task15 §3). With roles cleared, the semantic roof/wall/other base colors
   * are restored — NOT one uniform material (task14 §1) — and manual picks are
   * drawn blue.
   */
  private async renderHighlights(): Promise<void> {
    if (!this.model || !this.fragments) return;
    try {
      await this.model.resetHighlight();
      if (this.rolesActive) {
        await this.model.highlight(undefined, DIM_MATERIAL);
        await this.paintPrimaries();
      } else {
        await this.applyBaseColors();
        const manualIds = [...this.manual.values()];
        if (manualIds.length) await this.model.highlight(manualIds, MANUAL_MATERIAL);
      }
      this.recolorEdges();
      // Highlighting an otherwise filtered object must make it visible, and
      // clearing the highlight must immediately reapply its size/category state
      // (task23 issue 2). Runs before the single Fragments refresh below.
      await this.applyProjectedSizePolicy();
      // While a plan is shown, the cut layers carry the same roles, so they are
      // rebuilt for the new highlight rather than left describing the previous
      // one (task28 §1.3). Never returns to perspective mode.
      if (this.isPlanMode()) await this.refreshPlanSection();
      await this.updateFragments();
    } catch {
      // a highlight failure must never crash the viewer (spec_v006 §11.3, §15)
    }
  }

  /**
   * Primary results while roles are active (task15 §3): with one or more
   * results manually focused, focused stay opaque `PRIMARY` and the rest drop
   * to `PRIMARY_UNFOCUSED`; removing the last focused selection restores every
   * primary to opaque blue (the no-focus branch).
   */
  private async paintPrimaries(): Promise<void> {
    if (!this.model || this.queryPrimary.length === 0) return;
    const focused = new Set(
      [...this.manual.values()].filter((id) => this.queryPrimarySet.has(id)),
    );
    if (focused.size === 0) {
      await this.model.highlight(this.queryPrimary, PRIMARY_MATERIAL);
      return;
    }
    const unfocused = this.queryPrimary.filter((id) => !focused.has(id));
    if (unfocused.length) await this.model.highlight(unfocused, PRIMARY_UNFOCUSED_MATERIAL);
    await this.model.highlight([...focused], PRIMARY_MATERIAL);
  }

  // -------------------------------------------------------------------------
  // Isolated-preview support (task14 §5)
  // -------------------------------------------------------------------------

  /**
   * Extract just the selected instance's geometry from the ALREADY-LOADED
   * model, plus the base role it is drawn with.
   *
   * This is the lightweight-subset strategy the preview needs: it reuses the
   * loaded artifact's own geometry buffers rather than re-downloading or
   * re-parsing it, and never duplicates the whole model in memory.
   */
  async extractItemGeometry(guid: string): Promise<{
    meshes: FRAGS.MeshData[];
    role: GeometryRole;
  } | null> {
    if (!this.model) return null;
    try {
      const [localId] = await this.model.getLocalIdsByGuids([guid]);
      if (typeof localId !== "number") return null;
      const perItem = await this.model.getItemsGeometry([localId]);
      const meshes = (perItem?.[0] ?? []).filter((m) => m?.positions && m.positions.length > 0);
      if (meshes.length === 0) return null;
      return { meshes, role: this.roleOfLocalId(localId) };
    } catch {
      return null;
    }
  }

  /** The base color role a loaded item is drawn with, from the classification pass. */
  private roleOfLocalId(localId: number): GeometryRole {
    if (this.classification.roof.includes(localId)) return "roof";
    if (this.classification.wall.includes(localId)) return "wall";
    return "other";
  }

  /** Semantic base pass: everything "other", then walls, then roofs over it. */
  private async applyBaseColors(): Promise<void> {
    if (!this.model) return;
    await this.model.highlight(undefined, BASE_MATERIALS.other);
    if (this.classification.wall.length) {
      await this.model.highlight(this.classification.wall, BASE_MATERIALS.wall);
    }
    if (this.classification.roof.length) {
      await this.model.highlight(this.classification.roof, BASE_MATERIALS.roof);
    }
  }

  // -------------------------------------------------------------------------
  // Edge overlay (task15 §2)
  // -------------------------------------------------------------------------

  hasEdgeOverlay(): boolean {
    return this.edgeOverlay?.isBuilt() ?? false;
  }

  /**
   * The edge role an entity currently renders with — mirrors the face layering
   * in `renderHighlights`/`paintPrimaries` exactly, so edges always follow the
   * entity's current face color.
   */
  edgeRoleOf(localId: number): EdgeRole {
    // A face hidden by the projected-size policy must not leave a wireframe
    // behind (task23 issue 2). Checked first because it overrides every colour
    // role — but never applies to highlighted/selected objects, which the
    // policy exempts from hiding in the first place.
    if (this.isHiddenBySize(localId)) return "hidden";
    const manualIds = [...this.manual.values()];
    if (this.rolesActive) {
      if (this.queryPrimarySet.has(localId)) {
        const anyFocused = manualIds.some((id) => this.queryPrimarySet.has(id));
        return !anyFocused || manualIds.includes(localId) ? "primary" : "primaryUnfocused";
      }
      return "dim";
    }
    return manualIds.includes(localId) ? "manual" : this.roleOfLocalId(localId);
  }

  private recolorEdges(): void {
    if (!this.edgeOverlay?.isBuilt()) return;
    this.edgeOverlay.recolor((localId) => this.edgeRoleOf(localId));
  }

  dispose(): void {
    this.disposers.forEach((d) => {
      try {
        d();
      } catch {
        // ignore
      }
    });
    this.disposers = [];
    // Plan-only cameras, clipping planes, section meshes, and materials go with
    // the rest of the imperative layer (task28 §4.3).
    this.planToken++;
    this.disposePlanSection();
    this.closePlanView();
    this.planBandIndex = null;
    this.planRange = null;
    this.sceneBands = [];
    this.savedPose = null;
    this.sizePolicySuspended = false;
    this.views = null;
    this.edgeToken++;
    this.edgeOverlay?.dispose();
    this.edgeOverlay = null;
    this.allLocalIds = [];
    this.removeBasePlane();
    try {
      this.components?.dispose();
    } catch {
      // ignore
    }
    this.components = null;
    this.world = null;
    this.fragments = null;
    this.model = null;
    this.modelId = null;
    this.manual.clear();
    this.classification = { roof: [], wall: [] };
  }
}
