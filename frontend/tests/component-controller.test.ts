// Component-panel controller flows: detail loading, stale-response guards,
// deterministic group actions, and Clear Chat vs Reset App interaction
// (tasks/task14.md §5, §6, §8).
//
// The viewer adapter and API client are fully mocked — no scene, no network,
// no LLM.
import { beforeEach, describe, expect, it, vi } from "vitest";

const viewerStub = vi.hoisted(() => ({
  setCallbacks: vi.fn(),
  init: vi.fn(async () => {}),
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
  extractItemGeometry: vi.fn(async () => null),
  dispose: vi.fn(),
}));

vi.mock("../src/viewer/ViewerAdapter", () => ({
  ViewerAdapter: vi.fn(() => viewerStub),
}));

import { api } from "../src/api/client";
import { controller } from "../src/state/controller";
import { useStore } from "../src/state/store";
import type { EntityDetailsResponse, HighlightGroupResponse } from "../src/api/types";

function details(guid = "G1"): EntityDetailsResponse {
  return {
    source_model_id: 1,
    instance: {
      global_id: guid,
      ifc_class: "IfcDoor",
      name: `Door ${guid}`,
      materials: [],
      quantities: [],
      properties: [],
    },
    type: null,
    family: null,
    availability: {
      instance: true,
      same_type: false,
      same_family: false,
      type_unavailable_reason: "This model has no explicit IFC type data for this object.",
      family_unavailable_reason: "This model has no explicit family property for this object.",
    },
  };
}

function group(partial: Partial<HighlightGroupResponse> = {}): HighlightGroupResponse {
  return {
    source_model_id: 1,
    scope: "type",
    available: true,
    unavailable_reason: null,
    total: 3,
    global_ids: ["A", "B", "C"],
    truncated: false,
    class_counts: { IfcDoor: 3 },
    ...partial,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
  Object.values(viewerStub).forEach((f) => (f as { mockClear?: () => void }).mockClear?.());
  useStore.setState({
    activeModelId: 1,
    activeModel: { source_model_id: 1, display_name: "M", source_fingerprint: "fp", viewer_asset_status: "ready" },
    messages: [],
    componentGuid: null,
    componentDetails: null,
    componentScope: null,
    componentGroupNotice: null,
  });
});

describe("component details loading (task14 §5)", () => {
  it("fetches bounded details through the narrow endpoint", async () => {
    const spy = vi.spyOn(api, "entityDetails").mockResolvedValue(details("G1"));
    await controller.openComponent("G1");
    expect(spy).toHaveBeenCalledWith(1, "G1", expect.anything());
    expect(useStore.getState().componentDetails?.instance.global_id).toBe("G1");
    expect(useStore.getState().componentLoading).toBe(false);
  });

  it("surfaces a bounded error without crashing the panel", async () => {
    vi.spyOn(api, "entityDetails").mockRejectedValue(new Error("boom"));
    await controller.openComponent("G1");
    expect(useStore.getState().componentError).toBeTruthy();
    expect(useStore.getState().componentLoading).toBe(false);
  });

  it("ignores a stale detail response after the subject changed", async () => {
    // G1 resolves slowly; G2 is selected while it is in flight.
    vi.spyOn(api, "entityDetails").mockImplementation(async (_m, guid) => {
      if (guid === "G1") await new Promise((r) => setTimeout(r, 30));
      return details(guid);
    });

    const slow = controller.openComponent("G1");
    await new Promise((r) => setTimeout(r, 5));
    await controller.openComponent("G2");
    await slow;

    // The late G1 response must not paint over the current G2 subject.
    expect(useStore.getState().componentGuid).toBe("G2");
    expect(useStore.getState().componentDetails?.instance.global_id).toBe("G2");
  });

  it("ignores a detail response that lands after the panel closed", async () => {
    vi.spyOn(api, "entityDetails").mockImplementation(async (_m, guid) => {
      await new Promise((r) => setTimeout(r, 20));
      return details(guid);
    });
    const pending = controller.openComponent("G1");
    controller.closeComponent();
    await pending;
    expect(useStore.getState().componentGuid).toBeNull();
    expect(useStore.getState().componentDetails).toBeNull();
  });

  it("does nothing without an active model", async () => {
    useStore.setState({ activeModelId: null });
    const spy = vi.spyOn(api, "entityDetails");
    await controller.openComponent("G1");
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("deterministic group actions (task14 §5)", () => {
  beforeEach(() => {
    useStore.setState({ componentGuid: "G1", componentDetails: details("G1") });
  });

  it("highlights the returned identities and creates no chat message", async () => {
    vi.spyOn(api, "highlightGroup").mockResolvedValue(group());
    const querySpy = vi.spyOn(api, "query");

    await controller.applyGroupScope("type");

    expect(viewerStub.applyQueryRoles).toHaveBeenCalledWith(["A", "B", "C"], []);
    expect(querySpy).not.toHaveBeenCalled(); // no LLM, no chat turn
    expect(useStore.getState().messages).toHaveLength(0);
    expect(useStore.getState().componentScope).toBe("type");
    expect(useStore.getState().componentGroupNotice).toBe("3 matching objects.");
  });

  it("reports the exact total and truncation above the cap", async () => {
    const ids = Array.from({ length: 2000 }, (_, i) => `G-${i}`);
    vi.spyOn(api, "highlightGroup").mockResolvedValue(
      group({ total: 5000, global_ids: ids, truncated: true }),
    );
    await controller.applyGroupScope("type");
    expect(useStore.getState().componentGroupNotice).toBe(
      "Highlighted the first 2000 of 5000 matching objects.",
    );
  });

  it("reports an unavailable scope truthfully and highlights nothing", async () => {
    vi.spyOn(api, "highlightGroup").mockResolvedValue(
      group({
        available: false,
        total: 0,
        global_ids: [],
        unavailable_reason: "This model has no explicit IFC type data for this object.",
      }),
    );
    await controller.applyGroupScope("type");
    expect(viewerStub.applyQueryRoles).not.toHaveBeenCalled();
    expect(useStore.getState().componentScope).toBeNull();
    expect(useStore.getState().componentGroupNotice).toMatch(/no explicit IFC type data/);
  });

  it("keeps the selected entity as the panel subject", async () => {
    vi.spyOn(api, "highlightGroup").mockResolvedValue(group());
    await controller.applyGroupScope("type");
    expect(useStore.getState().componentGuid).toBe("G1");
  });

  it("ignores a stale group response after the subject changed", async () => {
    vi.spyOn(api, "highlightGroup").mockImplementation(async () => {
      await new Promise((r) => setTimeout(r, 25));
      return group();
    });
    const pending = controller.applyGroupScope("type");
    useStore.setState({ componentGuid: "G2" }); // user picked another object
    await pending;
    expect(useStore.getState().componentScope).toBeNull();
  });
});

describe("Clear Chat vs Reset App with the panel open (task14 §6)", () => {
  beforeEach(() => {
    useStore.setState({
      componentGuid: "G1",
      componentDetails: details("G1"),
      componentScope: "type",
      componentGroupNotice: "3 matching objects.",
      manualGuids: ["G1"],
    });
  });

  it("Clear Chat keeps the model, selection and panel, but drops the group highlight", async () => {
    vi.spyOn(api, "query").mockResolvedValue({} as never);
    await controller.clearChat();

    expect(useStore.getState().componentGuid).toBe("G1"); // panel follows selection, which is kept
    expect(useStore.getState().componentDetails).not.toBeNull();
    expect(useStore.getState().activeModelId).toBe(1);
    // the group highlight is a query-result role, so it clears
    expect(viewerStub.clearQueryRoles).toHaveBeenCalled();
    expect(useStore.getState().componentScope).toBeNull();
  });

  it("a late group response cannot re-highlight after Clear Chat", async () => {
    vi.spyOn(api, "query").mockResolvedValue({} as never);
    vi.spyOn(api, "highlightGroup").mockImplementation(async () => {
      await new Promise((r) => setTimeout(r, 25));
      return group();
    });

    const pending = controller.applyGroupScope("type");
    await controller.clearChat();
    viewerStub.applyQueryRoles.mockClear();
    await pending;

    expect(viewerStub.applyQueryRoles).not.toHaveBeenCalled();
    expect(useStore.getState().componentScope).toBeNull();
  });

  it("Reset App closes the panel and clears its state entirely", async () => {
    vi.spyOn(api, "query").mockResolvedValue({} as never);
    await controller.resetApp();

    expect(useStore.getState().componentGuid).toBeNull();
    expect(useStore.getState().componentDetails).toBeNull();
    expect(useStore.getState().componentScope).toBeNull();
    expect(useStore.getState().activeModelId).toBeNull();
    expect(viewerStub.unloadModel).toHaveBeenCalled();
  });
});
