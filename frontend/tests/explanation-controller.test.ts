// Query-explanation lifecycle and viewer synchronization (tasks/task26.md
// §2, §5, §6, §7). The viewer adapter and API client are fully mocked — no
// scene, no network, no LLM.
//
// The property these tests protect: the card and the 3D highlight are applied
// and retired together, so they can never describe different sets.
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
  // Floor-plan mode (task28): the controller returns the viewer to 3D and
  // retires the floor contract on model switch and Reset App.
  setFloorContract: vi.fn(async () => []),
  enterPlanMode: vi.fn(async () => ({ ok: true })),
  exitPlanMode: vi.fn(async () => {}),
  setVisualizationMode: vi.fn(async () => {}),
  clearManualSelection: vi.fn(),
  removeManualSelection: vi.fn(),
  setSelectionEnabled: vi.fn(),
  dispose: vi.fn(),
}));

vi.mock("../src/viewer/ViewerAdapter", () => ({
  ViewerAdapter: vi.fn(() => viewerStub),
}));

import { api } from "../src/api/client";
import type { AnswerExplanation, QueryResponseEnvelope } from "../src/api/types";
import { controller } from "../src/state/controller";
import { useStore } from "../src/state/store";

vi.spyOn(api, "reportQueryRenderTiming").mockResolvedValue();

function explanation(partial: Partial<AnswerExplanation> = {}): AnswerExplanation {
  return {
    part_id: "p1",
    request_label: "external doors on floor 3",
    operation: "count",
    result_status: "exact",
    presentation: "result_table",
    answer_basis: "exact_sql",
    interpretation: "doors whose storey is the third elevation band",
    retrieval_modes: ["sql"],
    exact_total: 9,
    class_breakdown: { IfcDoor: 5, IfcWindow: 4 },
    distribution: [],
    aggregate: null,
    relationship_endpoint_total: null,
    limitation: null,
    known_parts: [],
    unknown_parts: [],
    shown_identity_count: 9,
    true_result_count: 9,
    identities_truncated: false,
    groups: [
      { key: "IfcDoor", label: "IfcDoor", exact_count: 5, shown_count: 5, truncated: false,
        global_ids: ["D1", "D2", "D3", "D4", "D5"] },
      { key: "IfcWindow", label: "IfcWindow", exact_count: 4, shown_count: 4, truncated: false,
        global_ids: ["W1", "W2", "W3", "W4"] },
    ],
    rows: [],
    ...partial,
  } as AnswerExplanation;
}

const ALL_PRIMARY = ["D1", "D2", "D3", "D4", "D5", "W1", "W2", "W3", "W4"];

function envelope(partial: Partial<QueryResponseEnvelope> = {}): QueryResponseEnvelope {
  return {
    request_id: "r1",
    session_id: "s1",
    status: "success",
    scope: "active_model",
    route: "hybrid",
    answer_basis: "exact_sql",
    answer: "There are 9 external doors on floor 3.",
    active_source_model_id: 1,
    model_candidates: [],
    primary_entities: [],
    context_entities: [],
    relationships: [],
    viewer_actions: {
      model_action: "keep_current",
      selection_action: "select_and_fit",
      primary_global_ids: ALL_PRIMARY,
      context_global_ids: ["CTX1"],
      role_groups: [],
      load_model_id: null,
      viewer_source_location: null,
    },
    evidence_summary: { basis: "exact_sql", sql_match_count: 9, notes: [] },
    answer_explanation: explanation(),
    warnings: [],
    ...partial,
  } as QueryResponseEnvelope;
}

beforeEach(() => {
  vi.clearAllMocks();
  viewerStub.hasModel.mockReturnValue(true);
  useStore.setState({
    messages: [],
    pending: false,
    retryQuestion: null,
    manualGuids: [],
    resolvedChips: {},
    componentGuid: null,
    explanation: null,
    explanationPrimaryGuids: [],
    explanationContextGuids: [],
    explanationGroupKey: null,
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

describe("opening and replacing the explanation", () => {
  it("opens on a qualifying highlighted answer and stores the original roles", async () => {
    vi.spyOn(api, "query").mockResolvedValue(envelope());
    await controller.submitQuestion("how many external doors on floor 3?");

    const s = useStore.getState();
    expect(s.explanation?.part_id).toBe("p1");
    expect(s.explanationPrimaryGuids).toEqual(ALL_PRIMARY);
    expect(s.explanationContextGuids).toEqual(["CTX1"]);
    expect(s.explanationGroupKey).toBeNull();
    expect(viewerStub.applyQueryRoles).toHaveBeenCalledWith(ALL_PRIMARY, ["CTX1"]);
  });

  it("replaces both the explanation and the highlight for a newer qualifying answer", async () => {
    vi.spyOn(api, "query").mockResolvedValue(envelope());
    await controller.submitQuestion("q1");
    await controller.selectExplanationGroup("IfcDoor");
    expect(useStore.getState().explanationGroupKey).toBe("IfcDoor");

    vi.spyOn(api, "query").mockResolvedValue(
      envelope({
        request_id: "r2",
        answer_explanation: explanation({ part_id: "p2", request_label: "windows" }),
        viewer_actions: {
          model_action: "keep_current",
          selection_action: "select_and_fit",
          primary_global_ids: ["N1"],
          context_global_ids: [],
          role_groups: [],
          load_model_id: null,
          viewer_source_location: null,
        },
      }),
    );
    await controller.submitQuestion("q2");

    const s = useStore.getState();
    expect(s.explanation?.part_id).toBe("p2");
    // the previous subgroup must not survive into the new result
    expect(s.explanationGroupKey).toBeNull();
    expect(s.explanationPrimaryGuids).toEqual(["N1"]);
  });

  it("a newer answer with no highlight retires the panel AND the old highlight", async () => {
    vi.spyOn(api, "query").mockResolvedValue(envelope());
    await controller.submitQuestion("q1");
    expect(useStore.getState().explanation).not.toBeNull();

    vi.spyOn(api, "query").mockResolvedValue(
      envelope({
        answer_explanation: null,
        viewer_actions: {
          model_action: "keep_current",
          selection_action: "none",
          primary_global_ids: [],
          context_global_ids: [],
          role_groups: [],
          load_model_id: null,
          viewer_source_location: null,
        },
      }),
    );
    await controller.submitQuestion("something unanswerable");

    expect(useStore.getState().explanation).toBeNull();
    expect(viewerStub.clearQueryRoles).toHaveBeenCalled();
  });

  it("a highlighted answer without an explanation payload leaves no stale card", async () => {
    vi.spyOn(api, "query").mockResolvedValue(envelope());
    await controller.submitQuestion("q1");

    vi.spyOn(api, "query").mockResolvedValue(envelope({ answer_explanation: null }));
    await controller.submitQuestion("q2");

    expect(useStore.getState().explanation).toBeNull();
  });

  it("a stale/canceled response cannot restore old content", async () => {
    let resolveLate: (v: QueryResponseEnvelope) => void = () => {};
    vi.spyOn(api, "query").mockReturnValue(
      new Promise<QueryResponseEnvelope>((res) => {
        resolveLate = res;
      }),
    );
    const inFlight = controller.submitQuestion("slow");
    controller.cancelQuery();
    resolveLate(envelope());
    await inFlight;

    expect(useStore.getState().explanation).toBeNull();
    expect(viewerStub.applyQueryRoles).not.toHaveBeenCalled();
  });
});

describe("subgroup selection and restoration", () => {
  beforeEach(async () => {
    vi.spyOn(api, "query").mockResolvedValue(envelope());
    await controller.submitQuestion("q");
    vi.clearAllMocks();
  });

  it("applies only the subgroup's authoritative identities to the viewer", async () => {
    await controller.selectExplanationGroup("IfcDoor");
    expect(viewerStub.applyQueryRoles).toHaveBeenCalledWith(["D1", "D2", "D3", "D4", "D5"], []);
    expect(useStore.getState().explanationGroupKey).toBe("IfcDoor");
  });

  it("All results restores the original primary AND context roles exactly", async () => {
    await controller.selectExplanationGroup("IfcWindow");
    vi.clearAllMocks();

    await controller.showAllExplanationResults();
    expect(viewerStub.applyQueryRoles).toHaveBeenCalledWith(ALL_PRIMARY, ["CTX1"]);
    expect(useStore.getState().explanationGroupKey).toBeNull();
  });

  it("never issues a query or LLM call for selection or restoration", async () => {
    const spy = vi.spyOn(api, "query");
    const before = useStore.getState().messages.length;
    await controller.selectExplanationGroup("IfcDoor");
    await controller.showAllExplanationResults();
    expect(spy).not.toHaveBeenCalled();
    // …and the conversation is untouched: no hidden question, no new turn.
    expect(useStore.getState().messages).toHaveLength(before);
  });

  it("refuses a group with no authoritative identities", async () => {
    useStore.setState({
      explanation: explanation({
        groups: [
          { key: "IfcSpace", label: "IfcSpace", exact_count: 3, shown_count: 0,
            truncated: false, global_ids: [] },
        ],
      }),
    });
    await controller.selectExplanationGroup("IfcSpace");
    expect(viewerStub.applyQueryRoles).not.toHaveBeenCalled();
    expect(useStore.getState().explanationGroupKey).toBeNull();
  });
});

// A selectable grouped graph node is a subgroup like any other: the same
// deterministic highlight path, no query and no LLM call (task29 §5.4).
describe("grouped graph node selection", () => {
  const graphExplanation = () =>
    explanation({
      operation: "relationship",
      presentation: "relationship_graph",
      groups: [],
      graph: {
        node_count: 4,
        edge_count: 3,
        description: "4 groups and 3 grouped connections.",
        nodes: [
          { id: "n0", label: "IfcBuildingStorey", role: "seed", ifc_class: "IfcBuildingStorey",
            relationship_class: null, semantic_role: null, endpoint_role: null, entity_count: 1,
            global_ids: ["S1"], global_ids_truncated: false, selectable: false },
          { id: "n1", label: "IfcDoor", role: "endpoint", ifc_class: "IfcDoor",
            relationship_class: "IfcRelContainedInSpatialStructure",
            semantic_role: "containment", endpoint_role: "RelatedElements", entity_count: 5,
            global_ids: ["D1", "D2", "D3", "D4", "D5"], global_ids_truncated: false,
            selectable: true },
          { id: "n2", label: "IfcWindow", role: "endpoint", ifc_class: "IfcWindow",
            relationship_class: "IfcRelContainedInSpatialStructure",
            semantic_role: "containment", endpoint_role: "RelatedElements", entity_count: 4,
            global_ids: ["W1", "W2", "W3", "W4"], global_ids_truncated: false, selectable: true },
          { id: "n3", label: "IfcSpace", role: "endpoint", ifc_class: "IfcSpace",
            relationship_class: "IfcRelContainedInSpatialStructure",
            semantic_role: "containment", endpoint_role: "RelatedElements", entity_count: 3,
            global_ids: [], global_ids_truncated: true, selectable: false },
        ],
        edges: [],
      },
    });

  beforeEach(async () => {
    vi.spyOn(api, "query").mockResolvedValue(
      envelope({ answer_explanation: graphExplanation() }),
    );
    await controller.submitQuestion("what is connected to floor 3?");
    vi.clearAllMocks();
  });

  it("applies the node's authoritative identities and nothing else", async () => {
    await controller.selectExplanationGroup("n1");
    expect(viewerStub.applyQueryRoles).toHaveBeenCalledWith(["D1", "D2", "D3", "D4", "D5"], []);
    expect(useStore.getState().explanationGroupKey).toBe("n1");
  });

  it("refuses the seed node and any node the backend did not mark selectable", async () => {
    await controller.selectExplanationGroup("n0");
    await controller.selectExplanationGroup("n3");
    expect(viewerStub.applyQueryRoles).not.toHaveBeenCalled();
    expect(useStore.getState().explanationGroupKey).toBeNull();
  });

  it("All results restores the exact original primary and context roles", async () => {
    await controller.selectExplanationGroup("n2");
    vi.clearAllMocks();
    await controller.showAllExplanationResults();
    expect(viewerStub.applyQueryRoles).toHaveBeenCalledWith(ALL_PRIMARY, ["CTX1"]);
    expect(useStore.getState().explanationGroupKey).toBeNull();
  });

  it("never issues a query for node selection or restoration", async () => {
    const spy = vi.spyOn(api, "query");
    await controller.selectExplanationGroup("n1");
    await controller.showAllExplanationResults();
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("clearing and retirement", () => {
  beforeEach(async () => {
    vi.spyOn(api, "query").mockResolvedValue(envelope());
    await controller.submitQuestion("q");
    vi.clearAllMocks();
  });

  it("manual close clears the panel and its query-result highlight", async () => {
    await controller.closeExplanation();
    expect(useStore.getState().explanation).toBeNull();
    expect(viewerStub.clearQueryRoles).toHaveBeenCalled();
  });

  it("Clear Chat clears the panel and highlight", async () => {
    await controller.clearChat();
    expect(useStore.getState().explanation).toBeNull();
    expect(viewerStub.clearQueryRoles).toHaveBeenCalled();
  });

  it("Reset App clears the panel and highlight", async () => {
    await controller.resetApp();
    expect(useStore.getState().explanation).toBeNull();
    expect(viewerStub.clearQueryRoles).toHaveBeenCalled();
  });

  it("switching models clears the panel", async () => {
    vi.spyOn(api, "query").mockResolvedValue(envelope());
    await controller.confirmAndLoadModel({
      source_model_id: 2,
      display_name: "M2",
      source_fingerprint: "fp2",
      viewer_asset_status: "ready",
    } as never);
    expect(useStore.getState().explanation).toBeNull();
  });

  it("a component group action that replaces the highlight retires the explanation", async () => {
    useStore.setState({ componentGuid: "G-SUBJECT" });
    vi.spyOn(api, "highlightGroup").mockResolvedValue({
      available: true,
      global_ids: ["T1", "T2"],
      total: 2,
      truncated: false,
      unavailable_reason: null,
    } as never);

    await controller.applyGroupScope("type");

    expect(useStore.getState().explanation).toBeNull();
    expect(viewerStub.applyQueryRoles).toHaveBeenCalledWith(["T1", "T2"], []);
  });

  it("opening the component panel by clicking an object leaves the explanation alone", async () => {
    vi.spyOn(api, "entityDetails").mockResolvedValue({
      source_model_id: 1,
      instance: { global_id: "G9", ifc_class: "IfcDoor", materials: [], quantities: [], properties: [] },
      type: null,
      family: null,
      availability: { instance: true, same_type: false, same_family: false,
        type_unavailable_reason: null, family_unavailable_reason: null },
    } as never);

    await controller.openComponent("G9");

    expect(useStore.getState().explanation).not.toBeNull();
    expect(viewerStub.clearQueryRoles).not.toHaveBeenCalled();
  });
});
