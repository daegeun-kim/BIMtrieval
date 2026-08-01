// Progressive display and three-state sorting in the Query Explanation object
// tables (tasks/task31.md §4, §8.2).
//
// The API client and the viewer are mocked so any backend or LLM call would be
// observable — scrolling and sorting must make none.
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const viewerStub = vi.hoisted(() => ({
  setCallbacks: vi.fn(),
  init: vi.fn(async () => {}),
  hasModel: vi.fn(() => true),
  applyQueryRoles: vi.fn(async (): Promise<{ missing: string[] }> => ({ missing: [] })),
  clearQueryRoles: vi.fn(async () => {}),
  fitToGuids: vi.fn(async (): Promise<{ missing: string[] }> => ({ missing: [] })),
  unloadModel: vi.fn(async () => {}),
  clearManualSelection: vi.fn(),
  exitPlanMode: vi.fn(async () => {}),
  setVisualizationMode: vi.fn(async () => {}),
  dispose: vi.fn(),
}));
vi.mock("../src/viewer/ViewerAdapter", () => ({ ViewerAdapter: vi.fn(() => viewerStub) }));

import type { AnswerExplanation, ExplanationRow } from "../src/api/types";
import ExplanationPanel from "../src/explain/ExplanationPanel";
import {
  ROW_PAGE_SIZE,
  ariaSortFor,
  nextRowSort,
  rowTableCaption,
  sortRows,
  type RowSort,
} from "../src/explain/explanation";
import { api } from "../src/api/client";
import { useStore } from "../src/state/store";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** `count` rows, deliberately NOT in any sorted order, with stable identities. */
function rows(count: number): ExplanationRow[] {
  return Array.from({ length: count }, (_, i) => ({
    global_id: `G${String(i).padStart(4, "0")}`,
    ifc_class: i % 2 === 0 ? "IfcDoor" : "IfcWindow",
    name: `Object ${((count - i) * 7) % count}`,
    storey_name: `Floor ${(i % 3) + 1}`,
  }));
}

function explanation(partial: Partial<AnswerExplanation> = {}): AnswerExplanation {
  return {
    part_id: "p1",
    request_label: "doors",
    operation: "count",
    result_status: "exact",
    presentation: "result_table",
    answer_basis: "exact_sql",
    interpretation: null,
    retrieval_modes: ["sql"],
    exact_total: 120,
    class_breakdown: {},
    distribution: [],
    aggregate: null,
    relationship_endpoint_total: null,
    graph: null,
    presentation_fallback_reason: null,
    chart_unit: null,
    limitation: null,
    known_parts: [],
    unknown_parts: [],
    shown_identity_count: 120,
    true_result_count: 120,
    identities_truncated: false,
    groups: [],
    rows: rows(120),
    ...partial,
  } as AnswerExplanation;
}

function mount(partial: Partial<AnswerExplanation> = {}) {
  useStore.setState({ explanation: explanation(partial), explanationGroupKey: null });
  return render(<ExplanationPanel />);
}

function scroller(): HTMLElement {
  return screen.getByTestId("ex-table-scroll");
}

/** Drive the container to its scroll end, as a real wheel/drag would. */
function scrollToEnd(): void {
  const el = scroller();
  Object.defineProperty(el, "scrollHeight", { value: 4000, configurable: true });
  Object.defineProperty(el, "clientHeight", { value: 400, configurable: true });
  Object.defineProperty(el, "scrollTop", { value: 3600, configurable: true, writable: true });
  fireEvent.scroll(el);
}

/** A scroll that does NOT reach the end. */
function scrollPartway(): void {
  const el = scroller();
  Object.defineProperty(el, "scrollHeight", { value: 4000, configurable: true });
  Object.defineProperty(el, "clientHeight", { value: 400, configurable: true });
  Object.defineProperty(el, "scrollTop", { value: 100, configurable: true, writable: true });
  fireEvent.scroll(el);
}

function bodyRowCount(): number {
  return within(screen.getByRole("table")).getAllByRole("row").length - 1; // minus header
}

function objectCells(): string[] {
  return within(screen.getByRole("table"))
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.querySelectorAll("td")[0]!.textContent ?? "");
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

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

describe("sort-cycle and caption helpers (task31 §4.2, §4.3)", () => {
  it("cycles descending, ascending, original for one column", () => {
    let sort: RowSort | null = null;
    sort = nextRowSort(sort, "object");
    expect(sort).toEqual({ column: "object", direction: "desc" });
    sort = nextRowSort(sort, "object");
    expect(sort).toEqual({ column: "object", direction: "asc" });
    sort = nextRowSort(sort, "object");
    expect(sort).toBeNull();
  });

  it("starts a different column at descending, discarding the previous state", () => {
    const sort = nextRowSort({ column: "object", direction: "asc" }, "class");
    expect(sort).toEqual({ column: "class", direction: "desc" });
  });

  it("maps the state to aria-sort", () => {
    expect(ariaSortFor(null, "class")).toBe("none");
    expect(ariaSortFor({ column: "class", direction: "desc" }, "class")).toBe("descending");
    expect(ariaSortFor({ column: "class", direction: "asc" }, "class")).toBe("ascending");
    expect(ariaSortFor({ column: "class", direction: "asc" }, "storey")).toBe("none");
  });

  it("keeps missing values last in BOTH directions and never mutates the input", () => {
    const source: ExplanationRow[] = [
      { global_id: "A", ifc_class: "IfcDoor", name: "A", storey_name: "Floor 2" },
      { global_id: "B", ifc_class: "IfcDoor", name: "B", storey_name: null },
      { global_id: "C", ifc_class: "IfcDoor", name: "C", storey_name: "Floor 1" },
      { global_id: "D", ifc_class: "IfcDoor", name: "D", storey_name: "   " },
    ];
    const snapshot = [...source];
    for (const direction of ["asc", "desc"] as const) {
      const out = sortRows(source, { column: "storey", direction });
      expect(out.slice(-2).map((r) => r.global_id)).toEqual(["B", "D"]); // missing last
      expect(out).toHaveLength(4);
    }
    expect(source).toEqual(snapshot);
  });

  it("restores the exact original order when the sort is cancelled", () => {
    const source = rows(12);
    expect(sortRows(source, null)).toEqual(source);
  });

  it("breaks ties by the original order, deterministically", () => {
    const source: ExplanationRow[] = [
      { global_id: "Z", ifc_class: "IfcDoor", name: "Same", storey_name: null },
      { global_id: "Y", ifc_class: "IfcDoor", name: "Same", storey_name: null },
      { global_id: "X", ifc_class: "IfcDoor", name: "Same", storey_name: null },
    ];
    for (const direction of ["asc", "desc"] as const) {
      expect(sortRows(source, { column: "object", direction }).map((r) => r.global_id)).toEqual([
        "Z",
        "Y",
        "X",
      ]);
    }
  });

  it("sorts the Object column on the GlobalId fallback when no name exists", () => {
    const source: ExplanationRow[] = [
      { global_id: "B", ifc_class: "IfcDoor", name: null, storey_name: null },
      { global_id: "A", ifc_class: "IfcDoor", name: null, storey_name: null },
    ];
    expect(sortRows(source, { column: "object", direction: "asc" }).map((r) => r.global_id)).toEqual(
      ["A", "B"],
    );
  });

  it("distinguishes displayed, available and true totals whenever they differ", () => {
    // All three differ: the caption must name all three.
    expect(rowTableCaption(50, 2000, 5000)).toBe(
      "Showing 50 of 2,000 listed objects; 5,000 results in total",
    );
    // Available is capped but fully displayed — never "2,000 results".
    expect(rowTableCaption(2000, 2000, 5000)).toBe(
      "Showing all 2,000 listed objects; 5,000 results in total",
    );
    // Nothing was capped: displayed < available.
    expect(rowTableCaption(50, 120, 120)).toBe("Showing 50 of 120 results");
    // Everything displayed and nothing capped.
    expect(rowTableCaption(120, 120, 120)).toBe("120 results");
  });

  it("never lets an available count pass for the complete result", () => {
    expect(rowTableCaption(2000, 2000, 5000)).toContain("5,000 results in total");
    expect(rowTableCaption(2000, 2000, 5000)).not.toMatch(/^2,000 results$/);
  });
});

// ---------------------------------------------------------------------------
// Progressive display
// ---------------------------------------------------------------------------

describe("progressive display (task31 §4.2)", () => {
  it("renders the first 50 rows initially", () => {
    mount();
    expect(ROW_PAGE_SIZE).toBe(50);
    expect(bodyRowCount()).toBe(50);
  });

  it("appends exactly the next 50 on each end-of-scroll", () => {
    mount();
    scrollToEnd();
    expect(bodyRowCount()).toBe(100);
    scrollToEnd();
    expect(bodyRowCount()).toBe(120); // stops at the available count
    scrollToEnd();
    expect(bodyRowCount()).toBe(120); // and stays there
  });

  it("appends nothing for a scroll that has not reached the end", () => {
    mount();
    scrollPartway();
    expect(bodyRowCount()).toBe(50);
  });

  it("shows every available row with no Load more button", () => {
    mount();
    expect(screen.queryByRole("button", { name: /load more|show more/i })).toBeNull();
    scrollToEnd();
    scrollToEnd();
    expect(bodyRowCount()).toBe(120);
  });

  it("keeps the table inside its own bounded scroll area", () => {
    mount();
    // The scroll container is the table wrap, not the panel: appending rows
    // cannot grow the explanation card.
    expect(scroller()).toHaveClass("ex-table-wrap");
    expect(scroller().querySelector("table")).not.toBeNull();
  });

  it("updates the caption as more rows are displayed", () => {
    mount();
    expect(screen.getByText("Showing 50 of 120 results")).toBeInTheDocument();
    scrollToEnd();
    expect(screen.getByText("Showing 100 of 120 results")).toBeInTheDocument();
    scrollToEnd();
    expect(screen.getByText("120 results")).toBeInTheDocument();
  });

  it("names the true total when the identity set is capped", () => {
    mount({ rows: rows(80), true_result_count: 5000, identities_truncated: true });
    expect(
      screen.getByText("Showing 50 of 80 listed objects; 5,000 results in total"),
    ).toBeInTheDocument();
  });

  it("issues no backend or LLM request while scrolling", () => {
    const query = vi.spyOn(api, "query");
    mount();
    scrollToEnd();
    scrollToEnd();
    expect(query).not.toHaveBeenCalled();
    expect(viewerStub.applyQueryRoles).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Three-state sorting
// ---------------------------------------------------------------------------

describe("three-state column sorting (task31 §4.3)", () => {
  function header(name: string): HTMLElement {
    return within(screen.getByRole("table")).getByRole("columnheader", { name: new RegExp(name, "i") });
  }
  function sortButton(name: string): HTMLElement {
    return within(header(name)).getByRole("button");
  }

  it("turns every column header into a sort button", () => {
    mount();
    for (const label of ["Object", "Class", "Storey"]) {
      expect(sortButton(label)).toBeInTheDocument();
      expect(header(label)).toHaveAttribute("aria-sort", "none");
    }
  });

  it("cycles descending, ascending, original on repeated clicks", async () => {
    const user = userEvent.setup();
    mount();
    const original = objectCells();

    await user.click(sortButton("Object"));
    expect(header("Object")).toHaveAttribute("aria-sort", "descending");
    const desc = objectCells();

    await user.click(sortButton("Object"));
    expect(header("Object")).toHaveAttribute("aria-sort", "ascending");
    const asc = objectCells();
    expect(asc).not.toEqual(desc);

    await user.click(sortButton("Object"));
    expect(header("Object")).toHaveAttribute("aria-sort", "none");
    expect(objectCells()).toEqual(original);
  });

  it("sorts rows that are not yet displayed, not merely the mounted 50", async () => {
    const user = userEvent.setup();
    mount();
    const before = new Set(objectCells());
    await user.click(sortButton("Object"));
    const after = objectCells();
    // The descending top-50 must include names that were beyond the first page.
    expect(after.some((name) => !before.has(name))).toBe(true);
  });

  it("returns the display to the first 50 rows and scrolls to the top", async () => {
    const user = userEvent.setup();
    mount();
    scrollToEnd();
    expect(bodyRowCount()).toBe(100);
    const el = scroller();
    await user.click(sortButton("Class"));
    expect(bodyRowCount()).toBe(50);
    expect(el.scrollTop).toBe(0);
  });

  it("starts another column at descending and clears the prior column's state", async () => {
    const user = userEvent.setup();
    mount();
    await user.click(sortButton("Object"));
    await user.click(sortButton("Object")); // now ascending
    expect(header("Object")).toHaveAttribute("aria-sort", "ascending");

    await user.click(sortButton("Storey"));
    expect(header("Storey")).toHaveAttribute("aria-sort", "descending");
    expect(header("Object")).toHaveAttribute("aria-sort", "none");
  });

  it("keeps rows with no storey last in both directions", async () => {
    const user = userEvent.setup();
    const source: ExplanationRow[] = [
      { global_id: "A", ifc_class: "IfcDoor", name: "A", storey_name: "Floor 1" },
      { global_id: "B", ifc_class: "IfcDoor", name: "B", storey_name: null },
      { global_id: "C", ifc_class: "IfcDoor", name: "C", storey_name: "Floor 2" },
    ];
    mount({ rows: source, true_result_count: 3 });
    const storeys = () =>
      within(screen.getByRole("table"))
        .getAllByRole("row")
        .slice(1)
        .map((r) => r.querySelectorAll("td")[2]!.textContent);

    await user.click(sortButton("Storey"));
    expect(storeys().at(-1)).toBe("—");
    await user.click(sortButton("Storey"));
    expect(storeys().at(-1)).toBe("—");
  });

  it("is operable from the keyboard", async () => {
    const user = userEvent.setup();
    mount();
    sortButton("Class").focus();
    await user.keyboard("{Enter}");
    expect(header("Class")).toHaveAttribute("aria-sort", "descending");
    await user.keyboard(" ");
    expect(header("Class")).toHaveAttribute("aria-sort", "ascending");
  });

  it("issues no backend or LLM request while sorting", async () => {
    const user = userEvent.setup();
    const query = vi.spyOn(api, "query");
    mount();
    await user.click(sortButton("Object"));
    await user.click(sortButton("Class"));
    expect(query).not.toHaveBeenCalled();
    expect(viewerStub.applyQueryRoles).not.toHaveBeenCalled();
  });

  it("resets to page one and original order when a newer answer replaces the payload", async () => {
    const user = userEvent.setup();
    mount();
    scrollToEnd();
    await user.click(sortButton("Object"));
    expect(header("Object")).toHaveAttribute("aria-sort", "descending");

    // A newer qualifying result replaces the card outright.
    act(() => {
      useStore.setState({ explanation: explanation({ request_label: "windows" }) });
    });
    expect(header("Object")).toHaveAttribute("aria-sort", "none");
    expect(bodyRowCount()).toBe(50);
  });
});

// ---------------------------------------------------------------------------
// Boundaries that must NOT move
// ---------------------------------------------------------------------------

describe("unchanged boundaries (task31 §4.1)", () => {
  it("leaves the relationship endpoint fallback table on the same progressive path", () => {
    mount({ presentation: "relationship_table", operation: "relationship" });
    expect(bodyRowCount()).toBe(50);
    scrollToEnd();
    expect(bodyRowCount()).toBe(100);
  });

  it("does not paginate or sort a one-bucket group table", () => {
    mount({
      operation: "group_distribution",
      presentation: "group_table",
      distribution: [{ key: "Floor 1", count: 120, value: null }],
      rows: [],
      groups: [],
    });
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(2); // header + one bucket
    expect(within(table).queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByTestId("ex-table-scroll")).toBeNull();
  });

  it("does not paginate or sort a comparison table", () => {
    mount({
      operation: "comparison",
      presentation: "comparison_table",
      distribution: [
        { key: "Floor 1", count: 3, value: null },
        { key: "Floor 2", count: 5, value: null },
      ],
      rows: [],
      groups: [],
    });
    expect(within(screen.getByRole("table")).queryAllByRole("button")).toHaveLength(0);
  });

  it("keeps the exact result total and the identity cap disclosure intact", () => {
    mount({
      rows: rows(2000),
      shown_identity_count: 2000,
      true_result_count: 7431,
      identities_truncated: true,
    });
    // The 2,000-identity cap still bounds the row list, and the exact total is
    // still reported independently of it — in the caption and in the panel's
    // own truncation note.
    expect(screen.getByText(/Showing 50 of 2,000 listed objects; 7,431 results in total/)).
      toBeInTheDocument();
    expect(screen.getByTestId("ex-truncation").textContent).toMatch(
      /Highlighting 2,000 of 7,431 matching objects/,
    );
    expect(useStore.getState().explanation!.true_result_count).toBe(7431);
    expect(useStore.getState().explanation!.rows!.length).toBe(2000);
  });
});
