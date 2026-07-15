// Typed API client: bounded error normalization + no raw backend detail
// (Task 11 Phase 3, spec_v006 §18.1).
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClient } from "../src/api/client";
import { ApiError } from "../src/api/types";

const client = new ApiClient("http://backend.test");

function stubFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status, headers })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("ApiClient", () => {
  it("returns parsed JSON on success", async () => {
    stubFetch(200, { models: [] });
    await expect(client.listModels()).resolves.toEqual({ models: [] });
  });

  it("maps network failure to a retryable backend_unavailable error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("fail"))));
    const err = await client.listModels().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.kind).toBe("backend_unavailable");
    expect(err.retryable).toBe(true);
  });

  it("maps AbortError to canceled", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => Promise.reject(new DOMException("aborted", "AbortError"))),
    );
    const err = await client.query({ question: "q", session_id: "s" }).catch((e) => e);
    expect(err.kind).toBe("canceled");
  });

  it("maps asset 404 missing to asset_missing without leaking detail", async () => {
    stubFetch(404, { detail: { status: "missing", message: "viewer asset not prepared" } });
    const err = await client.fetchViewerAsset(1).catch((e) => e);
    expect(err.kind).toBe("asset_missing");
    expect(err.message).not.toContain("C:\\");
  });

  it("maps asset 409 to asset_stale", async () => {
    stubFetch(409, { detail: { status: "stale" } });
    const err = await client.fetchViewerAsset(1).catch((e) => e);
    expect(err.kind).toBe("asset_stale");
  });

  it("maps asset 503 to retryable asset_unavailable", async () => {
    stubFetch(503, { detail: { status: "unavailable" } });
    const err = await client.fetchViewerAsset(1).catch((e) => e);
    expect(err.kind).toBe("asset_unavailable");
    expect(err.retryable).toBe(true);
  });

  it("maps 422 to bad_request and 500 to retryable server", async () => {
    stubFetch(422, {});
    const err1 = await client.query({ question: "q", session_id: "s" }).catch((e) => e);
    expect(err1.kind).toBe("bad_request");
    stubFetch(500, {});
    const err2 = await client.query({ question: "q", session_id: "s" }).catch((e) => e);
    expect(err2.kind).toBe("server");
    expect(err2.retryable).toBe(true);
  });

  it("builds the viewer asset URL from the model id only", () => {
    expect(client.viewerAssetUrl(7)).toBe("http://backend.test/api/models/7/viewer-asset");
  });
});
