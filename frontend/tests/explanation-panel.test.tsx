// The Query Explanation card: presentation choice, the persistent information
// region, group selection, and the fixed stacked layout (tasks/task26.md §3,
// §4, §5, §7).
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
    presentation: "metric",
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

describe("presentation selection (§4.1)", () => {
  it("count renders a headline metric", () => {
    mount({ presentation: "metric", operation: "count" });
    expect(screen.getByTestId("ex-metric")).toHaveTextContent("9");
  });

  it("list renders a bounded result table", () => {
    mount({
      presentation: "table",
      operation: "list",
      rows: [
        { global_id: "D1", ifc_class: "IfcDoor", name: "Door A", storey_name: "Floor 3" },
        { global_id: "D2", ifc_class: "IfcDoor", name: null, storey_name: null },
      ],
      true_result_count: 9,
    });
    const table = screen.getByRole("table");
    expect(within(table).getByText("Door A")).toBeInTheDocument();
    expect(within(table).getByText("D2")).toBeInTheDocument();
    expect(within(table).getByText(/2 of 9 results/i)).toBeInTheDocument();
  });

  it("group distribution renders bars from the existing buckets", () => {
    mount({
      presentation: "distribution",
      operation: "group_distribution",
      distribution: [
        { key: "Floor 1", count: 120, value: null },
        { key: "Floor 2", count: 61, value: null },
      ],
    });
    const list = screen.getByRole("list", { name: /distribution/i });
    expect(within(list).getByText("Floor 1")).toBeInTheDocument();
    expect(within(list).getByText("120")).toBeInTheDocument();
  });

  it("aggregate renders the value, unit, and matched/coverage information", () => {
    mount({
      presentation: "aggregate",
      operation: "aggregate",
      aggregate: { function: "sum", value: 812.5, unit: "m2", matched_count: 205,
        coverage_count: 180, complete: false },
    });
    expect(screen.getByTestId("ex-aggregate")).toHaveTextContent("812.5");
    expect(screen.getByTestId("ex-aggregate")).toHaveTextContent("m2");
    expect(screen.getByText(/180 of 205 matched/i)).toBeInTheDocument();
  });

  it("relationship renders the endpoint count and a bounded endpoint table", () => {
    mount({
      presentation: "relationship",
      operation: "relationship",
      relationship_endpoint_total: 2,
      rows: [
        { global_id: "R1", ifc_class: "IfcSpace", name: "Office", storey_name: null },
        { global_id: "R2", ifc_class: "IfcSpace", name: "Hall", storey_name: null },
      ],
    });
    expect(screen.getByTestId("ex-endpoints")).toHaveTextContent("2");
    expect(screen.getByText("Office")).toBeInTheDocument();
  });

  it("partial renders the known/unknown split", () => {
    mount({
      presentation: "partial",
      result_status: "partial",
      known_parts: ["door count"],
      unknown_parts: ["fire rating"],
    });
    expect(screen.getAllByText("door count").length).toBeGreaterThan(0);
    expect(screen.getAllByText("fire rating").length).toBeGreaterThan(0);
  });
});

describe("the persistent information region (§4)", () => {
  it("is present for every presentation — a chart or table never appears alone", () => {
    for (const presentation of ["metric", "table", "distribution", "aggregate",
      "relationship", "partial"] as const) {
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
});

describe("group selection and All results (§5)", () => {
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

  it("a distribution bucket is never a button", () => {
    mount({
      presentation: "distribution",
      operation: "group_distribution",
      distribution: [{ key: "Floor 1", count: 120, value: null }],
      groups: [],
    });
    const list = screen.getByRole("list", { name: /distribution/i });
    expect(within(list).queryByRole("button")).not.toBeInTheDocument();
  });

  it("has a close control that is reachable by keyboard", async () => {
    mount();
    const closeBtn = screen.getByRole("button", { name: /close query explanation/i });
    closeBtn.focus();
    await userEvent.keyboard("{Enter}");
    expect(close).toHaveBeenCalled();
  });
});

describe("fixed stacked layout geometry (§3)", () => {
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
