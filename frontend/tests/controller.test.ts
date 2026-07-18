// Controller flows: Clear Chat vs Reset App, stale-response rejection,
// retry gating, viewer-action application (Task 11 Phases 8-9; spec_v006 §13,
// §18.1). The viewer adapter and API client are fully mocked — no scene, no
// network, no LLM.
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
  dispose: vi.fn(),
}));

vi.mock("../src/viewer/ViewerAdapter", () => ({
  ViewerAdapter: vi.fn(() => viewerStub),
}));

import { api } from "../src/api/client";
import { controller } from "../src/state/controller";
import { useStore } from "../src/state/store";
import type { QueryResponseEnvelope } from "../src/api/types";

const renderTimingSpy = vi.spyOn(api, "reportQueryRenderTiming").mockResolvedValue();

function envelope(partial: Partial<QueryResponseEnvelope> = {}): QueryResponseEnvelope {
  return {
    request_id: "r1",
    session_id: "s1",
    status: "success",
    scope: "active_model",
    route: "sql",
    answer_basis: "exact_sql",
    answer: "There are 84 doors.",
    active_source_model_id: 1,
    model_candidates: [],
    primary_entities: [],
    context_entities: [],
    relationships: [],
    viewer_actions: {
      model_action: "keep_current",
      selection_action: "select_and_fit",
      primary_global_ids: ["G-P"],
      context_global_ids: ["G-C"],
      role_groups: [],
      load_model_id: null,
      viewer_source_location: null,
    },
    evidence_summary: { basis: "exact_sql", sql_match_count: 84, notes: [] },
    warnings: [],
    ...partial,
  } as QueryResponseEnvelope;
}

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    messages: [],
    pending: false,
    retryQuestion: null,
    manualGuids: [],
    resolvedChips: {},
    activeModel: {
      source_model_id: 1,
      display_name: "M1",
      source_fingerprint: "fp",
      viewer_asset_status: "ready",
    },
    activeModelId: 1,
    loadPhase: "ready",
  });
});

describe("submitQuestion", () => {
  it("sends session, model, selection, bounded history; applies viewer roles", async () => {
    const spy = vi.spyOn(api, "query").mockResolvedValue(envelope());
    useStore.getState().setManualGuids(["G1", "G2"]);

    await controller.submitQuestion("How many doors?");

    const req = spy.mock.calls[0]![0];
    expect(req.question).toBe("How many doors?");
    expect(req.active_source_model_id).toBe(1);
    expect(req.selected_global_ids).toEqual(["G1", "G2"]);
    expect(viewerStub.applyQueryRoles).toHaveBeenCalledWith(["G-P"], ["G-C"]);
    expect(renderTimingSpy).toHaveBeenCalledWith(
      expect.objectContaining({ request_id: "r1" }),
    );
    const msgs = useStore.getState().messages;
    expect(msgs.at(-1)?.evidence?.route).toBe("sql");
    expect(useStore.getState().pending).toBe(false);
  });

  it("rejects blank input without any API call", async () => {
    const spy = vi.spyOn(api, "query");
    await controller.submitQuestion("   ");
    expect(spy).not.toHaveBeenCalled();
  });

  it("adds a bounded warning message for unrenderable GlobalIds", async () => {
    vi.spyOn(api, "query").mockResolvedValue(envelope());
    viewerStub.applyQueryRoles.mockResolvedValueOnce({ missing: ["GONE"] });
    await controller.submitQuestion("q");
    const notice = useStore.getState().messages.find((m) => m.kind === "notice");
    expect(notice?.content).toContain("couldn't be highlighted");
  });

  it("offers Retry only for retryable failures and never auto-retries", async () => {
    const { ApiError } = await import("../src/api/types");
    const spy = vi
      .spyOn(api, "query")
      .mockRejectedValue(new ApiError("backend_unavailable", "down", { retryable: true }));
    await controller.submitQuestion("q");
    expect(useStore.getState().retryQuestion).toBe("q");
    expect(spy).toHaveBeenCalledTimes(1); // no automatic retry
  });

  it("ignores a response that arrives after cancellation (stale rejection)", async () => {
    let resolveLate: (v: QueryResponseEnvelope) => void = () => {};
    vi.spyOn(api, "query").mockReturnValue(
      new Promise<QueryResponseEnvelope>((res) => {
        resolveLate = res;
      }),
    );
    const inFlight = controller.submitQuestion("slow question");
    controller.cancelQuery();
    resolveLate(envelope({ answer: "LATE" }));
    await inFlight;
    expect(useStore.getState().messages.some((m) => m.content === "LATE")).toBe(false);
    expect(useStore.getState().pending).toBe(false);
  });
});

describe("Clear Chat vs Reset App", () => {
  it("clearChat keeps model + selection, clears messages, rotates session", async () => {
    vi.spyOn(api, "query").mockResolvedValue(envelope());
    useStore.setState({
      messages: [{ id: "m1", role: "user", content: "hi", kind: "text", createdAt: 1 }],
      manualGuids: ["G1"],
    });
    const before = useStore.getState().sessionId;

    await controller.clearChat();

    const s = useStore.getState();
    expect(s.messages).toEqual([]);
    expect(s.manualGuids).toEqual(["G1"]); // manual selection kept
    expect(s.activeModelId).toBe(1); // model kept
    expect(s.sessionId).not.toBe(before); // fresh conversation identity
    expect(viewerStub.clearQueryRoles).toHaveBeenCalled();
    expect(viewerStub.unloadModel).not.toHaveBeenCalled();
    expect(viewerStub.clearManualSelection).not.toHaveBeenCalled();
  });

  it("resetApp also unloads the model and returns to the initial state", async () => {
    vi.spyOn(api, "query").mockResolvedValue(envelope());
    useStore.setState({
      messages: [{ id: "m1", role: "user", content: "hi", kind: "text", createdAt: 1 }],
      manualGuids: ["G1"],
    });
    const before = useStore.getState().sessionId;

    await controller.resetApp();

    const s = useStore.getState();
    expect(s.messages).toEqual([]);
    expect(s.manualGuids).toEqual([]);
    expect(s.activeModelId).toBeNull();
    expect(s.loadPhase).toBe("idle");
    expect(s.sessionId).not.toBe(before);
    expect(viewerStub.unloadModel).toHaveBeenCalled();
    expect(viewerStub.clearManualSelection).toHaveBeenCalled();
  });
});

describe("citations", () => {
  it("focusCitation fits the object without calling the query API", async () => {
    const spy = vi.spyOn(api, "query");
    await controller.focusCitation({
      entityId: 1,
      globalId: "G9",
      ifcClass: "IfcDoor",
      role: "primary",
    });
    expect(viewerStub.fitToGuids).toHaveBeenCalledWith(["G9"]);
    expect(spy).not.toHaveBeenCalled();
  });
});
