// Application controller (Task 11 Phases 6, 8, 9). Owns the async flows that tie
// the typed API client and the imperative ViewerAdapter to the state store:
// model load + cache, question submission, viewer-action application, manual
// selection resolution, Clear Chat, and Reset App. Deterministic UI operations
// (selection resolution, model load, resets) never call the query/LLM endpoint.
import { api } from "../api/client";
import { ApiError } from "../api/types";
import type {
  EntityCitation,
  HistoryTurn,
  ModelListItem,
  QueryResponseEnvelope,
  SessionQueryRequest,
} from "../api/types";
import { MAX_HISTORY_TURNS } from "../config";
import { getCachedArtifact, putCachedArtifact } from "../storage/artifactCache";
import { ViewerAdapter } from "../viewer/ViewerAdapter";
import {
  makeMessageId,
  useStore,
  type ChatMessage,
  type EvidenceView,
} from "./store";

const RESOLVE_DEBOUNCE_MS = 150;

export class AppController {
  readonly viewer = new ViewerAdapter();

  private queryAbort: AbortController | null = null;
  private loadAbort: AbortController | null = null;
  private resolveAbort: AbortController | null = null;
  private resolveTimer: ReturnType<typeof setTimeout> | null = null;

  // Monotonic tokens so late/stale async results are ignored after the model or
  // session changes (spec_v006 §11.2, §12.3).
  private queryToken = 0;
  private loadToken = 0;
  private resolveToken = 0;

  private get s() {
    return useStore.getState();
  }

  // ---- bootstrap + viewer wiring ----------------------------------------

  async bootstrap(): Promise<void> {
    await this.refreshModels();
  }

  async refreshModels(): Promise<void> {
    this.s.setModelsLoading(true);
    this.s.setModelsError(null);
    try {
      const res = await api.listModels();
      this.s.setModels(res.models ?? []);
      this.s.setBackendReachable(true);
    } catch (err) {
      this.s.setModelsError(this.uiError(err, "Couldn't load the model list."));
      this.s.setBackendReachable(!(err instanceof ApiError && err.kind === "backend_unavailable"));
    } finally {
      this.s.setModelsLoading(false);
    }
  }

  async initViewer(container: HTMLElement): Promise<void> {
    this.viewer.setCallbacks({
      onManualSelectionChange: (guids) => this.onManualSelectionChange(guids),
      onSelectionLimitReached: () =>
        this.s.setSelectionNotice("Selection is limited to five objects. Remove one to add another."),
    });
    await this.viewer.init(container);
  }

  // ---- model confirmation + loading -------------------------------------

  async confirmAndLoadModel(model: ModelListItem): Promise<void> {
    const token = ++this.loadToken;
    this.loadAbort?.abort();
    this.loadAbort = new AbortController();
    const signal = this.loadAbort.signal;

    this.s.setPendingConfirm(null);
    this.s.setActiveModel(model);
    this.s.setLoadError(null);
    this.s.setLoadPhase("metadata");
    this.s.clearSelection();
    this.viewer.clearManualSelection();
    await this.viewer.clearQueryRoles();

    try {
      // Sync the backend session's active model (existing confirmation
      // semantics). We use the frontend asset endpoint for geometry.
      await api.query(
        {
          question: "load model",
          session_id: this.s.sessionId,
          confirm_model_id: model.source_model_id,
        },
        signal,
      );

      const bytes = await this.loadArtifact(model, token, signal);
      if (token !== this.loadToken) return; // superseded
      if (!bytes) return;

      this.s.setLoadPhase("initializing");
      await this.viewer.loadModel(bytes, String(model.source_model_id));
      if (token !== this.loadToken) return;
      this.s.setLoadPhase("ready");
    } catch (err) {
      if (this.isCanceled(err) || token !== this.loadToken) return;
      this.s.setLoadPhase("error");
      this.s.setLoadError(this.uiError(err, "The model could not be loaded."));
    }
  }

  private async loadArtifact(
    model: ModelListItem,
    token: number,
    signal: AbortSignal,
  ): Promise<ArrayBuffer | null> {
    const cached = await getCachedArtifact(model.source_model_id, model.source_fingerprint);
    if (token !== this.loadToken) return null;
    if (cached) {
      this.s.setLoadPhase("cached");
      return cached.bytes;
    }
    this.s.setLoadPhase("downloading");
    const asset = await api.fetchViewerAsset(model.source_model_id, signal);
    // Cache is best-effort; a quota failure must not block the load.
    void putCachedArtifact(model.source_model_id, model.source_fingerprint, asset.bytes.slice(0));
    return asset.bytes;
  }

  retryLoad(): void {
    const model = this.s.activeModel;
    if (model) void this.confirmAndLoadModel(model);
  }

  // ---- manual selection + resolution ------------------------------------

  private onManualSelectionChange(guids: string[]): void {
    this.s.setManualGuids(guids);
    this.s.setSelectionNotice(null);
    // prune resolved chips no longer selected
    const kept: typeof this.s.resolvedChips = {};
    for (const g of guids) if (this.s.resolvedChips[g]) kept[g] = this.s.resolvedChips[g];
    this.s.setResolvedChips(kept);
    this.scheduleResolve(guids);
  }

  private scheduleResolve(guids: string[]): void {
    if (this.resolveTimer) clearTimeout(this.resolveTimer);
    const toResolve = guids.filter((g) => !this.s.resolvedChips[g]);
    if (toResolve.length === 0) return;
    this.resolveTimer = setTimeout(() => void this.resolveSelection(guids, toResolve), RESOLVE_DEBOUNCE_MS);
  }

  private async resolveSelection(allGuids: string[], toResolve: string[]): Promise<void> {
    const modelId = this.s.activeModelId;
    if (modelId === null) return;
    const token = ++this.resolveToken;
    this.resolveAbort?.abort();
    this.resolveAbort = new AbortController();
    try {
      const res = await api.resolveEntities(modelId, toResolve.slice(0, 5), this.resolveAbort.signal);
      if (token !== this.resolveToken) return; // stale
      if (this.s.activeModelId !== modelId) return; // model changed
      // ignore if selection changed underneath us
      const current = new Set(this.s.manualGuids);
      const next = { ...this.s.resolvedChips };
      for (const ent of res.resolved ?? []) if (current.has(ent.global_id)) next[ent.global_id] = ent;
      this.s.setResolvedChips(next);
      void allGuids;
    } catch {
      // resolution is non-critical; chips fall back to showing the raw id
    }
  }

  removeChip(guid: string): void {
    this.viewer.removeManualSelection(guid);
  }

  // ---- question submission ----------------------------------------------

  async submitQuestion(rawText: string): Promise<void> {
    const text = rawText.trim();
    if (!text || this.s.pending) return;

    this.s.addMessage(this.userMessage(text));
    this.s.setPending(true);
    this.s.setRetryQuestion(null);

    const token = ++this.queryToken;
    this.queryAbort?.abort();
    this.queryAbort = new AbortController();

    const request: SessionQueryRequest = {
      question: text,
      session_id: this.s.sessionId,
      active_source_model_id: this.s.activeModelId,
      selected_global_ids: this.s.activeModelId !== null ? this.s.manualGuids.slice(0, 5) : [],
      history: this.boundedHistory(),
    };

    try {
      const env = await api.query(request, this.queryAbort.signal);
      if (token !== this.queryToken) return; // superseded/stale
      this.s.setBackendReachable(true);
      await this.handleEnvelope(env);
    } catch (err) {
      if (this.isCanceled(err) || token !== this.queryToken) return;
      const apiErr = err instanceof ApiError ? err : null;
      this.s.addMessage(this.assistantError(this.uiError(err, "Something went wrong answering that.")));
      if (!apiErr || apiErr.retryable || apiErr.kind === "backend_unavailable") {
        this.s.setRetryQuestion(text);
      }
      if (apiErr?.kind === "backend_unavailable") this.s.setBackendReachable(false);
    } finally {
      if (token === this.queryToken) this.s.setPending(false);
    }
  }

  cancelQuery(): void {
    this.queryToken++; // invalidate in-flight response
    this.queryAbort?.abort();
    this.s.setPending(false);
  }

  retry(): void {
    const q = this.s.retryQuestion;
    if (q) void this.submitQuestion(q);
  }

  private async handleEnvelope(env: QueryResponseEnvelope): Promise<void> {
    const citations = this.citationsOf(env);
    const message: ChatMessage = {
      id: makeMessageId(),
      role: "assistant",
      content: env.answer,
      kind: env.status === "error" ? "error" : env.route === "clarify" ? "clarification" : "text",
      createdAt: Date.now(),
      status: env.status,
      evidence: this.evidenceOf(env, citations),
      citations,
      candidates: env.model_candidates?.length ? env.model_candidates : undefined,
    };
    this.s.addMessage(message);

    if (env.warnings?.length) {
      // surface unresolved-selection / degraded notes as a quiet notice
    }
    await this.applyViewerActions(env);
  }

  private async applyViewerActions(env: QueryResponseEnvelope): Promise<void> {
    if (!this.viewer.hasModel()) return;
    const va = env.viewer_actions;
    if (!va) return;
    const action = va.selection_action;
    if (action === "clear" || action === "none" || action === undefined) {
      if (action === "clear") await this.viewer.clearQueryRoles();
      return;
    }
    const primary = va.primary_global_ids ?? [];
    const context = va.context_global_ids ?? [];
    if (primary.length === 0 && context.length === 0) return;
    const { missing } = await this.viewer.applyQueryRoles(primary, context);
    if (missing.length > 0) {
      this.s.addMessage({
        id: makeMessageId(),
        role: "assistant",
        kind: "notice",
        createdAt: Date.now(),
        content: `${missing.length} referenced object(s) aren't in the current 3D view and couldn't be highlighted.`,
      });
    }
  }

  async focusCitation(citation: EntityCitation): Promise<void> {
    if (!this.viewer.hasModel()) return;
    // Deterministic — never calls the LLM (spec_v006 §11.4).
    await this.viewer.fitToGuids([citation.globalId]);
  }

  async fitAll(): Promise<void> {
    await this.viewer.fitAll();
  }

  // ---- Clear Chat / Reset App -------------------------------------------

  async clearChat(): Promise<void> {
    this.cancelQuery();
    this.s.clearMessages();
    this.s.setRetryQuestion(null);
    await this.viewer.clearQueryRoles();
    // fresh backend + frontend conversation identity; keep model + selection + cache
    this.resetBackendSession();
    this.s.regenerateSessionId();
  }

  async resetApp(): Promise<void> {
    this.cancelQuery();
    this.loadToken++; // invalidate any in-flight load
    this.loadAbort?.abort();
    this.resetBackendSession();

    this.s.clearMessages();
    this.s.setRetryQuestion(null);
    this.s.clearSelection();
    this.viewer.clearManualSelection();
    await this.viewer.clearQueryRoles();
    await this.viewer.unloadModel();

    this.s.setActiveModel(null);
    this.s.setPendingConfirm(null);
    this.s.setLoadPhase("idle");
    this.s.setLoadError(null);
    this.s.regenerateSessionId();
  }

  // Best-effort: retire the old backend session state (spec_v006 §13.1/§13.2).
  private resetBackendSession(): void {
    void api
      .query({ question: "reset", session_id: this.s.sessionId, reset: true })
      .catch(() => undefined);
  }

  // ---- helpers ----------------------------------------------------------

  private boundedHistory(): HistoryTurn[] {
    const turns: HistoryTurn[] = [];
    for (const m of this.s.messages) {
      if (m.kind === "error" || m.kind === "notice") continue;
      if (!m.content.trim()) continue;
      turns.push({ role: m.role, content: m.content.slice(0, 4000) });
    }
    return turns.slice(-MAX_HISTORY_TURNS);
  }

  private citationsOf(env: QueryResponseEnvelope): EntityCitation[] {
    const out: EntityCitation[] = [];
    for (const e of env.primary_entities ?? [])
      out.push({ entityId: e.entity_id, globalId: e.global_id, ifcClass: e.ifc_class, name: e.name, role: "primary" });
    for (const e of env.context_entities ?? [])
      out.push({ entityId: e.entity_id, globalId: e.global_id, ifcClass: e.ifc_class, name: e.name, role: "context" });
    return out;
  }

  private evidenceOf(env: QueryResponseEnvelope, citations: EntityCitation[]): EvidenceView {
    const ev = env.evidence_summary;
    return {
      route: env.route,
      answerBasis: env.answer_basis,
      scope: env.scope,
      sqlCount: ev?.sql_match_count ?? null,
      ragCount: ev?.rag_candidate_count ?? null,
      relCount: ev?.relationship_count ?? null,
      primaries: citations.filter((c) => c.role === "primary"),
      contexts: citations.filter((c) => c.role === "context"),
      relationships: env.relationships ?? [],
      notes: ev?.notes ?? [],
      warnings: env.warnings ?? [],
    };
  }

  private userMessage(text: string): ChatMessage {
    return { id: makeMessageId(), role: "user", content: text, kind: "text", createdAt: Date.now() };
  }

  private assistantError(text: string): ChatMessage {
    return { id: makeMessageId(), role: "assistant", content: text, kind: "error", createdAt: Date.now() };
  }

  private isCanceled(err: unknown): boolean {
    return err instanceof ApiError && err.kind === "canceled";
  }

  private uiError(err: unknown, fallback: string): string {
    if (err instanceof ApiError && err.kind !== "server") return err.message;
    return fallback;
  }
}

export const controller = new AppController();
