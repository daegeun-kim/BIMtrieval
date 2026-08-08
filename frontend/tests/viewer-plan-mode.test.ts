// Floor-plan mode inside the existing viewer (Task 28 §1.2, §3, §4,
// §6, §8.2).
//
// A fake Fragments model, world, and `OBC.Views` component are injected — no
// WebGL, no worker, no backend. The fakes reproduce the real component's
// contract: `createFromPlane` returns a view owning its own orthographic
// camera, `open` swaps `world.camera`, and deleting the entry closes it and
// restores the default camera.
import * as THREE from "three";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ViewerAdapter, type FloorContractBand } from "../src/viewer/ViewerAdapter";
import {
  PLAN,
  PLAN_CUT_COLOR,
  PLAN_CUT_OPACITY,
  PLAN_FILL_COLOR,
  PLAN_FILL_OPACITY,
  PLAN_WALL_CUT_COLOR,
} from "../src/viewer/viewerTheme";

const MODEL_BOX = new THREE.Box3(new THREE.Vector3(0, -0.4, 0), new THREE.Vector3(30, 9, 40));

/** Three logical floors: ground (two sub-levels), first, second. */
const CONTRACT: FloorContractBand[] = [
  { band_index: 0, label: "Floor 1", storey_global_ids: ["S0a", "S0b"] },
  { band_index: 1, label: "Floor 2", storey_global_ids: ["S1"] },
  { band_index: 2, label: "Floor 3", storey_global_ids: ["S2"] },
];

/** Raw artifact `Elevation` per storey, deliberately offset from the scene. */
const ELEVATIONS: Record<string, number> = {
  S0a: 5.0, // + coordinateHeight (-5) -> scene 0.0
  S0b: 4.9, //                          -> scene -0.1
  S1: 8.0, //                           -> scene 3.0
  S2: 11.0, //                          -> scene 6.0
};
const COORDINATE_HEIGHT = -5;

interface Harness {
  adapter: ViewerAdapter;
  views: FakeViews;
  world: FakeWorld;
  scene: THREE.Scene;
  modelObject: THREE.Object3D;
  defaultControls: FakeControls;
  getSection: ReturnType<typeof vi.fn>;
  useCamera: ReturnType<typeof vi.fn>;
  setVisible: ReturnType<typeof vi.fn>;
}

class FakeControls {
  mouseButtons = { left: 1, middle: 16, right: 2, wheel: 16 };
  maxDistance = Infinity;
  /** camera-controls drives BOTH its dolly and its zoom action from this. */
  dollySpeed = 1;
  enabled = true;
  private position = new THREE.Vector3(20, 30, 60);
  private target = new THREE.Vector3(15, 4, 20);
  setOrbitPoint = vi.fn();
  fitToBox = vi.fn(async () => {});
  setLookAt = vi.fn(
    async (px: number, py: number, pz: number, tx: number, ty: number, tz: number) => {
      this.position.set(px, py, pz);
      this.target.set(tx, ty, tz);
    },
  );
  getPosition(out: THREE.Vector3) {
    return out.copy(this.position);
  }
  getTarget(out: THREE.Vector3) {
    return out.copy(this.target);
  }
  addEventListener = vi.fn();
  removeEventListener = vi.fn();
}

class FakeCamera {
  three: THREE.Camera;
  controls = new FakeControls();
  updateAspect = vi.fn();
  constructor(ortho: boolean) {
    this.three = ortho
      ? new THREE.OrthographicCamera(-25, 25, 15, -15, 0.1, 1000)
      : new THREE.PerspectiveCamera(27, 1.5, 0.1, 1000);
  }
}

class FakeView {
  plane = new THREE.Plane();
  camera = new FakeCamera(true);
  open = false;
  private _range = 15;
  disposed = false;
  constructor(readonly id: string) {}
  set range(value: number) {
    this._range = value;
  }
  get range(): number {
    return this._range;
  }
  dispose() {
    this.disposed = true;
  }
}

class FakeViews {
  restoreCameraOnClose = true;
  world: FakeWorld | null = null;
  created: FakeView[] = [];
  openCalls: string[] = [];
  closeCalls: string[] = [];
  list = {
    entries: new Map<string, FakeView>(),
    delete: (id: string) => {
      const view = this.list.entries.get(id);
      if (!view) return false;
      if (view.open) this.close(id);
      view.dispose();
      return this.list.entries.delete(id);
    },
  };
  constructor(private readonly host: { world: FakeWorld }) {}
  createFromPlane(plane: THREE.Plane, config?: { id?: string }) {
    const view = new FakeView(config?.id ?? `v${this.created.length}`);
    view.plane.copy(plane);
    this.created.push(view);
    this.list.entries.set(view.id, view);
    return view;
  }
  open(id: string) {
    const view = this.list.entries.get(id);
    if (!view) throw new Error("no such view");
    for (const other of this.list.entries.values()) if (other.open) this.close(other.id);
    view.open = true;
    this.openCalls.push(id);
    this.host.world.camera = view.camera as unknown as FakeCamera;
  }
  close(id: string) {
    const view = this.list.entries.get(id);
    if (!view?.open) return;
    view.open = false;
    this.closeCalls.push(id);
    this.host.world.useDefaultCamera();
  }
}

interface FakeWorld {
  camera: FakeCamera;
  defaultCamera: FakeCamera;
  scene: { three: THREE.Scene };
  renderer: { three: { domElement: HTMLCanvasElement }; resize: () => void };
  useDefaultCamera(): void;
}

function makeCanvas(): HTMLCanvasElement {
  const c = document.createElement("canvas");
  Object.defineProperty(c, "clientWidth", { value: 1200, configurable: true });
  Object.defineProperty(c, "clientHeight", { value: 800, configurable: true });
  c.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1200, height: 800 }) as DOMRect;
  return c;
}

function makeHarness(opts?: {
  elevations?: Record<string, number>;
  coordinateHeight?: number;
  sectionVertices?: number;
  sectionThrows?: boolean;
  modelOffsetY?: number;
  box?: THREE.Box3;
}): Harness {
  const adapter = new ViewerAdapter(5);
  const scene = new THREE.Scene();
  const modelObject = new THREE.Object3D();
  modelObject.position.y = opts?.modelOffsetY ?? 0;
  scene.add(modelObject);

  const elevations = opts?.elevations ?? ELEVATIONS;
  const sectionVertices = opts?.sectionVertices ?? 6;

  const getSection = vi.fn(async () => {
    if (opts?.sectionThrows) throw new Error("worker failed");
    const buffer = new Float32Array(600_000);
    for (let i = 0; i < sectionVertices * 3; i++) buffer[i] = i;
    return {
      buffer,
      index: sectionVertices,
      fillsIndices: sectionVertices >= 3 ? [0, 1, 2] : [],
    };
  });
  const useCamera = vi.fn();
  const setVisible = vi.fn(async () => {});

  const gids = Object.keys(elevations);
  const model = {
    box: opts?.box ?? MODEL_BOX,
    object: modelObject,
    getLocalIdsByGuids: async (guids: string[]) =>
      guids.map((g) => (g in elevations ? gids.indexOf(g) + 1 : null)),
    getItemsData: async (ids: number[]) =>
      ids.map((id) => ({ Elevation: { value: elevations[gids[id - 1]!] } })),
    getCoordinates: async () => [0, opts?.coordinateHeight ?? COORDINATE_HEIGHT, 0],
    getSection,
    useCamera,
    setVisible,
    resetHighlight: vi.fn(async () => {}),
    highlight: vi.fn(async () => {}),
    getMergedBox: async () => MODEL_BOX,
    getLocalIdsByGuidsRaw: undefined,
  };

  const defaultCamera = new FakeCamera(false);
  const world: FakeWorld = {
    camera: defaultCamera,
    defaultCamera,
    scene: { three: scene },
    renderer: { three: { domElement: makeCanvas() }, resize: () => {} },
    useDefaultCamera() {
      this.camera = this.defaultCamera;
    },
  };
  const views = new FakeViews({ world });
  views.world = world;

  Object.assign(adapter as unknown as Record<string, unknown>, {
    model,
    world,
    components: { get: () => views },
    fragments: { core: { update: async () => {} } },
  });
  return {
    adapter,
    views,
    world,
    scene,
    modelObject,
    defaultControls: defaultCamera.controls,
    getSection,
    useCamera,
    setVisible,
  };
}

/** Adapter internals reached the same way the other viewer suites do. */
interface Internals {
  createBasePlane(): void;
  resolveGroundY(): Promise<void>;
  planSection: { group: THREE.Group } | null;
}
function priv(adapter: ViewerAdapter): Internals {
  return adapter as unknown as Internals;
}

describe("mapping logical bands into artifact scene space (task28 §3)", () => {
  it("resolves scene elevations from the artifact, not from the contract", async () => {
    const { adapter } = makeHarness();
    await adapter.setFloorContract(CONTRACT);
    const bands = adapter.getSceneBands();
    expect(bands.map((b) => b.bandIndex)).toEqual([0, 1, 2]);
    // Elevation + coordinateHeight: 5.0/4.9 -> 0.0/-0.1, 8 -> 3, 11 -> 6.
    expect(bands[0]!.maxSceneY).toBeCloseTo(0, 10);
    expect(bands[0]!.minSceneY).toBeCloseTo(-0.1, 10);
    expect(bands[1]!.maxSceneY).toBeCloseTo(3, 10);
    expect(bands[2]!.maxSceneY).toBeCloseTo(6, 10);
    // The raw artifact elevations are never used directly as scene Y.
    expect(bands.map((b) => b.maxSceneY)).not.toContain(11);
  });

  it("carries the model object's own world transform into scene space", async () => {
    const { adapter } = makeHarness({ modelOffsetY: 12 });
    await adapter.setFloorContract(CONTRACT);
    // Fragments' auto-coordination offset applies on top of the elevation sum.
    expect(adapter.getSceneBands()[1]!.maxSceneY).toBeCloseTo(15, 10);
  });

  it("reads the artifact once for the whole contract, not once per floor", async () => {
    const { adapter } = makeHarness();
    const model = (adapter as unknown as { model: { getItemsData: unknown } }).model;
    const spy = vi.spyOn(model as { getItemsData: () => unknown }, "getItemsData");
    await adapter.setFloorContract(CONTRACT);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("returns one enabled state per logical floor", async () => {
    const { adapter } = makeHarness();
    const states = await adapter.setFloorContract(CONTRACT);
    expect(states).toHaveLength(3);
    expect(states.every((s) => s.enabled)).toBe(true);
    expect(states.map((s) => s.label)).toEqual(["Floor 1", "Floor 2", "Floor 3"]);
  });

  it("disables ONLY the floor whose storeys cannot be resolved", async () => {
    // S1 is absent from the artifact, so band 1 cannot be mapped.
    const { adapter } = makeHarness({
      elevations: { S0a: 5.0, S0b: 4.9, S2: 11.0 },
    });
    const states = await adapter.setFloorContract(CONTRACT);
    expect(states.map((s) => s.enabled)).toEqual([true, false, true]);
    expect(states[1]!.reason).toMatch(/could not be located/i);
  });

  it("disables every floor, without throwing, when the artifact is unreadable", async () => {
    const { adapter } = makeHarness();
    const model = adapter as unknown as { model: { getCoordinates: () => Promise<number[]> } };
    model.model.getCoordinates = async () => {
      throw new Error("nope");
    };
    const states = await adapter.setFloorContract(CONTRACT);
    expect(states.every((s) => !s.enabled)).toBe(true);
  });
});

describe("entering plan mode (task28 §1.2)", () => {
  let h: Harness;
  beforeEach(async () => {
    h = makeHarness();
    await priv(h.adapter).resolveGroundY();
    priv(h.adapter).createBasePlane();
    await h.adapter.setFloorContract(CONTRACT);
  });

  it("keeps the same model, canvas, world, and scene", async () => {
    const sceneChildren = h.scene.children.length;
    await h.adapter.enterPlanMode(1);
    expect(h.adapter.hasModel()).toBe(true);
    expect(h.world.scene.three).toBe(h.scene);
    // Only the plan overlay is added, and it lives under the model object.
    expect(h.scene.children.length).toBe(sceneChildren);
  });

  it("activates an orthographic top-down plan camera", async () => {
    await h.adapter.enterPlanMode(1);
    expect(h.adapter.isPlanMode()).toBe(true);
    const camera = h.world.camera.three as THREE.OrthographicCamera;
    expect(camera.isOrthographicCamera).toBe(true);
    expect(camera).not.toBe(h.world.defaultCamera.three);
  });

  it("cuts 1.2 scene metres above the band and bounds the view below it", async () => {
    await h.adapter.enterPlanMode(1);
    const range = h.adapter.getPlanRange()!;
    expect(range.cut).toBeCloseTo(3 + PLAN.cutOffsetM, 10);
    expect(range.lower).toBeCloseTo(1.5, 10); // midpoint of 0 and 3
    // The View's plane keeps y <= cut and its range reaches down to `lower`.
    const view = h.views.created.at(-1)!;
    expect(view.plane.normal.y).toBe(-1);
    expect(view.plane.constant).toBeCloseTo(range.cut, 10);
    expect(view.range).toBeCloseTo(range.cut - range.lower, 10);
  });

  it("uses the model's geometric minimum for the lowest floor", async () => {
    await h.adapter.enterPlanMode(0);
    expect(h.adapter.getPlanRange()!.lower).toBeCloseTo(MODEL_BOX.min.y, 10);
  });

  it("maps every drag to pan and never to orbit", async () => {
    await h.adapter.enterPlanMode(1);
    const buttons = h.world.camera.controls.mouseButtons;
    expect(buttons.left).toBe(2); // TRUCK
    expect(buttons.middle).toBe(2);
    expect(buttons.right).toBe(2);
    expect(buttons.wheel).toBe(32); // orthographic ZOOM
    expect(Object.values(buttons)).not.toContain(1); // ROTATE
  });

  it("points Fragments' own LOD camera at the plan camera", async () => {
    await h.adapter.enterPlanMode(1);
    expect(h.useCamera).toHaveBeenCalledWith(h.world.camera.three);
  });

  it("hides the decorative base grid", async () => {
    expect(h.adapter.isBasePlaneVisible()).toBe(true);
    await h.adapter.enterPlanMode(1);
    expect(h.adapter.hasBasePlane()).toBe(true);
    expect(h.adapter.isBasePlaneVisible()).toBe(false);
  });

  it("fits the footprint through the panel-aware view-offset path", async () => {
    h.adapter.setViewportObstruction(400);
    await h.adapter.enterPlanMode(1);
    const controls = h.world.camera.controls;
    expect(controls.fitToBox).toHaveBeenCalledTimes(1);
    const camera = h.world.camera.three as THREE.OrthographicCamera;
    // Centering within the unobstructed region, on the ORTHOGRAPHIC camera.
    expect(camera.view?.enabled).toBe(true);
    expect(camera.view?.fullWidth).toBeCloseTo(800, 5); // 1200 - 400
    expect(camera.view?.width).toBe(1200);
  });

  it("marks the selected band active", async () => {
    await h.adapter.enterPlanMode(2);
    expect(h.adapter.getPlanBandIndex()).toBe(2);
  });

  it("refuses a disabled floor with a reason instead of a guessed plane", async () => {
    const bad = makeHarness({ elevations: { S0a: 5.0, S0b: 4.9, S2: 11.0 } });
    await bad.adapter.setFloorContract(CONTRACT);
    const result = await bad.adapter.enterPlanMode(1);
    expect(result.ok).toBe(false);
    expect(result.reason).toBeTruthy();
    expect(bad.adapter.isPlanMode()).toBe(false);
    expect(bad.views.created).toHaveLength(0);
  });
});

describe("the saved 3D camera (task28 §1.2, §8.2)", () => {
  let h: Harness;
  beforeEach(async () => {
    h = makeHarness();
    await h.adapter.setFloorContract(CONTRACT);
  });

  it("is captured when first leaving 3D", async () => {
    expect(h.adapter.getSavedPose()).toBeNull();
    await h.adapter.enterPlanMode(0);
    const pose = h.adapter.getSavedPose()!;
    expect(pose.position.toArray()).toEqual([20, 30, 60]);
    expect(pose.target.toArray()).toEqual([15, 4, 20]);
  });

  it("is NOT overwritten when switching directly from one floor to another", async () => {
    await h.adapter.enterPlanMode(0);
    const first = h.adapter.getSavedPose()!;
    // The plan camera drifts while the user pans it.
    await h.world.camera.controls.setLookAt(0, 500, 0, 0, 0, 0);
    await h.adapter.enterPlanMode(1);
    await h.adapter.enterPlanMode(2);
    const still = h.adapter.getSavedPose()!;
    expect(still.position.toArray()).toEqual(first.position.toArray());
    expect(still.target.toArray()).toEqual(first.target.toArray());
  });

  it("is restored exactly on returning to 3D", async () => {
    await h.adapter.enterPlanMode(0);
    await h.adapter.enterPlanMode(2);
    h.defaultControls.setLookAt.mockClear();
    await h.adapter.exitPlanMode();

    expect(h.world.camera).toBe(h.world.defaultCamera);
    expect(h.defaultControls.setLookAt).toHaveBeenCalledWith(20, 30, 60, 15, 4, 20, false);
    expect(h.adapter.getSavedPose()).toBeNull();
  });
});

describe("returning to 3D (task28 §1.2, §6)", () => {
  let h: Harness;
  beforeEach(async () => {
    h = makeHarness();
    await priv(h.adapter).resolveGroundY();
    priv(h.adapter).createBasePlane();
    await h.adapter.setFloorContract(CONTRACT);
  });

  it("removes both clipping boundaries and every plan-only overlay", async () => {
    await h.adapter.enterPlanMode(1);
    expect(h.adapter.hasPlanSection()).toBe(true);
    const view = h.views.created.at(-1)!;

    await h.adapter.exitPlanMode();
    expect(h.adapter.isPlanMode()).toBe(false);
    expect(h.adapter.hasPlanSection()).toBe(false);
    expect(h.adapter.getPlanRange()).toBeNull();
    expect(view.open).toBe(false);
    expect(view.disposed).toBe(true);
    expect(h.views.list.entries.size).toBe(0);
    expect(h.modelObject.children).toHaveLength(0);
  });

  it("restores the perspective projection, lens, controls, and base grid", async () => {
    await h.adapter.enterPlanMode(1);
    await h.adapter.exitPlanMode();

    const camera = h.world.camera.three as THREE.PerspectiveCamera;
    expect(camera.isPerspectiveCamera).toBe(true);
    expect(h.adapter.getFieldOfView()).toBeCloseTo(26.99, 1);
    expect(h.world.camera.controls.mouseButtons.middle).toBe(1); // ROTATE returns
    expect(h.adapter.isBasePlaneVisible()).toBe(true);
    expect(h.useCamera).toHaveBeenLastCalledWith(camera);
  });

  it("stays available after a plan-rendering failure", async () => {
    const broken = makeHarness({ sectionThrows: true });
    await broken.adapter.setFloorContract(CONTRACT);
    const result = await broken.adapter.enterPlanMode(1);
    // A truthful clipped orthographic view remains, with a concise limitation.
    expect(result.ok).toBe(true);
    expect(result.reason).toMatch(/outlines aren't available/i);
    expect(broken.adapter.hasPlanSection()).toBe(false);

    await broken.adapter.exitPlanMode();
    expect(broken.adapter.isPlanMode()).toBe(false);
    expect(broken.world.camera).toBe(broken.world.defaultCamera);
  });

  it("is a no-op when never in plan mode", async () => {
    await h.adapter.exitPlanMode();
    expect(h.defaultControls.setLookAt).not.toHaveBeenCalled();
    expect(h.adapter.isPlanMode()).toBe(false);
  });
});

describe("cut geometry (task28 §4.2, §4.3)", () => {
  let h: Harness;
  beforeEach(async () => {
    h = makeHarness();
    await h.adapter.setFloorContract(CONTRACT);
  });

  it("requests the section for the ACTIVE floor only, never for every floor", async () => {
    expect(h.getSection).not.toHaveBeenCalled(); // nothing precomputed at load
    await h.adapter.enterPlanMode(1);
    expect(h.getSection).toHaveBeenCalledTimes(1);
  });

  it("transforms the plane into the model's own space before sectioning", async () => {
    const offset = makeHarness({ modelOffsetY: 12 });
    await offset.adapter.setFloorContract(CONTRACT);
    await offset.adapter.enterPlanMode(1);
    const worldCut = offset.adapter.getPlanRange()!.cut; // 15 + 1.2
    const localPlane = offset.getSection.mock.calls[0]![0] as THREE.Plane;
    expect(worldCut).toBeCloseTo(16.2, 10);
    // Local space is 12 m below world space.
    expect(localPlane.constant).toBeCloseTo(worldCut - 12, 6);
  });

  it("mounts contour and fill under the model object, off the clipping plane", async () => {
    await h.adapter.enterPlanMode(1);
    expect(h.modelObject.children).toHaveLength(1);
    const group = h.modelObject.children[0] as THREE.Group;
    expect(group.position.y).toBeCloseTo(-PLAN.cutInsetM, 10);
    const types = group.children.map((c) => c.type);
    expect(types).toContain("LineSegments");
    expect(types).toContain("Mesh");
  });

  it("draws the cut contour above the base and highlight edge overlays", async () => {
    await h.adapter.enterPlanMode(1);
    const group = h.modelObject.children[0] as THREE.Group;
    const contour = group.children.find((c) => c.type === "LineSegments")!;
    const fill = group.children.find((c) => c.type === "Mesh")!;
    expect(contour.renderOrder).toBeGreaterThan(fill.renderOrder);
    expect(fill.renderOrder).toBeGreaterThan(2); // above the highlight overlay
  });

  it("uses the plan ink for contours and a restrained fill", async () => {
    await h.adapter.enterPlanMode(1);
    const group = h.modelObject.children[0] as THREE.Group;
    const contour = group.children.find((c) => c.type === "LineSegments") as THREE.LineSegments;
    const fill = group.children.find((c) => c.type === "Mesh") as THREE.Mesh;
    const contourMat = contour.material as THREE.LineBasicMaterial;
    const fillMat = fill.material as THREE.MeshBasicMaterial;
    // The contour is darker than the fill it outlines, and fully opaque.
    expect(contourMat.color.getHSL({ h: 0, s: 0, l: 0 }).l).toBeLessThan(
      fillMat.color.getHSL({ h: 0, s: 0, l: 0 }).l,
    );
    expect(contourMat.opacity).toBe(1);
    expect(fillMat.opacity).toBeLessThan(1);
  });

  it("keeps only the vertices the section actually produced", async () => {
    const small = makeHarness({ sectionVertices: 4 });
    await small.adapter.setFloorContract(CONTRACT);
    await small.adapter.enterPlanMode(1);
    const group = small.modelObject.children[0] as THREE.Group;
    const contour = group.children.find((c) => c.type === "LineSegments") as THREE.LineSegments;
    // 4 vertices, not the worker's 200,000-vertex scratch buffer.
    expect(contour.geometry.getAttribute("position").count).toBe(4);
  });

  it("produces no overlay when the plane intersects nothing", async () => {
    const empty = makeHarness({ sectionVertices: 0 });
    await empty.adapter.setFloorContract(CONTRACT);
    const result = await empty.adapter.enterPlanMode(1);
    expect(result.ok).toBe(true);
    expect(empty.adapter.hasPlanSection()).toBe(false);
    expect(empty.modelObject.children).toHaveLength(0);
  });

  it("adds a second blueprint-blue layer for query-primary cut geometry", async () => {
    await h.adapter.enterPlanMode(1);
    const baseChildren = (h.modelObject.children[0] as THREE.Group).children.length;
    h.getSection.mockClear();

    // A query highlight arriving while the plan is active.
    const model = (h.adapter as unknown as {
      model: { getLocalIdsByGuids: (g: string[]) => Promise<number[]> };
    }).model;
    model.getLocalIdsByGuids = async (guids) => guids.map((_, i) => 900 + i);
    await h.adapter.applyQueryRoles(["G-1", "G-2"], []);

    expect(h.getSection).toHaveBeenCalled();
    // The primary layer is requested for exactly the highlighted local ids.
    expect(h.getSection.mock.calls.some((c) => Array.isArray(c[1]))).toBe(true);
    const group = h.modelObject.children[0] as THREE.Group;
    expect(group.children.length).toBeGreaterThan(baseChildren);
    // Still a plan: no silent return to perspective.
    expect(h.adapter.isPlanMode()).toBe(true);
    expect((h.world.camera.three as THREE.OrthographicCamera).isOrthographicCamera).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Black wall cuts + plan wheel-zoom speed (Task 31 §5.1, §5.2)
// ---------------------------------------------------------------------------

describe("black wall cuts (task31 §5.1)", () => {
  /** Ids 1-3 are walls, 4-6 are not — the classification a real load produces. */
  const WALL_IDS = [1, 2, 3];
  const OTHER_IDS = [4, 5, 6];

  async function classifiedHarness() {
    const h = makeHarness();
    Object.assign(h.adapter as unknown as Record<string, unknown>, {
      classification: { roof: [], wall: [...WALL_IDS] },
      allLocalIds: [...WALL_IDS, ...OTHER_IDS],
    });
    await h.adapter.setFloorContract(CONTRACT);
    return h;
  }

  /** The ids each `getSection` call asked for, in call order. */
  function sectionIdCalls(h: Harness): (number[] | undefined)[] {
    return h.getSection.mock.calls.map((c) => c[1] as number[] | undefined);
  }

  it("sections walls as their own layer, disjoint from the non-wall layer", async () => {
    const h = await classifiedHarness();
    await h.adapter.enterPlanMode(1);
    const calls = sectionIdCalls(h);
    expect(calls).toHaveLength(2);
    expect(calls[0]).toEqual(OTHER_IDS); // base layer: no walls in it
    expect(calls[1]).toEqual(WALL_IDS);
  });

  it("uses #000000 for BOTH the wall cut fill and its contour", async () => {
    const h = await classifiedHarness();
    await h.adapter.enterPlanMode(1);
    const group = h.modelObject.children[0] as THREE.Group;
    const black = new THREE.Color("#000000");
    const wallLayer = group.children.filter((c) => c.renderOrder >= PLAN.wallFillRenderOrder);
    expect(wallLayer).toHaveLength(2);
    for (const object of wallLayer) {
      const material = (object as THREE.Mesh).material as THREE.Material & {
        color: THREE.Color;
      };
      expect(material.color.getHex()).toBe(black.getHex());
    }
  });

  it("keeps the non-wall cut at its existing colours and opacity", async () => {
    // The base layer must come through the wall split untouched. Asserted
    // against the theme constants rather than "not black": task28 §4.2 makes
    // the non-wall CONTOUR black on purpose (it is the darkest ink among the
    // projected layers) and only the poché FILL is grey, so a "not 0x000000"
    // check would contradict the design instead of protecting it.
    const h = await classifiedHarness();
    await h.adapter.enterPlanMode(1);
    const group = h.modelObject.children[0] as THREE.Group;
    const base = group.children.filter((c) => c.renderOrder < PLAN.wallFillRenderOrder);
    expect(base).toHaveLength(2);
    const contour = base.find((c) => c.type === "LineSegments") as THREE.LineSegments;
    const fill = base.find((c) => c.type === "Mesh") as THREE.Mesh;
    expect((contour.material as THREE.LineBasicMaterial).color.getHex()).toBe(
      PLAN_CUT_COLOR.getHex(),
    );
    expect((fill.material as THREE.MeshBasicMaterial).color.getHex()).toBe(
      PLAN_FILL_COLOR.getHex(),
    );
    // The grey poché is what distinguishes the base fill from the black wall
    // fill, so it must not have been recoloured to the wall layer's black.
    expect((fill.material as THREE.MeshBasicMaterial).color.getHex()).not.toBe(
      PLAN_WALL_CUT_COLOR.getHex(),
    );
    expect((contour.material as THREE.LineBasicMaterial).opacity).toBe(PLAN_CUT_OPACITY);
    expect((fill.material as THREE.MeshBasicMaterial).opacity).toBe(PLAN_FILL_OPACITY);
    expect((fill.material as THREE.MeshBasicMaterial).opacity).toBeLessThan(1);
  });

  it("keeps the black wall layer's alpha the same as the existing plan fill", async () => {
    const h = await classifiedHarness();
    await h.adapter.enterPlanMode(1);
    const group = h.modelObject.children[0] as THREE.Group;
    const baseFill = group.children.find(
      (c) => c.renderOrder === PLAN.baseFillRenderOrder,
    ) as THREE.Mesh;
    const wallFill = group.children.find(
      (c) => c.renderOrder === PLAN.wallFillRenderOrder,
    ) as THREE.Mesh;
    expect((wallFill.material as THREE.MeshBasicMaterial).opacity).toBe(
      (baseFill.material as THREE.MeshBasicMaterial).opacity,
    );
  });

  it("gives a query-primary wall the blue layer, above black and excluded from it", async () => {
    const h = await classifiedHarness();
    const model = (h.adapter as unknown as {
      model: { getLocalIdsByGuids: (g: string[]) => Promise<number[]> };
    }).model;
    // G-1 resolves to local id 1 — a wall that is also a query result.
    model.getLocalIdsByGuids = async () => [1];
    await h.adapter.enterPlanMode(1);
    h.getSection.mockClear();
    await h.adapter.applyQueryRoles(["G-1"], []);

    const calls = sectionIdCalls(h);
    expect(calls).toHaveLength(3);
    expect(calls[0]).toEqual(OTHER_IDS); // non-wall base, primary withheld
    expect(calls[1]).toEqual([2, 3]); // black walls, WITHOUT the primary wall
    expect(calls[2]).toEqual([1]); // the blue primary layer

    const group = h.modelObject.children[0] as THREE.Group;
    const blue = group.children.filter((c) => c.renderOrder >= PLAN.primaryFillRenderOrder);
    const black = group.children.filter(
      (c) =>
        c.renderOrder >= PLAN.wallFillRenderOrder &&
        c.renderOrder < PLAN.primaryFillRenderOrder,
    );
    expect(blue).toHaveLength(2);
    expect(black).toHaveLength(2);
    // Blue draws after black, so it can never be covered by it.
    for (const b of blue) {
      for (const k of black) expect(b.renderOrder).toBeGreaterThan(k.renderOrder);
    }
  });

  it("falls back to one plan-ink layer when the model has no wall classification", async () => {
    const h = makeHarness(); // classification/allLocalIds left empty
    await h.adapter.setFloorContract(CONTRACT);
    await h.adapter.enterPlanMode(1);
    expect(sectionIdCalls(h)).toEqual([undefined]);
    const group = h.modelObject.children[0] as THREE.Group;
    expect(group.children).toHaveLength(2);
  });

  it("never blackens ordinary 3D wall faces or 3D wall edges", async () => {
    const h = await classifiedHarness();
    await h.adapter.enterPlanMode(1);
    // The 3D wall material and its edge role are the same before and after: the
    // black layer is plan-only section geometry mounted under the model object.
    const { BASE_MATERIALS, VIEWER_COLORS } = await import("../src/viewer/viewerTheme");
    expect((BASE_MATERIALS.wall.color as THREE.Color).getHex()).toBe(
      new THREE.Color(VIEWER_COLORS.wall).getHex(),
    );
    expect(VIEWER_COLORS.wall).not.toBe("#000000");
    expect(h.adapter.edgeRoleOf(1)).toBe("wall");
  });
});

describe("plan wheel-zoom speed (task31 §5.2)", () => {
  it("re-asserts the accepted speed of 2 after the plan camera exists", async () => {
    const h = makeHarness();
    await h.adapter.setFloorContract(CONTRACT);
    // Reproduce the library assigning its abrupt default when a View is given
    // a world: the adapter's configuration runs afterwards and must win.
    const original = h.views.createFromPlane.bind(h.views);
    h.views.createFromPlane = ((plane: THREE.Plane, config?: { id?: string }) => {
      const view = original(plane, config);
      view.camera.controls.dollySpeed = 6;
      return view;
    }) as typeof h.views.createFromPlane;

    await h.adapter.enterPlanMode(1);
    expect(h.adapter.getPlanZoomSpeed()).toBe(2);
  });

  it("leaves the perspective camera's zoom speed untouched", async () => {
    const h = makeHarness();
    await h.adapter.setFloorContract(CONTRACT);
    const before = h.adapter.getPerspectiveZoomSpeed();
    await h.adapter.enterPlanMode(1);
    await h.adapter.exitPlanMode();
    expect(h.adapter.getPerspectiveZoomSpeed()).toBe(before);
  });
});

describe("stale asynchronous results and resource lifecycle (task28 §4.3, §6)", () => {
  it("cannot let an older floor's section replace a newer selection", async () => {
    const h = makeHarness();
    await h.adapter.setFloorContract(CONTRACT);

    let release: (() => void) | null = null;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let call = 0;
    h.getSection.mockImplementation(async () => {
      call += 1;
      if (call === 1) await gate; // floor 1's section stalls
      const buffer = new Float32Array(600_000);
      return { buffer, index: 6, fillsIndices: [0, 1, 2] };
    });

    const slow = h.adapter.enterPlanMode(1);
    await h.adapter.enterPlanMode(2); // newer selection wins
    release!();
    await slow;

    expect(h.adapter.getPlanBandIndex()).toBe(2);
    // Exactly one overlay, belonging to the NEW floor.
    expect(h.modelObject.children).toHaveLength(1);
    expect(h.adapter.getPlanRange()!.cut).toBeCloseTo(6 + PLAN.cutOffsetM, 10);
  });

  it("does not accumulate views, cameras, or section meshes across floor switches", async () => {
    const h = makeHarness();
    await h.adapter.setFloorContract(CONTRACT);
    for (let i = 0; i < 6; i++) await h.adapter.enterPlanMode(i % 3);

    expect(h.views.list.entries.size).toBe(1); // one live view at a time
    expect(h.modelObject.children).toHaveLength(1); // one live overlay
    expect(h.views.created.filter((v) => !v.disposed)).toHaveLength(1);
  });

  it("disposes every plan resource on unload", async () => {
    const h = makeHarness();
    await h.adapter.setFloorContract(CONTRACT);
    await h.adapter.enterPlanMode(1);

    await h.adapter.unloadModel();
    expect(h.adapter.isPlanMode()).toBe(false);
    expect(h.adapter.hasPlanSection()).toBe(false);
    expect(h.adapter.getSceneBands()).toEqual([]);
    expect(h.adapter.getSavedPose()).toBeNull();
    expect(h.views.created.every((v) => v.disposed)).toBe(true);
    expect(h.modelObject.children).toHaveLength(0);
  });

  it("disposes every plan resource on dispose", async () => {
    const h = makeHarness();
    await h.adapter.setFloorContract(CONTRACT);
    await h.adapter.enterPlanMode(1);
    h.adapter.dispose();
    expect(h.adapter.isPlanMode()).toBe(false);
    expect(h.views.created.every((v) => v.disposed)).toBe(true);
  });
});

describe("perspective-only policies are suspended, not misapplied (task28 §4.3)", () => {
  it("suspends the projected-size policy and restores hidden objects", async () => {
    const h = makeHarness();
    await h.adapter.setFloorContract(CONTRACT);
    // A live policy with two objects currently hidden.
    const policy = {
      restoreAll: vi.fn(() => [11, 22]),
      hiddenIds: () => [],
      isHidden: () => false,
      getRetainedCount: () => 0,
      reset: vi.fn(),
      evaluate: vi.fn(() => ({ hide: [], show: [] })),
    };
    Object.assign(h.adapter as unknown as Record<string, unknown>, {
      sizePolicy: policy,
      sizePolicyActive: true,
    });

    await h.adapter.enterPlanMode(1);
    expect(h.adapter.isSizePolicySuspended()).toBe(true);
    expect(policy.restoreAll).toHaveBeenCalledTimes(1);
    expect(h.setVisible).toHaveBeenCalledWith([11, 22], true);
    // The perspective FOV rule never runs against the orthographic camera.
    expect(policy.evaluate).not.toHaveBeenCalled();

    await h.adapter.exitPlanMode();
    expect(h.adapter.isSizePolicySuspended()).toBe(false);
    expect(policy.evaluate).toHaveBeenCalled(); // re-evaluated in perspective
  });

  it("leaves the policy alone when it was never active", async () => {
    const h = makeHarness();
    await h.adapter.setFloorContract(CONTRACT);
    await h.adapter.enterPlanMode(1);
    expect(h.setVisible).not.toHaveBeenCalled();
  });
});
