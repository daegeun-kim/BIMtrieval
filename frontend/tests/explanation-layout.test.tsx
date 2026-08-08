// The fixed 60/40 stacked right column and its interaction with the existing
// component-detail panel (Task 26 §3, §7).
import { act, render, screen } from "@testing-library/react";
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
  fitToGuids: vi.fn(async () => ({ missing: [] })),
  applyQueryRoles: vi.fn(async () => ({ missing: [] })),
  clearQueryRoles: vi.fn(async () => {}),
  clearManualSelection: vi.fn(),
  removeManualSelection: vi.fn(),
  setSelectionEnabled: vi.fn(),
  setViewportObstruction: vi.fn(),
  dispose: vi.fn(),
}));

vi.mock("../src/viewer/ViewerAdapter", () => ({ ViewerAdapter: vi.fn(() => viewerStub) }));
vi.mock("../src/viewer/ViewerCanvas", () => ({ default: () => <div data-testid="viewer" /> }));
vi.mock("../src/components/ComponentPreview", () => ({
  default: () => <div data-testid="component-preview" />,
}));

import App from "../src/App";
import type { AnswerExplanation } from "../src/api/types";
import { api } from "../src/api/client";
import {
  EXPLAIN_COLUMN_PAIRED_VW,
  EXPLAIN_COLUMN_VW,
  effectiveViewportObstructionPx,
  useStore,
} from "../src/state/store";

vi.spyOn(api, "listModels").mockResolvedValue({ models: [] } as never);
vi.spyOn(api, "entityDetails").mockResolvedValue({
  source_model_id: 1,
  instance: { global_id: "G9", ifc_class: "IfcDoor", materials: [], quantities: [], properties: [] },
  type: null,
  family: null,
  availability: { instance: true, same_type: false, same_family: false,
    type_unavailable_reason: null, family_unavailable_reason: null },
} as never);

const EXPLANATION = {
  part_id: "p1",
  request_label: "external doors on floor 3",
  operation: "count",
  result_status: "exact",
  presentation: "result_table",
  answer_basis: "exact_sql",
  interpretation: null,
  retrieval_modes: ["sql"],
  exact_total: 9,
  class_breakdown: { IfcDoor: 9 },
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
  groups: [],
  rows: [
    { global_id: "D1", ifc_class: "IfcDoor", name: "Door A", storey_name: "Floor 3" },
  ],
} as AnswerExplanation;

const VIEWPORT = 1600;

/** Renders App and flushes the bootstrap model fetch, so no state update
 *  lands outside act(). */
async function renderApp() {
  let result!: ReturnType<typeof render>;
  await act(async () => {
    result = render(<App />);
  });
  return result;
}

/** Re-renders and flushes, for a store change made between assertions. */
async function rerenderApp(rerender: (ui: React.ReactElement) => void) {
  await act(async () => {
    rerender(<App />);
  });
}

function columnWidth(): number {
  const app = document.querySelector(".app") as HTMLElement;
  return parseInt(app.style.getPropertyValue("--chat-w"), 10);
}

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(window, "innerWidth", { value: VIEWPORT, configurable: true });
  useStore.setState({
    explanation: null,
    explanationGroupKey: null,
    explanationPrimaryGuids: [],
    explanationContextGuids: [],
    componentGuid: null,
    componentDetails: null,
    panelCollapsed: false,
    messages: [],
    models: [],
    activeModel: null,
    activeModelId: null,
    pendingConfirmModelId: null,
  });
});

describe("the fixed stacked layout", () => {
  it("keeps the existing full-height resizable chat when no card is open", async () => {
    await renderApp();
    expect(screen.queryByTestId("right-stack")).not.toBeInTheDocument();
    const chat = screen.getByLabelText("Conversation");
    expect(chat).not.toHaveClass("panel-stacked");
    // the drag handle is the existing resizable behavior, untouched
    expect(chat.querySelector(".panel-resizer")).not.toBeNull();
  });

  it("a qualifying highlighted answer opens the stack with the chat below it", async () => {
    useStore.setState({ explanation: EXPLANATION });
    await renderApp();

    const stack = screen.getByTestId("right-stack");
    const cards = stack.children;
    expect(cards).toHaveLength(2);
    expect(cards[0]).toHaveClass("explain-panel");
    expect(cards[1]).toHaveClass("panel-stacked");
  });

  it("removes the chat's own width and drag handle inside the fixed stack", async () => {
    useStore.setState({ explanation: EXPLANATION });
    await renderApp();

    const chat = screen.getByLabelText("Conversation");
    expect(chat).toHaveClass("panel-stacked");
    expect(chat.style.width).toBe("");
    expect(chat.querySelector(".panel-resizer")).toBeNull();
    // …and the user's stored preference is preserved for when the card closes
    expect(useStore.getState().panelWidth).toBeGreaterThan(0);
  });

  it("is 40vw alone and 32vw with the component panel, restoring on close", async () => {
    useStore.setState({ explanation: EXPLANATION });
    const { rerender } = await renderApp();
    expect(columnWidth()).toBe(Math.round(VIEWPORT * EXPLAIN_COLUMN_VW));

    useStore.setState({ componentGuid: "G9" });
    await rerenderApp(rerender);
    expect(screen.getByLabelText("Component details")).toBeInTheDocument();
    expect(columnWidth()).toBe(Math.round(VIEWPORT * EXPLAIN_COLUMN_PAIRED_VW));

    useStore.setState({ componentGuid: null });
    await rerenderApp(rerender);
    expect(columnWidth()).toBe(Math.round(VIEWPORT * EXPLAIN_COLUMN_VW));
  });

  it("drives the viewer obstruction from that same live column width", async () => {
    useStore.setState({ explanation: EXPLANATION });
    const { rerender } = await renderApp();
    expect(viewerStub.setViewportObstruction).toHaveBeenLastCalledWith(
      effectiveViewportObstructionPx(Math.round(VIEWPORT * EXPLAIN_COLUMN_VW), false),
    );

    useStore.setState({ componentGuid: "G9" });
    await rerenderApp(rerender);
    expect(viewerStub.setViewportObstruction).toHaveBeenLastCalledWith(
      effectiveViewportObstructionPx(Math.round(VIEWPORT * EXPLAIN_COLUMN_PAIRED_VW), true),
    );
  });

  it("collapsing the chat inside the stack leaves the card and an accessible restore tab", async () => {
    useStore.setState({ explanation: EXPLANATION, panelCollapsed: true });
    await renderApp();

    const stack = screen.getByTestId("right-stack");
    expect(stack).toHaveClass("right-stack-collapsed");
    expect(screen.getByLabelText("Query explanation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open chat panel" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Conversation")).not.toBeInTheDocument();
  });

  it("keeps the existing component panel and its contents unchanged", async () => {
    useStore.setState({ explanation: EXPLANATION, componentGuid: "G9" });
    await renderApp();
    const panel = screen.getByLabelText("Component details");
    expect(panel).toHaveClass("component-panel");
    expect(screen.getByRole("group", { name: /highlight matching objects/i })).toBeInTheDocument();
  });
});

// A result that supports no presentation carries no payload at all, so the
// original full-height chat stays and no blank explanation space is reserved
// (task29 §2, §7).
describe("non-qualifying results reserve no panel space", () => {
  it("leaves the original full-height chat layout and no empty card", async () => {
    useStore.setState({ explanation: null });
    await renderApp();
    expect(screen.queryByTestId("right-stack")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Query explanation")).not.toBeInTheDocument();
    const chat = screen.getByLabelText("Conversation");
    expect(chat).not.toHaveClass("panel-stacked");
    expect(chat.querySelector(".panel-resizer")).not.toBeNull();
  });

  it("retires the prior card when a newer result stops qualifying", async () => {
    useStore.setState({ explanation: EXPLANATION });
    const { rerender } = await renderApp();
    expect(screen.getByTestId("right-stack")).toBeInTheDocument();

    useStore.getState().closeExplanation();
    await rerenderApp(rerender);
    expect(screen.queryByTestId("right-stack")).not.toBeInTheDocument();
    expect(columnWidth()).toBe(useStore.getState().panelWidth);
  });

  it("switching to floor-plan mode neither creates nor closes explanation content", async () => {
    useStore.setState({ explanation: EXPLANATION });
    const { rerender } = await renderApp();

    useStore.getState().setFloorMode("plan", 0);
    await rerenderApp(rerender);
    expect(screen.getByLabelText("Query explanation")).toBeInTheDocument();

    useStore.getState().setFloorMode("3d", null);
    await rerenderApp(rerender);
    expect(screen.getByLabelText("Query explanation")).toBeInTheDocument();
    // …and the diagram is never a plan, section, elevation or model image.
    expect(screen.queryByTestId("ex-graph")).not.toBeInTheDocument();
  });
});
