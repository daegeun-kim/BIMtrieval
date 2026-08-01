// Floor-plan mode is a user-controlled VIEWER state, not an answer presentation
// (tasks/task28.md §1.3, §6, §8.2).
//
// The whole point of this suite is what must NOT happen: no chat turn, no
// natural-language query, no LLM call, no change to the Query Explanation panel,
// and no change to query/selection roles.
import { beforeEach, describe, expect, it, vi } from "vitest";

const viewerStub = vi.hoisted(() => ({
  init: vi.fn(async () => {}),
  setCallbacks: vi.fn(),
  isInitialized: () => true,
  hasModel: vi.fn(() => true),
  loadModel: vi.fn(async () => {}),
  unloadModel: vi.fn(async () => {}),
  resize: vi.fn(),
  fitAll: vi.fn(async () => {}),
  fitToGuids: vi.fn(async (): Promise<{ missing: string[] }> => ({ missing: [] })),
  applyQueryRoles: vi.fn(async (): Promise<{ missing: string[] }> => ({ missing: [] })),
  clearQueryRoles: vi.fn(async () => {}),
  clearManualSelection: vi.fn(),
  removeManualSelection: vi.fn(),
  setSelectionEnabled: vi.fn(),
  setFloorContract: vi.fn(
    async (
      floors: { band_index: number; label: string; storey_global_ids: string[] }[],
    ) =>
      floors.map((f) => ({
        bandIndex: f.band_index,
        label: f.label,
        enabled: true,
        reason: null as string | null,
      })),
  ),
  enterPlanMode: vi.fn(async (): Promise<{ ok: boolean; reason?: string }> => ({ ok: true })),
  exitPlanMode: vi.fn(async () => {}),
  setVisualizationMode: vi.fn(async () => {}),
  dispose: vi.fn(),
}));

vi.mock("../src/viewer/ViewerAdapter", () => ({
  ViewerAdapter: vi.fn(() => viewerStub),
}));

import { api } from "../src/api/client";
import type { ModelFloorsResponse } from "../src/api/types";
import { controller } from "../src/state/controller";
import { useStore } from "../src/state/store";

const MODEL_ID = 3;

function floorsResponse(overrides?: Partial<ModelFloorsResponse>): ModelFloorsResponse {
  return {
    source_model_id: MODEL_ID,
    available: true,
    unavailable_reason: null,
    reference_band_index: 0,
    reference_basis: "elevation_zero",
    total_storeys: 5,
    floors: [
      {
        band_index: 0,
        label: "Floor 1",
        is_reference: true,
        storey_global_ids: ["S0a", "S0b"],
        storey_names: ["01 begane grond"],
        min_elevation: -0.08,
        max_elevation: 0,
      },
      {
        band_index: 1,
        label: "Floor 2",
        is_reference: false,
        storey_global_ids: ["S1"],
        storey_names: ["02 verdieping"],
        min_elevation: 3,
        max_elevation: 3,
      },
    ],
    ...overrides,
  };
}

function activate(modelId = MODEL_ID): void {
  useStore.getState().setActiveModel({
    source_model_id: modelId,
    display_name: `Model ${modelId}`,
    source_fingerprint: "fp",
    viewer_asset_status: "ready",
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  Object.values(viewerStub).forEach((v) => {
    if (typeof v === "function" && "mockClear" in v) (v as { mockClear: () => void }).mockClear();
  });
  const s = useStore.getState();
  s.clearFloors();
  s.clearMessages();
  s.closeExplanation();
  s.setActiveModel(null);
});

describe("loading the floor contract (task28 §2.1)", () => {
  it("maps the contract into scene space and publishes one option per band", async () => {
    activate();
    vi.spyOn(api, "modelFloors").mockResolvedValue(floorsResponse());
    await controller.loadFloors(MODEL_ID);

    const s = useStore.getState();
    expect(s.floorsAvailable).toBe(true);
    expect(s.floorsLoading).toBe(false);
    expect(s.floorOptions.map((o) => o.label)).toEqual(["Floor 1", "Floor 2"]);
    expect(s.floorOptions[0]!.storeyNames).toEqual(["01 begane grond"]);
    expect(s.floorMode).toBe("3d");
  });

  it("hands the viewer identities only — never the stored elevations", async () => {
    activate();
    vi.spyOn(api, "modelFloors").mockResolvedValue(floorsResponse());
    await controller.loadFloors(MODEL_ID);

    const handed = viewerStub.setFloorContract.mock.calls[0]![0];
    expect(handed).toEqual([
      { band_index: 0, label: "Floor 1", storey_global_ids: ["S0a", "S0b"] },
      { band_index: 1, label: "Floor 2", storey_global_ids: ["S1"] },
    ]);
    expect(JSON.stringify(handed)).not.toContain("elevation");
  });

  it("omits the control when the model reports no usable floors", async () => {
    activate();
    vi.spyOn(api, "modelFloors").mockResolvedValue(
      floorsResponse({ available: false, floors: [], reference_band_index: null }),
    );
    await controller.loadFloors(MODEL_ID);

    const s = useStore.getState();
    expect(s.floorsAvailable).toBe(false);
    expect(s.floorOptions).toEqual([]);
    expect(viewerStub.setFloorContract).not.toHaveBeenCalled();
  });

  it("omits the control, without breaking the viewer, when the request fails", async () => {
    activate();
    vi.spyOn(api, "modelFloors").mockRejectedValue(new Error("boom"));
    await expect(controller.loadFloors(MODEL_ID)).resolves.toBeUndefined();

    const s = useStore.getState();
    expect(s.floorsAvailable).toBe(false);
    expect(s.floorsLoading).toBe(false);
    expect(viewerStub.unloadModel).not.toHaveBeenCalled();
  });

  it("ignores a response for a model that is no longer active", async () => {
    activate(99); // a DIFFERENT model became active
    vi.spyOn(api, "modelFloors").mockResolvedValue(floorsResponse());
    await controller.loadFloors(MODEL_ID);

    const s = useStore.getState();
    expect(s.floorOptions).toEqual([]);
    expect(s.floorsAvailable).toBe(false);
  });

  it("ignores a superseded in-flight load", async () => {
    activate();
    let release: (() => void) | null = null;
    const gate = new Promise<void>((r) => {
      release = r;
    });
    vi.spyOn(api, "modelFloors").mockImplementation(async () => {
      await gate;
      return floorsResponse();
    });

    const first = controller.loadFloors(MODEL_ID);
    vi.spyOn(api, "modelFloors").mockResolvedValue(
      floorsResponse({ floors: [floorsResponse().floors![0]!] }),
    );
    await controller.loadFloors(MODEL_ID); // newer load wins
    release!();
    await first;

    expect(useStore.getState().floorOptions.map((o) => o.label)).toEqual(["Floor 1"]);
  });

  it("carries a per-floor disabled reason from the viewer through to the button", async () => {
    activate();
    vi.spyOn(api, "modelFloors").mockResolvedValue(floorsResponse());
    viewerStub.setFloorContract.mockResolvedValueOnce([
      { bandIndex: 0, label: "Floor 1", enabled: true, reason: null },
      { bandIndex: 1, label: "Floor 2", enabled: false, reason: "not locatable" },
    ]);
    await controller.loadFloors(MODEL_ID);

    const options = useStore.getState().floorOptions;
    expect(options[1]!.enabled).toBe(false);
    expect(options[1]!.reason).toBe("not locatable");
  });
});

describe("switching modes never touches the conversation (task28 §1.3)", () => {
  beforeEach(async () => {
    activate();
    vi.spyOn(api, "modelFloors").mockResolvedValue(floorsResponse());
    await controller.loadFloors(MODEL_ID);
  });

  it("creates no chat turn, issues no query, and calls no LLM", async () => {
    const query = vi.spyOn(api, "query");
    await controller.selectFloor(1);
    await controller.selectFloor(0);
    await controller.selectFloor(null);

    expect(query).not.toHaveBeenCalled();
    expect(useStore.getState().messages).toEqual([]);
  });

  it("neither opens nor closes the Query Explanation panel", async () => {
    const explanation = {
      part_id: "p1",
      request_label: "walls",
      operation: "count",
      result_status: "exact",
      presentation: "metric",
    } as never;
    useStore.getState().openExplanation(explanation, ["G-1"], []);

    await controller.selectFloor(1);
    expect(useStore.getState().explanation).toBe(explanation);
    await controller.selectFloor(null);
    expect(useStore.getState().explanation).toBe(explanation);
  });

  it("leaves query-primary, relationship-context, and manual roles untouched", async () => {
    await controller.selectFloor(1);
    await controller.selectFloor(null);
    expect(viewerStub.applyQueryRoles).not.toHaveBeenCalled();
    expect(viewerStub.clearQueryRoles).not.toHaveBeenCalled();
    expect(viewerStub.clearManualSelection).not.toHaveBeenCalled();
  });

  it("enters plan mode for the selected band and marks it active", async () => {
    await controller.selectFloor(1);
    expect(viewerStub.enterPlanMode).toHaveBeenCalledWith(1);
    const s = useStore.getState();
    expect(s.floorMode).toBe("plan");
    expect(s.floorBandIndex).toBe(1);
  });

  it("returns to 3D and clears the active floor", async () => {
    await controller.selectFloor(1);
    await controller.selectFloor(null);
    expect(viewerStub.exitPlanMode).toHaveBeenCalled();
    const s = useStore.getState();
    expect(s.floorMode).toBe("3d");
    expect(s.floorBandIndex).toBeNull();
  });

  it("switching floor to floor does not pass through 3D", async () => {
    await controller.selectFloor(0);
    viewerStub.exitPlanMode.mockClear();
    await controller.selectFloor(1);
    expect(viewerStub.exitPlanMode).not.toHaveBeenCalled();
    expect(useStore.getState().floorBandIndex).toBe(1);
  });

  it("disables only the failing floor and stays in the current mode", async () => {
    viewerStub.enterPlanMode.mockResolvedValueOnce({ ok: false, reason: "no room above" });
    await controller.selectFloor(1);

    const s = useStore.getState();
    expect(s.floorMode).toBe("3d");
    expect(s.floorOptions.find((o) => o.bandIndex === 1)!.enabled).toBe(false);
    expect(s.floorOptions.find((o) => o.bandIndex === 1)!.reason).toBe("no room above");
    expect(s.floorOptions.find((o) => o.bandIndex === 0)!.enabled).toBe(true);
  });

  it("surfaces a non-blocking plan limitation without leaving plan mode", async () => {
    viewerStub.enterPlanMode.mockResolvedValueOnce({ ok: true, reason: "no cut outlines" });
    await controller.selectFloor(1);
    const s = useStore.getState();
    expect(s.floorMode).toBe("plan");
    expect(s.floorNotice).toBe("no cut outlines");
  });

  it("refuses a band that is not in the contract", async () => {
    await controller.selectFloor(42);
    expect(viewerStub.enterPlanMode).not.toHaveBeenCalled();
    expect(useStore.getState().floorMode).toBe("3d");
  });
});

describe("lifecycle (task28 §1.2, §6)", () => {
  beforeEach(async () => {
    activate();
    vi.spyOn(api, "modelFloors").mockResolvedValue(floorsResponse());
    await controller.loadFloors(MODEL_ID);
    await controller.selectFloor(1);
  });

  it("Reset App returns to 3D and drops the floor buttons", async () => {
    vi.spyOn(api, "query").mockResolvedValue({} as never);
    await controller.resetApp();

    expect(viewerStub.exitPlanMode).toHaveBeenCalled();
    const s = useStore.getState();
    expect(s.floorMode).toBe("3d");
    expect(s.floorBandIndex).toBeNull();
    expect(s.floorOptions).toEqual([]);
    expect(s.floorsAvailable).toBe(false);
  });

  it("switching models retires the outgoing model's floors", async () => {
    vi.spyOn(api, "query").mockResolvedValue({} as never);
    vi.spyOn(api, "fetchViewerAsset").mockRejectedValue(new Error("stop here"));
    await controller.confirmAndLoadModel({
      source_model_id: 9,
      display_name: "Other",
      source_fingerprint: "fp9",
      viewer_asset_status: "ready",
    });

    expect(viewerStub.exitPlanMode).toHaveBeenCalled();
    const s = useStore.getState();
    expect(s.floorMode).toBe("3d");
    expect(s.floorOptions).toEqual([]);
  });

  it("never persists the mode or the selected floor", async () => {
    const keys = Object.keys(localStorage).concat(Object.keys(sessionStorage));
    expect(keys.some((k) => /floor|plan/i.test(k))).toBe(false);
  });
});
