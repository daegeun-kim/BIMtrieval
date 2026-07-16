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
  BASE_MATERIALS,
  CONTEXT_MATERIAL,
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
  private queryContext: number[] = [];
  // Resolved local-id sets for picking eligibility and edge recoloring
  // (task15 §3): membership checks never call the backend or an LLM.
  private queryPrimarySet = new Set<number>();
  private queryContextSet = new Set<number>();
  private rolesActive = false;
  private selectionEnabled = true;
  private edgeOverlay: EdgeOverlay | null = null;

  private pointerDown: { x: number; y: number; button: number } | null = null;
  private readonly maxSelection: number;
  private callbacks: ViewerCallbacks = {};

  private basePlane: THREE.Object3D | null = null;
  /** Scene-space Y of IFC/world elevation 0 (task14 §2). */
  private groundY = 0;
  private classification: BaseClassification = { roof: [], wall: [] };
  private disposers: Array<() => void> = [];

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

  /** Scene-space Y of elevation zero — exposed for tests (task14 §2). */
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

    // Attach camera + add to scene when a model is registered, and refresh LOD
    // whenever the camera comes to rest.
    world.camera.controls.addEventListener("rest", () => {
      void fragments.core.update(true);
    });
    fragments.list.onItemSet.add(({ value: model }) => {
      model.useCamera(world.camera.three as THREE.PerspectiveCamera);
      world.scene.three.add(model.object);
      void fragments.core.update(true);
    });

    this.components = components;
    this.world = world;
    this.fragments = fragments;

    this.configureControls();
    this.applyLens();
    this.attachPointer(container);
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
   *   2. otherwise intersect the elevation-zero base plane;
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

    // 2. elevation-zero plane
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

  private async handlePick(event: PointerEvent): Promise<void> {
    if (!this.model || !this.world) return;
    const dom = this.rendererDom();
    if (!dom) return;
    const additive = event.ctrlKey || event.shiftKey || event.metaKey;

    let result: FRAGS.RaycastResult | null = null;
    try {
      result = await this.model.raycast({
        camera: this.world.camera!.three,
        mouse: new THREE.Vector2(event.clientX, event.clientY),
        dom,
      });
    } catch {
      result = null;
    }

    if (!result) {
      if (!additive && this.manual.size > 0) {
        this.manual.clear();
        this.emitManual();
        await this.renderHighlights();
      }
      return;
    }

    const localId = result.localId;
    // Query-result-only picking (task15 §3): while blue primary results are
    // present, dimmed non-results and yellow context entities are not
    // selectable. The check runs BEFORE any selection state changes, so a
    // rejected entity never flickers into a selected state, and the current
    // selection is never replaced by clicking one. Eligibility comes from the
    // already-resolved local-id set — never a backend or LLM call.
    if (this.rolesActive && this.queryPrimarySet.size > 0 && !this.queryPrimarySet.has(localId)) {
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
    await this.fragments.core.update(true);

    await this.resolveGroundY();
    this.classification = await this.classifyGeometry();
    await this.renderHighlights();
    this.createBasePlane();
    // Optional edge overlay (task15 §2): built asynchronously AFTER the scene
    // is ready and usable, in yielded batches, so it never delays load or
    // blocks input. When it finishes it paints itself from the current roles.
    if (EDGES.enabled) {
      const overlay = new EdgeOverlay();
      this.edgeOverlay = overlay;
      void overlay.build(model, model.object).then((built) => {
        // Ignore a build that finished after the model changed underneath it.
        if (built && this.edgeOverlay === overlay) this.recolorEdges();
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
   * Scene-space Y of IFC/world elevation 0 (task14 §2).
   *
   * Derived from the model's own coordination matrix — the transform Fragments
   * applied to the original IFC coordinates — NOT from the bounding box. Using
   * the bbox centre or minimum would put the plane at an arbitrary height and
   * would move with the model's contents.
   */
  private async resolveGroundY(): Promise<void> {
    this.groundY = 0;
    if (!this.model) return;
    try {
      const matrix = await this.model.getCoordinationMatrix();
      if (matrix) {
        const origin = new THREE.Vector3(0, 0, 0).applyMatrix4(matrix);
        if (Number.isFinite(origin.y)) this.groundY = origin.y;
      }
    } catch {
      // no coordination info — elevation 0 is scene 0
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
    this.queryContext = [];
    this.queryPrimarySet = new Set();
    this.queryContextSet = new Set();
    this.rolesActive = false;
    this.classification = { roof: [], wall: [] };
    this.edgeOverlay?.dispose();
    this.edgeOverlay = null;
    this.removeBasePlane();
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
  // Base plane at elevation zero (task14 §2)
  // -------------------------------------------------------------------------

  /**
   * Quiet drafting grid at IFC/world elevation exactly 0, transformed into
   * scene coordinates. Below-zero geometry stays visible and unclipped: the
   * grid is a thin, transparent, non-depth-writing overlay, not a clip plane.
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
    const context = await this.resolveGuids(contextGuids);
    this.queryPrimary = primary.localIds;
    this.queryContext = context.localIds;
    this.queryPrimarySet = new Set(primary.localIds);
    this.queryContextSet = new Set(context.localIds);
    this.rolesActive = primary.localIds.length > 0 || context.localIds.length > 0;
    await this.renderHighlights();
    if (primary.localIds.length > 0) await this.fitToLocalIds(primary.localIds);
    else if (context.localIds.length > 0) await this.fitToLocalIds(context.localIds);
    return { missing: [...primary.missing, ...context.missing] };
  }

  async clearQueryRoles(): Promise<void> {
    this.queryPrimary = [];
    this.queryContext = [];
    this.queryPrimarySet = new Set();
    this.queryContextSet = new Set();
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
   * while the remaining primaries drop to translucent blue — never teal
   * (task15 §3). With roles cleared, the semantic roof/wall/other base colors
   * are restored — NOT one uniform material (task14 §1) — and manual picks are
   * drawn teal, last, so they stay distinct.
   */
  private async renderHighlights(): Promise<void> {
    if (!this.model || !this.fragments) return;
    try {
      await this.model.resetHighlight();
      if (this.rolesActive) {
        await this.model.highlight(undefined, DIM_MATERIAL);
        if (this.queryContext.length) {
          await this.model.highlight(this.queryContext, CONTEXT_MATERIAL);
        }
        await this.paintPrimaries();
      } else {
        await this.applyBaseColors();
        const manualIds = [...this.manual.values()];
        if (manualIds.length) await this.model.highlight(manualIds, MANUAL_MATERIAL);
      }
      this.recolorEdges();
      await this.fragments.core.update(true);
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
    const manualIds = [...this.manual.values()];
    if (this.rolesActive) {
      if (this.queryPrimarySet.has(localId)) {
        const anyFocused = manualIds.some((id) => this.queryPrimarySet.has(id));
        return !anyFocused || manualIds.includes(localId) ? "primary" : "primaryUnfocused";
      }
      return this.queryContextSet.has(localId) ? "context" : "dim";
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
