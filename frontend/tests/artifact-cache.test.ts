// IndexedDB cache: key invalidation, LRU eviction, quota fallback
// (spec_v006 §9.4, §18.1). The idb module is mocked with an in-memory store so
// no real IndexedDB is needed.
import { beforeEach, describe, expect, it, vi } from "vitest";

interface Rec {
  key: string;
  [k: string]: unknown;
}

const mem = new Map<string, Rec>();
let failPuts = false;

vi.mock("idb", () => ({
  openDB: async () => ({
    get: async (_s: string, key: string) => mem.get(key),
    put: async (_s: string, rec: Rec) => {
      if (failPuts) throw new DOMException("quota", "QuotaExceededError");
      mem.set(rec.key, rec);
    },
    delete: async (_s: string, key: string) => void mem.delete(key),
    getAllKeys: async () => [...mem.keys()],
    getAll: async () => [...mem.values()],
    clear: async () => mem.clear(),
    objectStoreNames: { contains: () => true },
  }),
}));

import { artifactKey, getCachedArtifact, putCachedArtifact } from "../src/storage/artifactCache";
import { ARTIFACT_FORMAT_VERSION, MAX_CACHED_ARTIFACTS } from "../src/config";

beforeEach(() => {
  mem.clear();
  failPuts = false;
});

describe("artifact cache", () => {
  it("key binds model id, fingerprint, and format version", () => {
    expect(artifactKey(1, "abc")).toBe(`1::abc::${ARTIFACT_FORMAT_VERSION}`);
  });

  it("round-trips an artifact", async () => {
    const bytes = new Uint8Array([1, 2, 3]).buffer;
    expect(await putCachedArtifact(1, "fp1", bytes)).toBe(true);
    const hit = await getCachedArtifact(1, "fp1");
    expect(hit?.byteLength).toBe(3);
  });

  it("misses when the fingerprint changes (stale key never reused)", async () => {
    await putCachedArtifact(1, "fp-old", new Uint8Array([9]).buffer);
    expect(await getCachedArtifact(1, "fp-new")).toBeNull();
  });

  it("misses when the stored format version differs", async () => {
    await putCachedArtifact(1, "fp1", new Uint8Array([9]).buffer);
    const rec = mem.get(artifactKey(1, "fp1"))!;
    rec["formatVersion"] = "frag-OLD";
    expect(await getCachedArtifact(1, "fp1")).toBeNull();
  });

  it(`keeps at most ${MAX_CACHED_ARTIFACTS} artifacts (LRU eviction)`, async () => {
    await putCachedArtifact(1, "a", new Uint8Array([1]).buffer);
    await putCachedArtifact(2, "b", new Uint8Array([2]).buffer);
    await putCachedArtifact(3, "c", new Uint8Array([3]).buffer);
    expect(mem.size).toBeLessThanOrEqual(MAX_CACHED_ARTIFACTS);
    expect(await getCachedArtifact(3, "c")).not.toBeNull();
    expect(await getCachedArtifact(1, "a")).toBeNull(); // oldest evicted
  });

  it("returns false on quota denial instead of throwing", async () => {
    failPuts = true;
    await expect(putCachedArtifact(1, "fp", new Uint8Array([1]).buffer)).resolves.toBe(false);
  });
});
