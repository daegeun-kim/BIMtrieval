// Domain aliases over the generated OpenAPI schema (src/types/api.ts). Every
// request/response shape the app uses is derived from the backend contract so
// there is a single source of truth (spec_v006 §10.6). Do not hand-maintain
// parallel response interfaces.
import type { components } from "../types/api";

type Schemas = components["schemas"];

export type ModelListItem = Schemas["ModelListItem"];
export type ModelListResponse = Schemas["ModelListResponse"];
export type ViewerAssetStatus = Schemas["ViewerAssetStatus"];
export type ResolveEntitiesRequest = Schemas["ResolveEntitiesRequest"];
export type ResolveEntitiesResponse = Schemas["ResolveEntitiesResponse"];
export type ResolvedEntity = Schemas["ResolvedEntity"];

export type SessionQueryRequest = Schemas["SessionQueryRequest"];
export type QueryResponseEnvelope = Schemas["QueryResponseEnvelope"];
export type HistoryTurn = Schemas["HistoryTurn"];
export type ViewerActions = Schemas["ViewerActions"];
export type ModelCandidate = Schemas["ModelCandidate"];
export type PrimaryEntityResult = Schemas["PrimaryEntityResult"];
export type ContextEntityResult = Schemas["ContextEntityResult"];
export type RelationshipResult = Schemas["RelationshipResult"];
export type EvidenceSummary = Schemas["EvidenceSummary"];
export type QueryRoute = Schemas["QueryRoute"];
export type AnswerBasis = Schemas["AnswerBasis"];
export type ResponseStatus = Schemas["ResponseStatus"];
export type ModelAction = Schemas["ModelAction"];
export type SelectionAction = Schemas["SelectionAction"];

// Task 13 additions (spec_v006 §10.8, §10.9).
export type ResultSummary = Schemas["ResultSummary"];
export type SampleDetail = Schemas["SampleDetail"];
export type EntityDetailsResponse = Schemas["EntityDetailsResponse"];
export type InstanceDetails = Schemas["InstanceDetails"];
export type TypeDetails = Schemas["TypeDetails"];
export type FamilyDetails = Schemas["FamilyDetails"];
export type DetailAvailability = Schemas["DetailAvailability"];
export type DetailValue = Schemas["DetailValue"];
export type HighlightScope = Schemas["HighlightScope"];
export type HighlightGroupResponse = Schemas["HighlightGroupResponse"];

// Task 26 — the bounded presentation payload for the primary visual answer
// part (task26 §1.1). Optional on the envelope; the panel opens only when the
// backend supplies it alongside a non-empty highlight.
export type AnswerExplanation = Schemas["AnswerExplanation"];
export type ExplanationPresentation = Schemas["ExplanationPresentation"];
export type ExplanationGroup = Schemas["ExplanationGroup"];
export type ExplanationRow = Schemas["ExplanationRow"];
export type ExplanationBucket = Schemas["ExplanationBucket"];
export type ExplanationAggregate = Schemas["ExplanationAggregate"];

// Task 29 — the bounded grouped relationship topology (task29 §5.1). The
// frontend lays these nodes and edges out; it never re-derives the grouping,
// the graph eligibility, or the presentation choice.
export type ExplanationGraph = Schemas["ExplanationGraph"];
export type ExplanationGraphNode = Schemas["ExplanationGraphNode"];
export type ExplanationGraphEdge = Schemas["ExplanationGraphEdge"];

// Task 28 — the read-only logical floor contract behind the floor-plan control
// (task28 §2.1). Elevations on `FloorBandInfo` are stored project-unit
// diagnostics, NOT viewer scene coordinates.
export type ModelFloorsResponse = Schemas["ModelFloorsResponse"];
export type FloorBandInfo = Schemas["FloorBandInfo"];
export type FloorReferenceBasis = Schemas["FloorReferenceBasis"];

// A displayable entity citation (primary or context) the chat can make clickable.
export interface EntityCitation {
  entityId: number;
  globalId: string;
  ifcClass: string;
  name?: string | null;
  role: "primary" | "context";
}

// Normalized, UI-safe error. Raw backend/internal detail never reaches the UI
// (spec_v006 §3, §12.2, §15).
export type ApiErrorKind =
  | "network"
  | "canceled"
  | "timeout"
  | "backend_unavailable"
  | "not_found"
  | "asset_missing"
  | "asset_stale"
  | "asset_unavailable"
  | "bad_request"
  | "server";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status?: number;
  readonly retryable: boolean;
  constructor(kind: ApiErrorKind, message: string, opts?: { status?: number; retryable?: boolean }) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = opts?.status;
    this.retryable = opts?.retryable ?? false;
  }
}
