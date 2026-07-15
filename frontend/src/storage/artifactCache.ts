// IndexedDB cache for prepared viewer artifacts (spec_v006 §9.4). The cache is a
// performance optimization, not application/conversation state: it survives both
// Clear Chat and Reset App and is never treated as authoritative. Keys bind the
// model id, source fingerprint, and artifact format version so a stale artifact
// is never reused after any of those change. A small LRU (default two) keeps
// local storage bounded; quota denial degrades gracefully to a non-persistent
// load rather than blocking the app.
import { openDB, type IDBPDatabase } from "idb";

import { ARTIFACT_FORMAT_VERSION, MAX_CACHED_ARTIFACTS } from "../config";

const DB_NAME = "bim-rag-viewer";
const STORE = "artifacts";

interface ArtifactRecord {
  key: string;
  sourceModelId: number;
  sourceFingerprint: string;
  formatVersion: string;
  bytes: ArrayBuffer;
  byteLength: number;
  cachedAt: number;
  lastUsed: number;
}

export function artifactKey(sourceModelId: number, sourceFingerprint: string): string {
  return `${sourceModelId}::${sourceFingerprint}::${ARTIFACT_FORMAT_VERSION}`;
}

let dbPromise: Promise<IDBPDatabase | null> | null = null;

async function getDb(): Promise<IDBPDatabase | null> {
  if (typeof indexedDB === "undefined") return null;
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, 1, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE)) {
          const store = db.createObjectStore(STORE, { keyPath: "key" });
          store.createIndex("lastUsed", "lastUsed");
        }
      },
    }).catch(() => null);
  }
  return dbPromise;
}

export interface CachedArtifact {
  bytes: ArrayBuffer;
  byteLength: number;
}

export async function getCachedArtifact(
  sourceModelId: number,
  sourceFingerprint: string,
): Promise<CachedArtifact | null> {
  const db = await getDb();
  if (!db) return null;
  const key = artifactKey(sourceModelId, sourceFingerprint);
  try {
    const rec = (await db.get(STORE, key)) as ArtifactRecord | undefined;
    if (!rec) return null;
    // Defensive stale-key guard even though the key already encodes identity.
    if (rec.sourceFingerprint !== sourceFingerprint || rec.formatVersion !== ARTIFACT_FORMAT_VERSION) {
      await db.delete(STORE, key);
      return null;
    }
    rec.lastUsed = Date.now();
    await db.put(STORE, rec).catch(() => undefined);
    return { bytes: rec.bytes, byteLength: rec.byteLength };
  } catch {
    return null;
  }
}

/** Store an artifact; returns false (without throwing) if quota/IDB is unavailable. */
export async function putCachedArtifact(
  sourceModelId: number,
  sourceFingerprint: string,
  bytes: ArrayBuffer,
): Promise<boolean> {
  const db = await getDb();
  if (!db) return false;
  const key = artifactKey(sourceModelId, sourceFingerprint);
  const now = Date.now();
  const rec: ArtifactRecord = {
    key,
    sourceModelId,
    sourceFingerprint,
    formatVersion: ARTIFACT_FORMAT_VERSION,
    bytes,
    byteLength: bytes.byteLength,
    cachedAt: now,
    lastUsed: now,
  };
  try {
    await evictToLimit(db, MAX_CACHED_ARTIFACTS - 1);
    await db.put(STORE, rec);
    return true;
  } catch {
    // QuotaExceededError or similar — fall back to a non-persistent load.
    return false;
  }
}

async function evictToLimit(db: IDBPDatabase, limit: number): Promise<void> {
  const keys = (await db.getAllKeys(STORE)) as string[];
  if (keys.length <= limit) return;
  const all = (await db.getAll(STORE)) as ArtifactRecord[];
  all.sort((a, b) => a.lastUsed - b.lastUsed);
  const toRemove = all.slice(0, all.length - limit);
  for (const rec of toRemove) {
    await db.delete(STORE, rec.key).catch(() => undefined);
  }
}

/** Test/diagnostic helper. */
export async function clearArtifactCache(): Promise<void> {
  const db = await getDb();
  if (!db) return;
  await db.clear(STORE).catch(() => undefined);
}
