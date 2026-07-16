// The single typed API client (spec_v006 §10.6, Task 11 Phase 3). Owns the base
// URL, request/response typing, cancellation, and bounded error normalization.
// No component issues raw fetch calls, and no raw backend error text reaches the
// UI.
import { API_BASE_URL } from "../config";
import {
  ApiError,
  type EntityDetailsResponse,
  type HighlightGroupResponse,
  type HighlightScope,
  type ModelListResponse,
  type QueryResponseEnvelope,
  type ResolveEntitiesResponse,
  type SessionQueryRequest,
} from "./types";

export interface ViewerAssetResult {
  bytes: ArrayBuffer;
  etag: string | null;
}

function normalizeFetchError(err: unknown): ApiError {
  if (err instanceof ApiError) return err;
  if (err instanceof DOMException && err.name === "AbortError") {
    return new ApiError("canceled", "Request canceled.");
  }
  return new ApiError("backend_unavailable", "Could not reach the backend.", { retryable: true });
}

async function readDetailStatus(res: Response): Promise<string | undefined> {
  try {
    const body = await res.clone().json();
    const detail = (body as { detail?: unknown }).detail;
    if (detail && typeof detail === "object" && "status" in detail) {
      return String((detail as { status?: unknown }).status);
    }
  } catch {
    // non-JSON body — ignore, fall back to status code mapping
  }
  return undefined;
}

export class ApiClient {
  constructor(private readonly baseUrl: string = API_BASE_URL) {}

  /** Absolute URL for the prepared viewer artifact of a model. */
  viewerAssetUrl(sourceModelId: number): string {
    return `${this.baseUrl}/api/models/${sourceModelId}/viewer-asset`;
  }

  async listModels(signal?: AbortSignal): Promise<ModelListResponse> {
    return this.getJson<ModelListResponse>(`${this.baseUrl}/api/models`, signal);
  }

  async resolveEntities(
    sourceModelId: number,
    globalIds: string[],
    signal?: AbortSignal,
  ): Promise<ResolveEntitiesResponse> {
    return this.postJson<ResolveEntitiesResponse>(
      `${this.baseUrl}/api/models/${sourceModelId}/entities/resolve`,
      { global_ids: globalIds },
      signal,
    );
  }

  async query(request: SessionQueryRequest, signal?: AbortSignal): Promise<QueryResponseEnvelope> {
    return this.postJson<QueryResponseEnvelope>(`${this.baseUrl}/api/query`, request, signal);
  }

  /**
   * Truthful bounded details for one component (spec_v006 §10.8). Deterministic
   * and LLM-free: opening the panel never consumes OpenAI tokens.
   */
  async entityDetails(
    sourceModelId: number,
    globalId: string,
    signal?: AbortSignal,
  ): Promise<EntityDetailsResponse> {
    return this.getJson<EntityDetailsResponse>(
      `${this.baseUrl}/api/models/${sourceModelId}/entities/${encodeURIComponent(globalId)}/details`,
      signal,
    );
  }

  /**
   * Deterministic instance/type/family match set for the component-panel
   * buttons (spec_v006 §10.8). Creates no chat message and calls no LLM.
   */
  async highlightGroup(
    sourceModelId: number,
    selectedGlobalId: string,
    scope: HighlightScope,
    signal?: AbortSignal,
  ): Promise<HighlightGroupResponse> {
    return this.postJson<HighlightGroupResponse>(
      `${this.baseUrl}/api/models/${sourceModelId}/entities/highlight-group`,
      { selected_global_id: selectedGlobalId, scope },
      signal,
    );
  }

  /** Fetch the prepared artifact, mapping bounded statuses to typed errors. */
  async fetchViewerAsset(sourceModelId: number, signal?: AbortSignal): Promise<ViewerAssetResult> {
    let res: Response;
    try {
      res = await fetch(this.viewerAssetUrl(sourceModelId), { signal });
    } catch (err) {
      throw normalizeFetchError(err);
    }
    if (!res.ok) {
      const status = (await readDetailStatus(res)) ?? "";
      if (res.status === 404 && status === "missing") {
        throw new ApiError("asset_missing", "This model has no prepared 3D artifact yet.");
      }
      if (res.status === 409 || status === "stale") {
        throw new ApiError("asset_stale", "The 3D artifact is out of date and needs re-preparing.");
      }
      if (res.status === 503 || status === "unavailable") {
        throw new ApiError("asset_unavailable", "The 3D artifact is currently unavailable.", {
          retryable: true,
        });
      }
      if (res.status === 404) throw new ApiError("not_found", "Model not found.");
      throw new ApiError("server", "The 3D artifact could not be loaded.", {
        status: res.status,
        retryable: true,
      });
    }
    const bytes = await res.arrayBuffer();
    return { bytes, etag: res.headers.get("ETag") };
  }

  private async getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
    let res: Response;
    try {
      res = await fetch(url, { signal, headers: { Accept: "application/json" } });
    } catch (err) {
      throw normalizeFetchError(err);
    }
    return this.parse<T>(res);
  }

  private async postJson<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
    let res: Response;
    try {
      res = await fetch(url, {
        method: "POST",
        signal,
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
      });
    } catch (err) {
      throw normalizeFetchError(err);
    }
    return this.parse<T>(res);
  }

  private async parse<T>(res: Response): Promise<T> {
    if (res.ok) return (await res.json()) as T;
    if (res.status === 404) throw new ApiError("not_found", "Not found.", { status: 404 });
    if (res.status === 422) throw new ApiError("bad_request", "The request was rejected.", { status: 422 });
    if (res.status >= 500) {
      throw new ApiError("server", "The backend hit an error. Please try again.", {
        status: res.status,
        retryable: true,
      });
    }
    throw new ApiError("server", "Unexpected response from the backend.", { status: res.status });
  }
}

export const api = new ApiClient();
