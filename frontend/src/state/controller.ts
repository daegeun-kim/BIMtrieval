// Application controller (Task 11 Phases 6, 8, 9). Owns the async flows that tie
// the typed API client and the imperative ViewerAdapter to the state store:
// model load + cache, question submission, viewer-action application, manual
// selection resolution, Clear Chat, and Reset App. Deterministic UI operations
// (selection resolution, model load, resets) never call the query/LLM endpoint.
import { api } from "../api/client";
import { ApiError } from "../api/types";
import type {
  EntityCitation,
  HighlightScope,
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

function nowMs(): number {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

export class AppController {
  readonly viewer = new ViewerAdapter();

  private queryAbort: AbortController | null = null;
  private loadAbort: AbortController | null = null;
  private resolveAbort: AbortController | null = null;
  private detailAbort: AbortController | null = null;
  private groupAbort: AbortController | null = null;
  private resolveTimer: ReturnType<typeof setTimeout> | null = null;

  // Monotonic tokens so late/stale async results are ignored after the model or
  // session changes (spec_v006 §11.2, §12.3). Detail and group have separate
  // tokens: a group action must not invalidate an in-flight detail fetch.
  private queryToken = 0;
  private loadToken = 0;
  private resolveToken = 0;
  private detailToken = 0;
  private groupToken = 0;

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
    // Component details belong to the outgoing model — close the panel and
    // retire its tokens so no cross-model detail can land (task14 §5).
    this.closeComponent();
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
    this.syncComponentPanel(guids);
  }

  // ---- component detail panel (task14 §5) --------------------------------

  /**
   * The panel follows the selection: the most recently picked object is its
   * subject, and clicking empty space (which clears the selection) closes it.
   */
  private syncComponentPanel(guids: string[]): void {
    const subject = guids.length > 0 ? guids[guids.length - 1]! : null;
    if (subject === null) {
      this.closeComponent();
      return;
    }
    if (this.s.componentGuid === subject) return;
    void this.openComponent(subject);
  }

  /** Fetch bounded details for one component. Deterministic — no LLM call. */
  async openComponent(guid: string): Promise<void> {
    const modelId = this.s.activeModelId;
    if (modelId === null) return;
    this.s.openComponentPanel(guid);

    const token = ++this.detailToken;
    this.detailAbort?.abort();
    this.detailAbort = new AbortController();
    try {
      const details = await api.entityDetails(modelId, guid, this.detailAbort.signal);
      if (!this.detailStillCurrent(token, guid, modelId)) return;
      this.s.setComponentDetails(details);
    } catch (err) {
      if (this.isCanceled(err)) return;
      if (!this.detailStillCurrent(token, guid, modelId)) return;
      this.s.setComponentError(this.uiError(err, "Couldn't load this component's details."));
    }
  }

  /** Guard against a stale response after rapid selection or a model switch. */
  private detailStillCurrent(token: number, guid: string, modelId: number): boolean {
    return (
      token === this.detailToken &&
      this.s.componentGuid === guid &&
      this.s.activeModelId === modelId
    );
  }

  closeComponent(): void {
    this.detailToken++;
    this.groupToken++;
    this.detailAbort?.abort();
    this.groupAbort?.abort();
    this.s.closeComponentPanel();
  }

  /**
   * Apply a deterministic instance/type/family highlight group (task14 §5).
   *
   * Never submits a chat query, adds a message, alters backend session history,
   * or consumes OpenAI tokens — it is a viewer operation over a bounded
   * identity list from the group endpoint.
   */
  async applyGroupScope(scope: HighlightScope): Promise<void> {
    const modelId = this.s.activeModelId;
    const guid = this.s.componentGuid;
    if (modelId === null || guid === null) return;

    const token = ++this.groupToken;
    this.groupAbort?.abort();
    this.groupAbort = new AbortController();
    try {
      const res = await api.highlightGroup(modelId, guid, scope, this.groupAbort.signal);
      if (!this.groupStillCurrent(token, guid, modelId)) return;

      if (!res.available) {
        this.s.setComponentScope(
          null,
          res.unavailable_reason ?? "That grouping isn't available for this object.",
        );
        return;
      }
      const ids = res.global_ids ?? [];
      const total = res.total ?? ids.length;
      // Primary role + dimmed remainder, centered with the guarded moderate fit.
      await this.viewer.applyQueryRoles(ids, []);
      this.s.setComponentScope(scope, this.groupNotice(ids.length, total, res.truncated ?? false));
    } catch (err) {
      if (this.isCanceled(err)) return;
      if (!this.groupStillCurrent(token, guid, modelId)) return;
      this.s.setComponentScope(null, "Couldn't apply that highlight.");
    }
  }

  private groupStillCurrent(token: number, guid: string, modelId: number): boolean {
    return (
      token === this.groupToken && this.s.componentGuid === guid && this.s.activeModelId === modelId
    );
  }

  private groupNotice(shown: number, total: number, truncated: boolean): string {
    if (truncated) return `Highlighted the first ${shown} of ${total} matching objects.`;
    return total === 1 ? "1 matching object." : `${total} matching objects.`;
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
    const queryStartedAt = nowMs();

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
      const responseReceivedAt = nowMs();
      if (token !== this.queryToken) return; // superseded/stale
      this.s.setBackendReachable(true);
      await this.handleEnvelope(env);
      const viewerRenderedAt = nowMs();
      await api.reportQueryRenderTiming({
        request_id: env.request_id,
        response_received_ms: responseReceivedAt - queryStartedAt,
        viewer_render_ms: viewerRenderedAt - responseReceivedAt,
        total_to_viewer_ms: viewerRenderedAt - queryStartedAt,
      });
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
      // Compact totals/class counts replace the old component listing (task14 §4).
      resultSummary: env.result_summary ?? undefined,
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

    const notices: string[] = [];
    // The viewer set is capped at 2,000; the exact total in the answer is not
    // (spec_v006 §10.9). Disclose the difference rather than letting the
    // highlighted count silently contradict the stated total.
    if (va.viewer_matches_truncated && va.viewer_matches_total) {
      notices.push(
        `Highlighted the first ${primary.length} of ${va.viewer_matches_total} matching objects.`,
      );
    }
    if (missing.length > 0) {
      notices.push(
        `${missing.length} referenced object(s) aren't in the current 3D view and couldn't be highlighted.`,
      );
    }
    if (notices.length > 0) {
      this.s.addMessage({
        id: makeMessageId(),
        role: "assistant",
        kind: "notice",
        createdAt: Date.now(),
        content: notices.join(" "),
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
    // A group highlight is a query-result role, so it clears too — and the
    // in-flight token is retired so a late group response cannot re-highlight
    // after the clear (task14 §5).
    this.groupToken++;
    this.groupAbort?.abort();
    this.s.setComponentScope(null, null);
    // fresh backend + frontend conversation identity; keep model + selection +
    // the component panel (which follows selection) + cache
    this.resetBackendSession();
    this.s.regenerateSessionId();
  }

  async resetApp(): Promise<void> {
    this.cancelQuery();
    this.loadToken++; // invalidate any in-flight load
    this.loadAbort?.abort();
    this.closeComponent(); // retires detail/group tokens and disposes panel state
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
