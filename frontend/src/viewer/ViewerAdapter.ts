// Typed viewer adapter (spec_v006 §11, Task 11 Phase 5). All imperative That
// Open / Three.js scene mutation lives here; React components never touch the
// scene directly. One active Fragments model at a time. Manual selection is kept
// visually and logically distinct from query-result roles even when they
// overlap, and camera fits are moderate so a small element never fills the view.
import * as OBC from "@thatopen/components";
import * as FRAGS from "@thatopen/fragments";
// Bundle the fragments worker locally instead of OBC.FragmentsManager.getWorker(),
// which fetches it from the unpkg CDN at runtime — this app must work fully
// offline against the local backend (spec_v006 §2, §17).
import fragmentsWorkerUrl from "@thatopen/fragments/worker?url";
import * as THREE from "three";

import {
  CONTEXT_MATERIAL,
  DIM_MATERIAL,
  MANUAL_MATERIAL,
  PRIMARY_MATERIAL,
} from "./highlightRoles";

const MIN_FIT_SIZE = 2.5; // metres — floor so tiny items don't fill the viewport
const FIT_EXPAND = 1.9; // keep surrounding geometry visible around a fit target
const CLICK_MOVE_TOLERANCE = 4; // px — distinguish a click from an orbit drag

export interface ViewerCallbacks {
  onManualSelectionChange?: (guids: string[]) => void;
  onSelectionLimitReached?: () => void;
}

export interface RoleApplyResult {
  missing: string[];
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
  private rolesActive = false;
  private selectionEnabled = true;

  private pointerDown: { x: number; y: number } | null = null;
  private readonly maxSelection: number;
  private callbacks: ViewerCallbacks = {};

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

  async init(container: HTMLElement): Promise<void> {
    if (this.components) return;

    const components = new OBC.Components();
    const worlds = components.get(OBC.Worlds);
    const world = worlds.create<OBC.SimpleScene, OBC.OrthoPerspectiveCamera, OBC.SimpleRenderer>();

    world.scene = new OBC.SimpleScene(components);
    world.scene.setup();
    world.scene.three.background = new THREE.Color("#e9edf1");

    world.renderer = new OBC.SimpleRenderer(components, container);
    world.camera = new OBC.OrthoPerspectiveCamera(components);

    components.init();

    // Faint drafting grid — part of the "measured drawing" language.
    try {
      const grids = components.get(OBC.Grids);
      const grid = grids.create(world);
      const mat = grid.three.material as THREE.Material & { color?: THREE.Color; opacity?: number };
      if (mat.color) mat.color = new THREE.Color("#c4cdd6");
      mat.opacity = 0.35;
      mat.transparent = true;
    } catch {
      // grid is decorative; never fail init over it
    }

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

    this.attachPointer(container);
  }

  private attachPointer(container: HTMLElement): void {
    const dom = this.rendererDom() ?? container;
    dom.addEventListener("pointerdown", (e) => {
      this.pointerDown = { x: e.clientX, y: e.clientY };
    });
    dom.addEventListener("pointerup", (e) => {
      const start = this.pointerDown;
      this.pointerDown = null;
      if (!start || !this.selectionEnabled) return;
      const moved = Math.hypot(e.clientX - start.x, e.clientY - start.y);
      if (moved > CLICK_MOVE_TOLERANCE) return; // orbit/pan, not a pick
      void this.handlePick(e);
    });
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

  async loadModel(bytes: ArrayBuffer, modelId: string): Promise<void> {
    if (!this.fragments) throw new Error("viewer not initialized");
    await this.unloadModel();
    const model = await this.fragments.core.load(bytes, { modelId });
    this.model = model;
    this.modelId = modelId;
    await this.fragments.core.update(true);
    await this.fitAll();
  }

  async unloadModel(): Promise<void> {
    this.manual.clear();
    this.queryPrimary = [];
    this.queryContext = [];
    this.rolesActive = false;
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

  resize(): void {
    try {
      this.world?.renderer?.resize(undefined);
      this.world?.camera.updateAspect();
    } catch {
      // resize can fire before the renderer exists; ignore
    }
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
      Math.max((size.x * FIT_EXPAND) / 2, MIN_FIT_SIZE),
      Math.max((size.y * FIT_EXPAND) / 2, MIN_FIT_SIZE),
      Math.max((size.z * FIT_EXPAND) / 2, MIN_FIT_SIZE),
    );
    const framed = new THREE.Box3(center.clone().sub(half), center.clone().add(half));
    await this.world.camera.controls.fitToBox(framed, true);
  }

  async fitToGuids(guids: string[]): Promise<RoleApplyResult> {
    if (!this.model) return { missing: guids };
    const { localIds, missing } = await this.resolveGuids(guids);
    if (localIds.length === 0) return { missing };
    try {
      const box = await this.model.getMergedBox(localIds);
      await this.fitBox(box.clone());
    } catch {
      // ignore fit errors, still report missing
    }
    return { missing };
  }

  async applyQueryRoles(primaryGuids: string[], contextGuids: string[]): Promise<RoleApplyResult> {
    if (!this.model) return { missing: [...primaryGuids, ...contextGuids] };
    const primary = await this.resolveGuids(primaryGuids);
    const context = await this.resolveGuids(contextGuids);
    this.queryPrimary = primary.localIds;
    this.queryContext = context.localIds;
    this.rolesActive = primary.localIds.length > 0 || context.localIds.length > 0;
    await this.renderHighlights();
    if (primary.localIds.length > 0) await this.fitToLocalIds(primary.localIds);
    else if (context.localIds.length > 0) await this.fitToLocalIds(context.localIds);
    return { missing: [...primary.missing, ...context.missing] };
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

  async clearQueryRoles(): Promise<void> {
    this.queryPrimary = [];
    this.queryContext = [];
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

  // Single source of truth for what is highlighted. Query roles dim the rest of
  // the model; manual picks are always drawn last so they stay distinct.
  private async renderHighlights(): Promise<void> {
    if (!this.model || !this.fragments) return;
    try {
      await this.model.resetHighlight();
      if (this.rolesActive) {
        await this.model.highlight(undefined, DIM_MATERIAL);
        if (this.queryContext.length) await this.model.highlight(this.queryContext, CONTEXT_MATERIAL);
        if (this.queryPrimary.length) await this.model.highlight(this.queryPrimary, PRIMARY_MATERIAL);
      }
      const manualIds = [...this.manual.values()];
      if (manualIds.length) await this.model.highlight(manualIds, MANUAL_MATERIAL);
      await this.fragments.core.update(true);
    } catch {
      // a highlight failure must never crash the viewer (spec_v006 §11.3, §15)
    }
  }

  dispose(): void {
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
  }
}
