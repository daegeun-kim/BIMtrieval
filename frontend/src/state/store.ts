// Small typed store (spec_v006 §13). Holds serializable UI/session state only;
// the Three.js scene and mutable viewer objects live in the ViewerAdapter, never
// here. Async flows (load, query, clear, reset) live in the controller, which
// reads/writes this store. Tab-scoped identity and harmless panel preferences
// persist to sessionStorage; chat history is never written to localStorage.
import { create } from "zustand";

import type {
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
}

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
}));

export function makeMessageId(): string {
  return `m-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
