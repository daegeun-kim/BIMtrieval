// The grouped relationship diagram (tasks/task29.md §5.4).
//
// What these tests protect: the diagram states its own counts and directions,
// only backend-declared selectable nodes act on the viewer, overlapping node
// groups are described truthfully, and the layout is stable rather than
// simulated.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AnswerExplanation,
  ExplanationGraph,
  ExplanationGraphNode,
} from "../src/api/types";
import ExplanationPanel from "../src/explain/ExplanationPanel";
import { useStore } from "../src/state/store";

const selectGroup = vi.fn(async () => {});
const showAll = vi.fn(async () => {});
const close = vi.fn(async () => {});
vi.mock("../src/state/controller", () => ({
  controller: {
    selectExplanationGroup: (...a: unknown[]) => selectGroup(...(a as [])),
    showAllExplanationResults: () => showAll(),
    closeExplanation: () => close(),
  },
}));

function node(partial: Partial<ExplanationGraphNode>): ExplanationGraphNode {
  return {
    id: "n1",
    label: "IfcDoor",
    role: "endpoint",
    ifc_class: "IfcDoor",
    relationship_class: "IfcRelContainedInSpatialStructure",
    semantic_role: "containment",
    endpoint_role: "RelatedElements",
    entity_count: 5,
    global_ids: ["D1", "D2", "D3", "D4", "D5"],
    global_ids_truncated: false,
    selectable: true,
    ...partial,
  } as ExplanationGraphNode;
}

function graph(partial: Partial<ExplanationGraph> = {}): ExplanationGraph {
  return {
    node_count: 4,
    edge_count: 3,
    description:
      "4 groups and 3 grouped connections. IfcBuildingStorey (query subject): 1 object(s). " +
      "IfcDoor (endpoint group): 5 object(s). IfcWindow (endpoint group): 4 object(s). " +
      "IfcSpace (endpoint group): 3 object(s).",
    nodes: [
      node({
        id: "n0",
        label: "IfcBuildingStorey",
        role: "seed",
        ifc_class: "IfcBuildingStorey",
        relationship_class: null,
        semantic_role: null,
        endpoint_role: null,
        entity_count: 1,
        global_ids: ["S1"],
        selectable: false,
      }),
      node({ id: "n1" }),
      node({ id: "n2", label: "IfcWindow", ifc_class: "IfcWindow", entity_count: 4,
        global_ids: ["W1", "W2", "W3", "W4"] }),
      node({ id: "n3", label: "IfcSpace", ifc_class: "IfcSpace", entity_count: 3,
        global_ids: [], global_ids_truncated: true, selectable: false }),
    ],
    edges: [
      { id: "e0", source_node_id: "n0", target_node_id: "n1",
        relationship_class: "IfcRelContainedInSpatialStructure",
        semantic_role: "containment", schema_direction: "relating_to_related",
        source_role: "RelatingStructure", target_role: "RelatedElements",
        connection_count: 5, label: "containment" },
      { id: "e1", source_node_id: "n0", target_node_id: "n2",
        relationship_class: "IfcRelContainedInSpatialStructure",
        semantic_role: "containment", schema_direction: "relating_to_related",
        source_role: "RelatingStructure", target_role: "RelatedElements",
        connection_count: 4, label: "containment" },
      { id: "e2", source_node_id: "n0", target_node_id: "n3",
        relationship_class: "IfcRelSpaceBoundary",
        semantic_role: "boundary", schema_direction: "relating_to_related",
        source_role: "RelatingSpace", target_role: "RelatedBuildingElement",
        connection_count: 3, label: "boundary" },
    ],
    ...partial,
  } as ExplanationGraph;
}

function explanation(partial: Partial<AnswerExplanation> = {}): AnswerExplanation {
  return {
    part_id: "p1",
    request_label: "objects connected to floor 3",
    operation: "relationship",
    result_status: "exact",
    presentation: "relationship_graph",
    answer_basis: "graph_traversal",
    interpretation: "objects the third storey contains",
    retrieval_modes: ["graph"],
    exact_total: 12,
    class_breakdown: {},
    distribution: [],
    aggregate: null,
    relationship_endpoint_total: 12,
    graph: graph(),
    presentation_fallback_reason: null,
    chart_unit: null,
    limitation: null,
    known_parts: [],
    unknown_parts: [],
    shown_identity_count: 12,
    true_result_count: 12,
    identities_truncated: false,
    groups: [],
    rows: [],
    ...partial,
  } as AnswerExplanation;
}

function mount(partial: Partial<AnswerExplanation> = {}, groupKey: string | null = null) {
  useStore.setState({ explanation: explanation(partial), explanationGroupKey: groupKey });
  return render(<ExplanationPanel />);
}

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    explanation: null,
    explanationPrimaryGuids: [],
    explanationContextGuids: [],
    explanationGroupKey: null,
  });
});

describe("rendering the grouped diagram", () => {
  it("renders a node-link diagram for a qualifying payload", () => {
    mount();
    expect(screen.getByTestId("ex-graph")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("labels every node with its class and represented entity count", () => {
    mount();
    const canvas = screen.getByTestId("ex-graph-canvas");
    for (const [label, count] of [
      ["IfcBuildingStorey", "1 · subject"],
      ["IfcDoor", "5 object(s)"],
      ["IfcWindow", "4 object(s)"],
      ["IfcSpace", "3 object(s)"],
    ]) {
      expect(within(canvas).getByText(label)).toBeInTheDocument();
      expect(within(canvas).getByText(count)).toBeInTheDocument();
    }
  });

  it("distinguishes the seed node from grouped endpoint nodes", () => {
    mount();
    const seed = screen.getByText("IfcBuildingStorey").closest(".ex-graph-node");
    expect(seed).toHaveClass("ex-graph-node-seed");
    const door = screen.getByText("IfcDoor").closest(".ex-graph-node");
    expect(door).toHaveClass("ex-graph-node-endpoint");
  });

  it("states each edge's meaning, grouped count and recorded direction", () => {
    mount();
    const legend = screen.getByRole("list", { name: /relationship connections/i });
    const rows = within(legend).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    // Direction follows the IFC roles: the relating side is the source.
    expect(rows[0]).toHaveTextContent("IfcBuildingStorey");
    expect(rows[0]).toHaveTextContent("IfcDoor");
    expect(rows[0]).toHaveTextContent("containment");
    expect(rows[0]).toHaveTextContent("5");
    expect(rows[2]).toHaveTextContent("boundary");
  });

  it("provides a textual accessible description of the nodes and edges", () => {
    mount();
    expect(screen.getByTestId("ex-graph-description")).toHaveTextContent(
      /4 groups and 3 grouped connections/,
    );
  });

  it("draws one path per declared edge, with an arrowhead for direction", () => {
    const { container } = mount();
    expect(container.querySelectorAll("path.ex-graph-edge")).toHaveLength(3);
    for (const path of container.querySelectorAll("path.ex-graph-edge")) {
      expect(path.getAttribute("marker-end")).toBe("url(#ex-graph-arrow)");
    }
  });

  it("lays out deterministically — the same payload renders identically twice", () => {
    const first = mount();
    const a = first.container.querySelector(".ex-graph-canvas")?.innerHTML;
    first.unmount();
    const second = mount();
    const b = second.container.querySelector(".ex-graph-canvas")?.innerHTML;
    expect(a).toBe(b);
  });

  it("keeps the diagram inside its own scroll area", () => {
    const { container } = mount();
    expect(container.querySelector(".ex-graph-scroll")).toBeInTheDocument();
  });
});

describe("node selection (§5.4)", () => {
  it("a selectable node is a focusable button that applies its subgroup", async () => {
    mount();
    const door = screen.getByRole("button", { name: /IfcDoor, 5 objects/ });
    door.focus();
    expect(door).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(selectGroup).toHaveBeenCalledWith("n1");
  });

  it("the active node is accessibly marked", () => {
    mount({}, "n1");
    expect(screen.getByRole("button", { name: /IfcDoor, 5 objects/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("a node without selectable identities is informative but not a control", () => {
    mount();
    expect(screen.queryByRole("button", { name: /IfcSpace/ })).not.toBeInTheDocument();
    expect(screen.getByText("IfcSpace")).toBeInTheDocument();
    // …and neither is the seed.
    expect(screen.queryByRole("button", { name: /IfcBuildingStorey/ })).not.toBeInTheDocument();
  });

  it("selecting a node updates the information region", () => {
    mount({}, "n1");
    expect(screen.getByTestId("ex-showing")).toHaveTextContent("IfcDoor");
    expect(screen.getByTestId("ex-highlighted")).toHaveTextContent(
      "5 of 12 query-result objects",
    );
    expect(screen.getByTestId("ex-full-result")).toHaveTextContent("Full result: 12");
  });

  it("says overlapping node groups are not a disjoint remainder", () => {
    mount({}, "n1");
    expect(screen.getByTestId("ex-overlap-note")).toHaveTextContent(
      /groups can share objects/i,
    );
  });

  it("discloses a capped node selection instead of implying the whole group", () => {
    mount(
      {
        graph: graph({
          nodes: [
            node({ id: "n0", label: "IfcBuildingStorey", role: "seed", entity_count: 1,
              global_ids: ["S1"], selectable: false }),
            node({ id: "n1", entity_count: 900, global_ids: ["D1", "D2"],
              global_ids_truncated: true }),
            node({ id: "n2", label: "IfcWindow", entity_count: 4,
              global_ids: ["W1", "W2", "W3", "W4"] }),
            node({ id: "n3", label: "IfcSpace", entity_count: 3, global_ids: [],
              selectable: false }),
          ],
        }),
      },
      "n1",
    );
    expect(screen.getByTestId("ex-truncation")).toHaveTextContent(/2 of 900 objects/);
  });

  it("All results restores the full result from the card", async () => {
    mount({}, "n2");
    await userEvent.click(screen.getByRole("button", { name: "All results" }));
    expect(showAll).toHaveBeenCalled();
  });
});

describe("the information region accompanies the diagram (§6)", () => {
  it("is present, and never replaced by the diagram", () => {
    mount();
    const info = screen.getByLabelText("What is shown");
    expect(within(info).getByText("objects connected to floor 3")).toBeInTheDocument();
    expect(within(info).getByText(/Relationship · exact/)).toBeInTheDocument();
    expect(within(info).getByText(/relationship traversal/)).toBeInTheDocument();
  });

  it("carries no fallback note while the diagram qualifies", () => {
    mount();
    expect(screen.queryByTestId("ex-fallback")).not.toBeInTheDocument();
  });
});
