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
import { type Profile, detectProfile } from "./profileDetection";
import { ProjectedSizePolicy, asPolicyModel } from "./ProjectedSizePolicy";
import {
  BASE_MATERIALS,
  DIM_MATERIAL,
  EDGES,
  MANUAL_MATERIAL,
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
const ACTION = { NONE: 0, ROTATE: 1, TRUCK: 2, DOLLY: 16 } as const;

export interface ViewerCallbacks {
  onManualSelectionChange?: (guids: string[]) => void;
  onSelectionLimitReached?: () => void;
}

export interface RoleApplyResult {
  missing: string[];
}

/** Classified base-color membership for the loaded model (task14 §1). */
interface BaseClassification {
  roof: number[];
  wall: number[];
}

type ViewerWorld = OBC.SimpleWorld<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>;

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

  constructor(maxSelection = 5) {
    this.maxSelection = maxSelection;
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
   */
  private applyViewOffset(): void {
    const cam = this.world?.camera.three as THREE.PerspectiveCamera | undefined;
    const dom = this.rendererDom();
    if (!cam || !cam.isPerspectiveCamera || !dom) return;
    const canvasW = dom.clientWidth || 1;
    const canvasH = dom.clientHeight || 1;
    const minLeftWidth = canvasW * VIEWER_CAMERA.minEffectiveWidthFraction;
    const leftWidth = Math.max(canvasW - this.rightObstructionPx, minLeftWidth);
    if (leftWidth >= canvasW - 0.5) {
      cam.clearViewOffset();
      return;
    }
    cam.setViewOffset(leftWidth, canvasH, 0, 0, canvasW, canvasH);
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
      const overlay = new EdgeOverlay();
      this.edgeOverlay = overlay;
      const thresholdDeg =
        profile === "large-model" ? EDGES.thresholdAngleDeg.largeModel : EDGES.thresholdAngleDeg.balanced;
      void overlay.build(model, model.object, { thresholdDeg, localIds }).then((built) => {
        // Ignore a build that finished after the model changed underneath it.
        if (built && this.edgeOverlay === overlay) {
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
    this.manual.clear();
    this.queryPrimary = [];
    this.queryPrimarySet = new Set();
    this.rolesActive = false;
    this.classification = { roof: [], wall: [] };
    this.sizePolicy.reset();
    this.sizePolicyActive = false;
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
    this.edgeOverlay?.dispose();
    this.edgeOverlay = null;
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
