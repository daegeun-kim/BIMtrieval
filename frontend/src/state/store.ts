// Small typed store (spec_v006 §13). Holds serializable UI/session state only;
// the Three.js scene and mutable viewer objects live in the ViewerAdapter, never
// here. Async flows (load, query, clear, reset) live in the controller, which
// reads/writes this store. Tab-scoped identity and harmless panel preferences
// persist to sessionStorage; chat history is never written to localStorage.
import { create } from "zustand";

import {
  DEFAULT_VISUALIZATION_MODE,
  type VisualizationMode,
} from "../viewer/viewerCustomization";
import type {
  AnswerExplanation,
  EntityCitation,
  EntityDetailsResponse,
  HighlightScope,
  ModelCandidate,
  ModelListItem,
  RelationshipResult,
  ResolvedEntity,
  ResponseStatus,
  ResultSummary,
} from "../api/types";

export type LoadPhase =
  | "idle"
  | "metadata"
  | "downloading"
  | "cached"
  | "initializing"
  | "ready"
  | "error";

export type MessageKind = "text" | "clarification" | "error" | "notice";

/**
 * Viewer projection mode (task28 §6). Current-session only and deliberately
 * NOT persisted to local storage: reopening the app starts in normal 3D.
 */
export type FloorMode = "3d" | "plan";

/**
 * One floor button. Serializable presentation state only — the saved
 * perspective pose and the live clipping/section objects belong inside the
 * imperative viewer layer, never here (task28 §6).
 */
export interface FloorOption {
  bandIndex: number;
  label: string;
  /** False when the floor cannot be mapped safely into scene coordinates. */
  enabled: boolean;
  /** Concise reason for a disabled floor. */
  reason: string | null;
  /** Source IFC storey names — tooltip / accessible description only. */
  storeyNames: string[];
}

export interface EvidenceView {
  route: string;
  answerBasis: string;
  scope: string;
  sqlCount?: number | null;
  ragCount?: number | null;
  relCount?: number | null;
  primaries: EntityCitation[];
  contexts: EntityCitation[];
  relationships: RelationshipResult[];
  notes: string[];
  warnings: string[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  kind: MessageKind;
  createdAt: number;
  evidence?: EvidenceView;
  candidates?: ModelCandidate[];
  citations?: EntityCitation[];
  status?: ResponseStatus;
  /** Compact totals/class counts shown instead of a component dump (task14 §4). */
  resultSummary?: ResultSummary;
}

const SS_SESSION = "bimrag.sessionId";
const SS_PANEL_W = "bimrag.panelWidth";
const SS_PANEL_C = "bimrag.panelCollapsed";

export const PANEL_MIN_WIDTH = 320;
export const PANEL_MAX_WIDTH = 520;

// Dual-panel desktop layout (task14 §5). With the component panel open, both
// panels take narrower defaults so the model stays the dominant workspace: at
// 1440px the two panels + margins occupy ~730px, leaving the viewer ~49%.
export const COMPONENT_PANEL_WIDTH = 320;
export const PANEL_PAIRED_WIDTH = 360;
export const PANEL_PAIRED_MAX_WIDTH = 400;

/** Chat width to use for the current pairing, without mutating the stored preference. */
export function effectivePanelWidth(stored: number, componentOpen: boolean): number {
  if (!componentOpen) return stored;
  return Math.min(stored, PANEL_PAIRED_MAX_WIDTH, PANEL_PAIRED_WIDTH);
}

/**
 * Outer margin between a floating right-side panel and the viewport edge, and
 * the gap between the component panel and the chat panel it docks against
 * (task19 §2) — mirrors `.panel`'s `right: 20px` and `.component-panel`'s
 * `var(--sp-3)` gap in App.css, the single CSS source for the same numbers.
 */
export const VIEWER_EDGE_MARGIN_PX = 20;
export const PANEL_GAP_PX = 12;

/**
 * Total width, in px, occupied by visible right-side panels — measured from
 * the viewport's right edge to the left edge of the outermost visible panel
 * (task19 §2). This is the single source of truth the viewer's effective
 * visible-region centering reads; it is derived entirely from the same live
 * chat width / component-open state App.tsx already uses for `--chat-w`,
 * never a separate hard-coded copy.
 */
export function effectiveViewportObstructionPx(chatWidthPx: number, componentOpen: boolean): number {
  const base = VIEWER_EDGE_MARGIN_PX + Math.max(0, chatWidthPx);
  if (!componentOpen) return base;
  return base + PANEL_GAP_PX + COMPONENT_PANEL_WIDTH;
}

/**
 * Fixed Task 26 stacked-column widths (task26 §3): 40% of the viewport, or 32%
 * when the 320 px component-detail panel is docked beside it. Deliberately not
 * a saved preference and not resizable — the layout is fixed for this task.
 */
export const EXPLAIN_COLUMN_VW = 0.4;
export const EXPLAIN_COLUMN_PAIRED_VW = 0.32;

/**
 * Width in px of the explanation+chat column for the current viewport. Feeds
 * BOTH the `--chat-w` CSS variable (so the component panel still docks against
 * the column's left edge) and `effectiveViewportObstructionPx`, so there is no
 * second set of hard-coded obstruction measurements (task26 §3).
 */
export function explanationColumnWidthPx(viewportWidthPx: number, componentOpen: boolean): number {
  const fraction = componentOpen ? EXPLAIN_COLUMN_PAIRED_VW : EXPLAIN_COLUMN_VW;
  return Math.round(Math.max(0, viewportWidthPx) * fraction);
}

function newSessionId(): string {
  const id =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `s-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return id;
}

function readSessionStorage(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeSessionStorage(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    // storage may be unavailable (private mode); non-fatal
  }
}

function initialSessionId(): string {
  const existing = readSessionStorage(SS_SESSION);
  if (existing) return existing;
  const id = newSessionId();
  writeSessionStorage(SS_SESSION, id);
  return id;
}

function initialPanelWidth(): number {
  const raw = Number(readSessionStorage(SS_PANEL_W));
  if (Number.isFinite(raw) && raw >= PANEL_MIN_WIDTH && raw <= PANEL_MAX_WIDTH) return raw;
  return 380;
}

export interface AppState {
  sessionId: string;

  // model catalog + active model
  models: ModelListItem[];
  modelsError: string | null;
  modelsLoading: boolean;
  activeModelId: number | null;
  activeModel: ModelListItem | null;
  loadPhase: LoadPhase;
  loadError: string | null;
  pendingConfirmModelId: number | null;

  // chat
  messages: ChatMessage[];
  pending: boolean;
  retryQuestion: string | null;
  backendReachable: boolean;

  // manual selection
  manualGuids: string[];
  resolvedChips: Record<string, ResolvedEntity>;
  selectionNotice: string | null;

  // panel layout
  panelWidth: number;
  panelCollapsed: boolean;

  // component detail panel (task14 §5). Current-session UI state only — details
  // are never persisted, and no backend trace data is ever stored here.
  componentGuid: string | null;
  componentDetails: EntityDetailsResponse | null;
  componentLoading: boolean;
  componentError: string | null;
  /** Which group action is currently applied, for button affordance. */
  componentScope: HighlightScope | null;
  componentGroupNotice: string | null;

  // Query explanation card (task26 §6). Current-session only and serializable:
  // the bounded presentation payload, the ORIGINAL viewer roles so "All results"
  // can restore them without another query, and the active subgroup. Never
  // persisted to local storage.
  explanation: AnswerExplanation | null;
  /** The full result's primary GlobalIds, as the answer delivered them. */
  explanationPrimaryGuids: string[];
  /** The full result's relationship-context GlobalIds. */
  explanationContextGuids: string[];
  /** `null` means the full result is highlighted. */
  explanationGroupKey: string | null;

  /**
   * Selected visualization quality (task31 §2.1). Session-level and
   * deliberately NOT persisted to sessionStorage/localStorage/IndexedDB:
   * reopening the app starts at Standard. It survives model switches, and only
   * Reset App returns it to Standard. This is the serializable half of the
   * typed state/controller boundary — the imperative scene work that applies it
   * stays inside `ViewerAdapter`.
   */
  visualizationMode: VisualizationMode;

  // Floor-plan mode (task28 §6). Current-session only, never persisted.
  floorMode: FloorMode;
  /** The model the floor contract belongs to, so a stale response is ignorable. */
  floorModelId: number | null;
  /** The active logical band while in plan mode. */
  floorBandIndex: number | null;
  floorsLoading: boolean;
  /** False when the model's spatial data establishes no logical floor at all. */
  floorsAvailable: boolean;
  floorOptions: FloorOption[];
  /** A concise, non-blocking plan limitation to surface. */
  floorNotice: string | null;

  // actions (pure state; side effects live in the controller)
  regenerateSessionId: () => string;
  setModels: (models: ModelListItem[]) => void;
  setModelsError: (msg: string | null) => void;
  setModelsLoading: (v: boolean) => void;
  setActiveModel: (model: ModelListItem | null) => void;
  setLoadPhase: (phase: LoadPhase) => void;
  setLoadError: (msg: string | null) => void;
  setPendingConfirm: (id: number | null) => void;

  addMessage: (msg: ChatMessage) => void;
  clearMessages: () => void;
  setPending: (v: boolean) => void;
  setRetryQuestion: (q: string | null) => void;
  setBackendReachable: (v: boolean) => void;

  setManualGuids: (guids: string[]) => void;
  setResolvedChips: (chips: Record<string, ResolvedEntity>) => void;
  setSelectionNotice: (msg: string | null) => void;
  clearSelection: () => void;

  setPanelWidth: (w: number) => void;
  togglePanelCollapsed: () => void;

  openComponentPanel: (guid: string) => void;
  setComponentDetails: (details: EntityDetailsResponse | null) => void;
  setComponentLoading: (v: boolean) => void;
  setComponentError: (msg: string | null) => void;
  setComponentScope: (scope: HighlightScope | null, notice?: string | null) => void;
  closeComponentPanel: () => void;

  openExplanation: (
    explanation: AnswerExplanation,
    primaryGuids: string[],
    contextGuids: string[],
  ) => void;
  setExplanationGroup: (key: string | null) => void;
  closeExplanation: () => void;

  setVisualizationMode: (mode: VisualizationMode) => void;

  setFloorsLoading: (modelId: number) => void;
  setFloorOptions: (
    modelId: number,
    options: FloorOption[],
    available: boolean,
  ) => void;
  setFloorMode: (mode: FloorMode, bandIndex: number | null) => void;
  setFloorOptionDisabled: (bandIndex: number, reason: string) => void;
  setFloorNotice: (notice: string | null) => void;
  clearFloors: () => void;
}

const FLOOR_DEFAULTS = {
  floorMode: "3d" as FloorMode,
  floorModelId: null,
  floorBandIndex: null,
  floorsLoading: false,
  floorsAvailable: false,
  floorOptions: [] as FloorOption[],
  floorNotice: null,
};

export const useStore = create<AppState>((set, get) => ({
  sessionId: initialSessionId(),

  models: [],
  modelsError: null,
  modelsLoading: false,
  activeModelId: null,
  activeModel: null,
  loadPhase: "idle",
  loadError: null,
  pendingConfirmModelId: null,

  messages: [],
  pending: false,
  retryQuestion: null,
  backendReachable: true,

  manualGuids: [],
  resolvedChips: {},
  selectionNotice: null,

  panelWidth: initialPanelWidth(),
  panelCollapsed: readSessionStorage(SS_PANEL_C) === "1",

  componentGuid: null,
  componentDetails: null,
  componentLoading: false,
  componentError: null,
  componentScope: null,
  componentGroupNotice: null,

  explanation: null,
  explanationPrimaryGuids: [],
  explanationContextGuids: [],
  explanationGroupKey: null,

  visualizationMode: DEFAULT_VISUALIZATION_MODE,

  ...FLOOR_DEFAULTS,

  regenerateSessionId: () => {
    const id = newSessionId();
    writeSessionStorage(SS_SESSION, id);
    set({ sessionId: id });
    return id;
  },
  setModels: (models) => set({ models }),
  setModelsError: (modelsError) => set({ modelsError }),
  setModelsLoading: (modelsLoading) => set({ modelsLoading }),
  setActiveModel: (activeModel) =>
    set({ activeModel, activeModelId: activeModel ? activeModel.source_model_id : null }),
  setLoadPhase: (loadPhase) => set({ loadPhase }),
  setLoadError: (loadError) => set({ loadError }),
  setPendingConfirm: (pendingConfirmModelId) => set({ pendingConfirmModelId }),

  addMessage: (msg) => set({ messages: [...get().messages, msg] }),
  clearMessages: () => set({ messages: [] }),
  setPending: (pending) => set({ pending }),
  setRetryQuestion: (retryQuestion) => set({ retryQuestion }),
  setBackendReachable: (backendReachable) => set({ backendReachable }),

  setManualGuids: (manualGuids) => set({ manualGuids }),
  setResolvedChips: (resolvedChips) => set({ resolvedChips }),
  setSelectionNotice: (selectionNotice) => set({ selectionNotice }),
  clearSelection: () => set({ manualGuids: [], resolvedChips: {}, selectionNotice: null }),

  setPanelWidth: (w) => {
    const clamped = Math.min(PANEL_MAX_WIDTH, Math.max(PANEL_MIN_WIDTH, Math.round(w)));
    writeSessionStorage(SS_PANEL_W, String(clamped));
    set({ panelWidth: clamped });
  },
  togglePanelCollapsed: () => {
    const next = !get().panelCollapsed;
    writeSessionStorage(SS_PANEL_C, next ? "1" : "0");
    set({ panelCollapsed: next });
  },

  // Selecting a new component clears the previous subject's details outright, so
  // a slow in-flight response can never paint over the new selection.
  openComponentPanel: (guid) =>
    set({
      componentGuid: guid,
      componentDetails: null,
      componentLoading: true,
      componentError: null,
      componentScope: null,
      componentGroupNotice: null,
    }),
  setComponentDetails: (componentDetails) =>
    set({ componentDetails, componentLoading: false, componentError: null }),
  setComponentLoading: (componentLoading) => set({ componentLoading }),
  setComponentError: (componentError) => set({ componentError, componentLoading: false }),
  setComponentScope: (componentScope, componentGroupNotice = null) =>
    set({ componentScope, componentGroupNotice }),
  closeComponentPanel: () =>
    set({
      componentGuid: null,
      componentDetails: null,
      componentLoading: false,
      componentError: null,
      componentScope: null,
      componentGroupNotice: null,
    }),

  // A newer qualifying result REPLACES the card outright, subgroup included —
  // a subgroup of the previous answer must never survive into the next one.
  openExplanation: (explanation, explanationPrimaryGuids, explanationContextGuids) =>
    set({
      explanation,
      explanationPrimaryGuids: [...explanationPrimaryGuids],
      explanationContextGuids: [...explanationContextGuids],
      explanationGroupKey: null,
    }),
  setExplanationGroup: (explanationGroupKey) => set({ explanationGroupKey }),
  closeExplanation: () =>
    set({
      explanation: null,
      explanationPrimaryGuids: [],
      explanationContextGuids: [],
      explanationGroupKey: null,
    }),

  setVisualizationMode: (visualizationMode) => set({ visualizationMode }),

  // A new model's floor contract replaces the previous one outright, so a floor
  // button from the outgoing model can never survive into the new one.
  setFloorsLoading: (floorModelId) =>
    set({
      ...FLOOR_DEFAULTS,
      floorModelId,
      floorsLoading: true,
    }),
  setFloorOptions: (floorModelId, floorOptions, floorsAvailable) =>
    set({
      floorModelId,
      floorOptions,
      floorsAvailable,
      floorsLoading: false,
      floorMode: "3d",
      floorBandIndex: null,
      floorNotice: null,
    }),
  setFloorMode: (floorMode, floorBandIndex) =>
    set({ floorMode, floorBandIndex: floorMode === "plan" ? floorBandIndex : null }),
  setFloorOptionDisabled: (bandIndex, reason) =>
    set({
      floorOptions: get().floorOptions.map((o) =>
        o.bandIndex === bandIndex ? { ...o, enabled: false, reason } : o,
      ),
    }),
  setFloorNotice: (floorNotice) => set({ floorNotice }),
  clearFloors: () => set({ ...FLOOR_DEFAULTS }),
}));

export function makeMessageId(): string {
  return `m-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
