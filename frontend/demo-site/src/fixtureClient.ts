// The demo's stand-in for `src/api/client.ts` (spec_v013 §4.3).
//
// Vite aliases this module in place of the real client. `api` is exported once
// and imported once — by `src/state/controller.ts` — and every network call the
// frontend makes passes through these eight methods, so replacing this one
// module replaces the entire backend. The viewer, chat, explanation panel,
// component panel, store, and controller all run unmodified and unaware.
//
// The exported surface must stay identical to the real client, because the
// aliased import is type-checked against it.
import {
  ApiError,
  type EntityDetailsResponse,
  type HighlightGroupResponse,
  type HighlightScope,
  type ModelFloorsResponse,
  type ModelListResponse,
  type QueryResponseEnvelope,
  type ResolveEntitiesResponse,
  type SessionQueryRequest,
} from "../../src/api/types";
import {
  answerFor,
  entityDetailsFor,
  floorsFixture,
  highlightGroupFor,
  loadModelFixture,
  modelsFixture,
  questionForText,
  resolveFixture,
} from "./fixtures";

export interface ViewerAssetResult {
  bytes: ArrayBuffer;
  etag: string | null;
}

export interface QueryRenderTiming {
  request_id: string;
  response_received_ms: number;
  viewer_render_ms: number;
  total_to_viewer_ms: number;
}

/**
 * A small delay before every fixture resolves, so the interface exercises its
 * real pending states — spinners, disabled controls, the cancel affordance —
 * instead of snapping to a finished frame.
 *
 * This is a presentation detail and NOT a simulation of real latency. The live
 * system took 18–33 s per question; that number is displayed with each answer
 * (spec_v013 §6.4) so the demo never implies otherwise.
 */
const FIXTURE_DELAY_MS = 120;

function settle<T>(value: T, signal?: AbortSignal): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new ApiError("canceled", "Request canceled."));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve(value);
    }, FIXTURE_DELAY_MS);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new ApiError("canceled", "Request canceled."));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/** Where the static Fragments artifact sits, under the Pages base path. */
function assetUrl(): string {
  return `${import.meta.env.BASE_URL}model.frag`;
}

export class ApiClient {
  viewerAssetUrl(_sourceModelId: number): string {
    return assetUrl();
  }

  async listModels(signal?: AbortSignal): Promise<ModelListResponse> {
    return settle(modelsFixture, signal);
  }

  async modelFloors(_sourceModelId: number, signal?: AbortSignal): Promise<ModelFloorsResponse> {
    return settle(floorsFixture, signal);
  }

  async resolveEntities(
    _sourceModelId: number,
    _globalIds: string[],
    signal?: AbortSignal,
  ): Promise<ResolveEntitiesResponse> {
    return settle(resolveFixture, signal);
  }

  /**
   * Three distinct purposes share this endpoint in the real application, so the
   * demo dispatches on the request shape (spec_v013 §4.4).
   */
  async query(request: SessionQueryRequest, signal?: AbortSignal): Promise<QueryResponseEnvelope> {
    // 1. The model-load handshake issued by `controller.confirmAndLoadModel`.
    if (request.confirm_model_id != null) {
      return settle(loadModelFixture, signal);
    }

    // 2. One of the three recorded questions.
    const question = questionForText(request.question ?? "");
    if (question) {
      const envelope = await answerFor(question);
      return settle(envelope, signal);
    }

    // 3. Unreachable through the UI, because the composer is a picker rather
    //    than a text field. Kept so an unexpected code path degrades honestly
    //    instead of throwing something the user cannot interpret.
    throw new ApiError(
      "bad_request",
      "This static demo can only answer the three questions listed below the transcript. Run the project locally to ask your own.",
    );
  }

  /** No telemetry sink exists in a static demo. */
  async reportQueryRenderTiming(_timing: QueryRenderTiming): Promise<void> {
    return;
  }

  async entityDetails(
    _sourceModelId: number,
    globalId: string,
    signal?: AbortSignal,
  ): Promise<EntityDetailsResponse> {
    const details = await entityDetailsFor(globalId);
    if (!details) {
      // A bounded set was captured (spec_v013 §7.3). Saying so plainly is the
      // point: the demo reports what it does not have rather than inventing it.
      throw new ApiError(
        "not_found",
        "This element's details weren't captured for the static demo. Every element is inspectable when the project runs locally.",
      );
    }
    return settle(details, signal);
  }

  async highlightGroup(
    _sourceModelId: number,
    selectedGlobalId: string,
    scope: HighlightScope,
    signal?: AbortSignal,
  ): Promise<HighlightGroupResponse> {
    const group = await highlightGroupFor(selectedGlobalId, scope);
    if (!group) {
      throw new ApiError(
        "not_found",
        "This grouping wasn't captured for the static demo.",
      );
    }
    return settle(group, signal);
  }

  async fetchViewerAsset(
    _sourceModelId: number,
    signal?: AbortSignal,
  ): Promise<ViewerAssetResult> {
    let res: Response;
    try {
      res = await fetch(assetUrl(), { signal });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new ApiError("canceled", "Request canceled.");
      }
      throw new ApiError("asset_unavailable", "The 3D model could not be loaded.", {
        retryable: true,
      });
    }
    if (!res.ok) {
      throw new ApiError("asset_unavailable", "The 3D model could not be loaded.", {
        status: res.status,
        retryable: true,
      });
    }
    const bytes = await res.arrayBuffer();
    return { bytes, etag: res.headers.get("ETag") };
  }
}

export const api = new ApiClient();
