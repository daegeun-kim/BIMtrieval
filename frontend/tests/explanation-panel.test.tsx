// The Query Explanation card: presentation rendering, the persistent
// information region, subgroup selection, and the fixed stacked layout
// (tasks/task29.md §3, §4, §6, §7; tasks/task26.md §3, §4, §5).
//
// The card renders only what the backend declared. Task 29 left it three
// families — bounded table, horizontal bars, grouped diagram — and removed the
// metric, aggregate and partial-split visuals, so a payload never arrives for a
// scalar answer at all (see `explanation-gate.test.tsx` for that half).
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AnswerExplanation } from "../src/api/types";
import ExplanationPanel from "../src/explain/ExplanationPanel";
import {
  EXPLAIN_COLUMN_PAIRED_VW,
  EXPLAIN_COLUMN_VW,
  effectiveViewportObstructionPx,
  explanationColumnWidthPx,
  useStore,
} from "../src/state/store";

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
    graph: null,
    presentation_fallback_reason: null,
    chart_unit: null,
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
    rows: [
      { global_id: "D1", ifc_class: "IfcDoor", name: "Door A", storey_name: "Floor 3" },
      { global_id: "D2", ifc_class: "IfcDoor", name: null, storey_name: null },
    ],
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

describe("table presentations (§3)", () => {
  it.each(["count", "list"])("%s renders a bounded scrollable result table", (operation) => {
    mount({ operation, presentation: "result_table", true_result_count: 9 });
    const table = screen.getByRole("table");
    expect(within(table).getByText("Door A")).toBeInTheDocument();
    // GlobalId is the final identity fallback.
    expect(within(table).getByText("D2")).toBeInTheDocument();
  });

  it("discloses shown-versus-true totals whenever the table is capped", () => {
    // Both listable rows are displayed, but the real result is larger — the
    // caption must name the true total so the list cannot read as exhaustive
    // (task31 §4.2).
    mount({ true_result_count: 9 });
    expect(
      screen.getByText(/showing all 2 listed objects; 9 results in total/i),
    ).toBeInTheDocument();
  });

  it("never implies a capped table is exhaustive", () => {
    mount({ true_result_count: 2 });
    expect(screen.getByText(/^2 results$/i)).toBeInTheDocument();
  });

  it("a one-bucket distribution renders a table, not a single bar", () => {
    mount({
      operation: "group_distribution",
      presentation: "group_table",
      distribution: [{ key: "Floor 1", count: 120, value: null }],
      groups: [],
      rows: [],
    });
    const table = screen.getByRole("table");
    expect(within(table).getByText("Floor 1")).toBeInTheDocument();
    expect(within(table).getByText("120")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: /distribution/i })).not.toBeInTheDocument();
  });

  it("a heterogeneous comparison renders a comparison table with its values", () => {
    mount({
      operation: "comparison",
      presentation: "comparison_table",
      distribution: [
        { key: "Floor 1", count: 2, value: 120 },
        { key: "Floor 2", count: 2, value: null },
      ],
      groups: [],
      rows: [],
    });
    const table = screen.getByRole("table");
    expect(within(table).getByText("Comparison")).toBeInTheDocument();
    expect(within(table).getByText("120")).toBeInTheDocument();
    expect(within(table).getByText("—")).toBeInTheDocument();
  });

  it("a relationship fallback renders the endpoint table and states the reason", () => {
    mount({
      operation: "relationship",
      presentation: "relationship_table",
      presentation_fallback_reason:
        "this relationship result is too large for the bounded diagram",
      relationship_endpoint_total: 2,
      groups: [],
      rows: [
        { global_id: "R1", ifc_class: "IfcSpace", name: "Office", storey_name: null },
        { global_id: "R2", ifc_class: "IfcSpace", name: "Hall", storey_name: null },
      ],
      true_result_count: 2,
    });
    expect(screen.getByText("Office")).toBeInTheDocument();
    expect(screen.getByTestId("ex-fallback")).toHaveTextContent(/too large for the bounded/i);
    expect(screen.queryByTestId("ex-graph")).not.toBeInTheDocument();
  });
});

describe("horizontal bar chart (§4)", () => {
  it("a multi-bucket distribution renders bars with exact labels and counts", () => {
    mount({
      operation: "group_distribution",
      presentation: "bar_chart",
      distribution: [
        { key: "Floor 1", count: 120, value: null },
        { key: "Floor 2", count: 61, value: null },
      ],
      groups: [],
      rows: [],
    });
    const list = screen.getByRole("list", { name: /distribution/i });
    expect(within(list).getByText("Floor 1")).toBeInTheDocument();
    expect(within(list).getByText("120")).toBeInTheDocument();
    expect(within(list).getByText("Floor 2")).toBeInTheDocument();
    expect(within(list).getByText("61")).toBeInTheDocument();
  });

  it("a homogeneous numeric comparison renders its exact values and unit", () => {
    mount({
      operation: "comparison",
      presentation: "bar_chart",
      chart_unit: "m2",
      distribution: [
        { key: "Floor 1", count: 2, value: 120.5 },
        { key: "Floor 2", count: 2, value: 61 },
      ],
      groups: [],
      rows: [],
    });
    const list = screen.getByRole("list", { name: /distribution/i });
    expect(within(list).getByText("120.5 m2")).toBeInTheDocument();
    expect(within(list).getByText("61 m2")).toBeInTheDocument();
  });

  it("a distribution bucket is never selectable", () => {
    mount({
      operation: "group_distribution",
      presentation: "bar_chart",
      distribution: [
        { key: "Floor 1", count: 120, value: null },
        { key: "Floor 2", count: 4, value: null },
      ],
      groups: [],
      rows: [],
    });
    const list = screen.getByRole("list", { name: /distribution/i });
    expect(within(list).queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("the persistent information region (§6)", () => {
  it("is present for every presentation — a chart, table or diagram never appears alone", () => {
    for (const presentation of [
      "result_table",
      "group_table",
      "comparison_table",
      "relationship_table",
      "bar_chart",
      "relationship_graph",
    ] as const) {
      const { unmount } = mount({ presentation });
      expect(screen.getByLabelText("What is shown")).toBeInTheDocument();
      expect(screen.getByTestId("ex-showing")).toBeInTheDocument();
      unmount();
    }
  });

  it("states the question part, the interpretation, the status and the basis", () => {
    mount();
    const info = screen.getByLabelText("What is shown");
    expect(within(info).getByText("external doors on floor 3")).toBeInTheDocument();
    expect(
      within(info).getByText("doors whose storey is the third elevation band"),
    ).toBeInTheDocument();
    expect(within(info).getByText(/Count · exact/)).toBeInTheDocument();
    expect(within(info).getByText(/exact structured query/)).toBeInTheDocument();
  });

  it("distinguishes a selected subgroup from the full answer", () => {
    mount({}, "IfcDoor");
    expect(screen.getByTestId("ex-showing")).toHaveTextContent("IfcDoor");
    expect(screen.getByTestId("ex-highlighted")).toHaveTextContent(
      "5 of 9 query-result objects",
    );
    expect(screen.getByTestId("ex-full-result")).toHaveTextContent(
      "Full result: 9 · external doors on floor 3",
    );
  });

  it("says All results with the full count when no subgroup is active", () => {
    mount();
    expect(screen.getByTestId("ex-showing")).toHaveTextContent("All results");
    expect(screen.getByTestId("ex-highlighted")).toHaveTextContent("9 query-result objects");
  });

  it("discloses truncation rather than implying the shown objects are exhaustive", () => {
    mount({ shown_identity_count: 2000, true_result_count: 1981 + 2000,
      identities_truncated: true });
    expect(screen.getByTestId("ex-truncation")).toHaveTextContent(/2,000 of 3,981/);
  });

  it("shows the limitation when the result carries one", () => {
    mount({ limitation: "fire rating is recorded on only some doors" });
    expect(
      screen.getByText("fire rating is recorded on only some doors"),
    ).toBeInTheDocument();
  });

  it("shows partial known/unknown information without a partial visual", () => {
    mount({
      result_status: "partial",
      presentation: "result_table",
      known_parts: ["door count"],
      unknown_parts: ["fire rating"],
    });
    const info = screen.getByLabelText("What is shown");
    expect(within(info).getByText("door count")).toBeInTheDocument();
    expect(within(info).getByText("fire rating")).toBeInTheDocument();
    // The base operation's presentation is unchanged by partial status.
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});

describe("group selection and All results (§3, §7)", () => {
  it("clicking a group applies it and marks it active", async () => {
    mount();
    await userEvent.click(screen.getByRole("listitem", { name: /IfcDoor/ }));
    expect(selectGroup).toHaveBeenCalledWith("IfcDoor");
  });

  it("the active group is visually and accessibly marked", () => {
    mount({}, "IfcDoor");
    expect(screen.getByRole("listitem", { name: /IfcDoor/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("All results appears only while a subgroup is active", async () => {
    const { unmount } = mount();
    expect(screen.queryByRole("button", { name: "All results" })).not.toBeInTheDocument();
    unmount();

    mount({}, "IfcWindow");
    await userEvent.click(screen.getByRole("button", { name: "All results" }));
    expect(showAll).toHaveBeenCalled();
  });

  it("a group with no authoritative identities is shown but not selectable", () => {
    mount({
      groups: [
        { key: "IfcDoor", label: "IfcDoor", exact_count: 5, shown_count: 5, truncated: false,
          global_ids: ["D1"] },
        { key: "IfcSpace", label: "IfcSpace", exact_count: 3, shown_count: 0, truncated: false,
          global_ids: [] },
      ],
    });
    expect(screen.getByRole("listitem", { name: /IfcSpace/ })).toBeDisabled();
    expect(screen.getByRole("listitem", { name: /IfcDoor/ })).toBeEnabled();
  });

  it("a single-class result shows no class bars at all", () => {
    mount({ groups: [] });
    expect(screen.queryByRole("list", { name: /breakdown by class/i })).not.toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("has a close control that is reachable by keyboard", async () => {
    mount();
    const closeBtn = screen.getByRole("button", { name: /close query explanation/i });
    closeBtn.focus();
    await userEvent.keyboard("{Enter}");
    expect(close).toHaveBeenCalled();
  });
});

describe("fixed stacked layout geometry (§7)", () => {
  it("is 40% of the viewport alone and 32% beside the component panel", () => {
    expect(explanationColumnWidthPx(1600, false)).toBe(Math.round(1600 * EXPLAIN_COLUMN_VW));
    expect(explanationColumnWidthPx(1600, true)).toBe(
      Math.round(1600 * EXPLAIN_COLUMN_PAIRED_VW),
    );
    expect(explanationColumnWidthPx(1600, true)).toBeLessThan(
      explanationColumnWidthPx(1600, false),
    );
  });

  it("feeds the one obstruction calculation, which grows for the component panel", () => {
    const alone = effectiveViewportObstructionPx(explanationColumnWidthPx(1600, false), false);
    const paired = effectiveViewportObstructionPx(explanationColumnWidthPx(1600, true), true);
    expect(alone).toBe(20 + 640);
    expect(paired).toBe(20 + 512 + 12 + 320);
  });
});
