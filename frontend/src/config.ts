// Runtime configuration. The only external endpoint the frontend ever contacts
// is the local backend HTTP API (spec_v006 §17). No secrets/paths live here.
export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  "http://localhost:8000";

// Bumped whenever the artifact encoding changes so stale IndexedDB entries are
// never reused across format changes (spec_v006 §9.4).
export const ARTIFACT_FORMAT_VERSION = "frag-3.4";

// Conservative local-prototype limits (spec_v006 §11.2, §14).
export const MAX_SELECTION = 5;
export const MAX_HISTORY_TURNS = 20;
export const MAX_CACHED_ARTIFACTS = 2;
