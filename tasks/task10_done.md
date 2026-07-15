# Task 10: Narrow Backend Contract for the BIM Frontend

## Prerequisites

Require:

```text
tasks/task09_done.md
specs/spec_v002_query_architecture.md
specs/spec_v003_sql_query_path.md
specs/spec_v004_rag_query_path.md
specs/spec_v005_hybrid_query_orchestration.md
specs/spec_v006_frontend_application.md
```

If Task 09 is incomplete, stop. This task implements backend contracts only; do not implement the
React frontend or convert the full IFC model here.

## Objective

Add the smallest deterministic, read-only backend surface required by the frontend:

1. bounded model listing for a display-name selector;
2. safe prepared-viewer-artifact delivery;
3. active-model-scoped IFC GlobalId resolution;
4. GlobalId-based selected-object support in `POST /api/query`;
5. local Vite-origin CORS;
6. accurate OpenAPI contracts and offline/read-only tests.

These operations must not invoke an LLM, parse IFC, convert geometry, write the database, import
ingestion code, or expose filesystem paths.

## Owner intent

The backend remains the lightweight, independent Poetry application established by Task 09. It
queries existing PostgreSQL BIM information and serves an already-prepared immutable viewer asset.
It is not an ingestion or geometry-conversion application.

Preserve every completed SQL, graph, RAG, hybrid, session, grounding, safety, and viewer-action
behavior. Make only narrow compatible contract changes.

## Required implementation

### 1. Model list endpoint

Add a deterministic endpoint under the existing public API convention, recommended:

```text
GET /api/models
```

Return a bounded stable array containing only what the minimal selector/runtime needs:

```text
source_model_id
display_name
opaque asset version or source fingerprint
viewer_asset_status: ready | missing | stale | unavailable
```

Requirements:

- read through the dedicated read-only database role;
- deterministic ordering;
- safe default display name when editable display name is null;
- no full source path, local IFC path, canonical JSON, credentials, or ingestion internals;
- no catalog card/dashboard fields beyond the contract;
- no LLM call;
- safe behavior when no models exist.

### 2. Viewer-asset root and naming

Use the repository-level convention from v006:

```text
model_assets/{source_model_id}/{source_fingerprint}.frag
```

Implement backend-owned configuration for the asset root. The default may resolve from the
repository root, but must be overrideable for tests/local deployment without exposing the resolved
path to clients.

Derive the filename from the database model identity. Never accept a path, filename, drive letter,
or traversal segment from a request.

### 3. Viewer-asset endpoint

Add a safe binary endpoint, recommended:

```text
GET /api/models/{source_model_id}/viewer-asset
```

Requirements:

- verify the model exists;
- derive and resolve the expected artifact path;
- verify path containment under the configured root;
- distinguish missing/stale/unavailable with bounded responses;
- stream rather than load an unbounded file into Python memory;
- use an appropriate binary content type;
- use fingerprint-aware `ETag`/conditional caching where supported cleanly;
- add range support only if justified by the actual frontend/library behavior;
- never return the server path in body, headers, or errors;
- never convert IFC or write any file/database record during a request.

Update `viewer_actions.viewer_source_location` so browser-facing responses contain a safe HTTP API
path/URL or an equivalent opaque asset reference, never a Windows filesystem path.

### 4. GlobalId resolver

Add a read-only endpoint, recommended:

```text
POST /api/models/{source_model_id}/entities/resolve
```

Request:

```json
{
  "global_ids": ["..."]
}
```

Return compact ordered mappings:

```text
entity_id
global_id
ifc_class
name
```

Requirements:

- 1-5 GlobalIds only;
- strict request schema, size limits, trimming, stable deduplication;
- every SQL predicate includes `source_model_id`;
- parameterized SQL/ORM only;
- preserve request order for resolved rows;
- explicit bounded unresolved-ID reporting;
- no cross-model resolution;
- no canonical JSON or relationship expansion;
- no LLM call and no database write.

### 5. Browser selection in `POST /api/query`

Extend the request contract compatibly with:

```text
selected_global_ids: list[str], maximum 5
```

The frontend supplies GlobalIds plus `active_source_model_id`. Trusted backend code resolves these
to canonical entity IDs before planner context and selected-object SQL/RAG/graph behavior.

Requirements:

- reject selected GlobalIds without an active model;
- reject/bound malformed, duplicate, unresolved, or cross-model IDs before LLM context;
- never let browser-provided database integer IDs override a conflicting GlobalId selection;
- retain existing `selected_entity_ids` only for internal/backward compatibility if required by the
  completed tests, and document it as non-public/deprecated;
- update planner-context serialization and logs without exposing unnecessary data;
- preserve the existing maximum-five selected-object rule;
- selection resolution itself makes zero OpenAI calls.

### 6. Clear/reset compatibility

Do not redesign session behavior unnecessarily. Verify the frontend can:

- reset/retire the old backend session;
- create a fresh session ID;
- retain the active model locally for Clear Chat and supply it on the next request;
- unload/forget the model locally for Reset App.

If a narrow backend change is genuinely required to avoid stale server state, implement the
smallest typed deterministic control. Do not add an LLM call or persistent chat storage.

### 7. CORS

Allow the configured local frontend origin, default:

```text
http://localhost:5173
```

Use an explicit allowlist. Do not use wildcard origins with credentials. Make production/local
origins configurable without putting secrets in frontend configuration.

### 8. OpenAPI

Ensure model, asset, resolver, selected-GlobalId query, error, and existing response schemas appear
accurately in FastAPI OpenAPI. Keep types strict and bounded so Task 11 can generate TypeScript
contracts reproducibly.

## Tests

Add backend tests for:

- model-list ordering, null display name, empty catalog, and field allowlist;
- asset ready/missing/stale/unknown-model behavior;
- path containment and traversal resistance;
- binary streaming, content type, ETag, and conditional request behavior;
- absence of filesystem paths in all responses/errors;
- resolver success, stable order, duplicates, unresolved IDs, malformed IDs, more than five,
  cross-model isolation, and unknown model;
- query selected-GlobalId resolution before planner context;
- conflict handling between deprecated integer IDs and GlobalIds;
- unchanged viewer-action shape with safe asset reference;
- configured CORS allow/deny behavior;
- OpenAPI schema presence;
- zero OpenAI calls for model list, asset access, selection resolution, and reset controls;
- existing backend regression suite.

Use temporary small binary fixture artifacts. Do not convert or commit the full IFC/Fragments file
as a test fixture. Live database tests remain read-only. Normal tests must not call OpenAI.

## Required validation

From `backend/`:

```powershell
poetry install
poetry run ruff check app tests
poetry run pytest
poetry run uvicorn app.main:app --reload
```

Then validate with read-only/manual HTTP checks:

- `/health` and `/ready` unchanged;
- `/api/models` returns the current model safely;
- resolver maps sampled known GlobalIds within the current model;
- missing viewer artifact returns the specified bounded status until Task 11 prepares it;
- `POST /api/query` still works with existing requests and accepts the new GlobalId selection;
- model confirmation returns a browser-safe asset reference;
- database counts and corpus/vector metadata remain unchanged.

## Prohibited actions

- Do not implement frontend components.
- Do not install Node/frontend packages in this task.
- Do not parse or convert IFC.
- Do not add IfcOpenShell to the backend.
- Do not create or modify PostGIS geometry.
- Do not write/migrate/drop/truncate BIM tables.
- Do not regenerate corpus text or vectors.
- Do not import `bim_rag` or ingestion code.
- Do not expose arbitrary file serving or local paths.
- Do not add an LLM call to deterministic viewer operations.
- Do not run live OpenAI tests or recreate the deleted live provider test.
- Do not change public answer/viewer semantics beyond the required compatible additions.

## Acceptance criteria

1. All four frontend-facing capabilities are deterministic and read-only.
2. Backend remains independently installable/runnable through Poetry.
3. No backend import/dependency on ingestion or IfcOpenShell exists.
4. Browser identity uses active-model-scoped GlobalIds.
5. Asset delivery cannot escape the configured root or expose server paths.
6. Existing query behavior and tests remain valid.
7. OpenAPI is sufficient for generated frontend types.
8. CORS accepts `localhost:5173` and rejects unconfigured origins.
9. Normal tests make zero OpenAI calls.
10. Database table counts, data, and vectors are unchanged.

## Completion report

Rename to `tasks/task10_done.md` only when complete. Append:

- routes and schemas added/changed;
- asset-root/naming behavior;
- GlobalId resolution and query integration behavior;
- backward-compatibility decisions;
- CORS/OpenAPI results;
- tests and startup results;
- database before/after counts;
- confirmation that no IFC conversion, DB mutation, PostGIS work, or OpenAI call occurred;
- explicit statuses:

```text
Model list contract: VALIDATED
Viewer asset delivery contract: VALIDATED
GlobalId resolution contract: VALIDATED
GlobalId query-selection contract: VALIDATED
CORS/OpenAPI contract: VALIDATED
Existing backend behavior: REGRESSION VALIDATED
Database non-mutation: VALIDATED
Frontend implementation: NOT STARTED
```

---

## Completion report (delivered)

### Routes and schemas added/changed

- New router `app/api/routes/models.py` (prefix `/api/models`), all read-only and LLM-free:
  - `GET /api/models` — deterministic bounded selector list.
  - `GET /api/models/{source_model_id}/viewer-asset` — streamed prepared artifact.
  - `POST /api/models/{source_model_id}/entities/resolve` — GlobalId → compact identity.
- New schemas `app/api/schemas/models.py`: `ModelListItem`, `ModelListResponse`,
  `ResolveEntitiesRequest`, `ResolvedEntity`, `ResolveEntitiesResponse` (all `extra="forbid"`).
- `ViewerAssetStatus` enum added to `app/shared/types.py`.
- `app/api/schemas/request.py`: added public `selected_global_ids` (max 5); documented
  `selected_entity_ids` as deprecated/internal.
- `app/api/app.py`: registered the models router + explicit CORS allowlist middleware.
- `app/config/settings.py`: `viewer_asset_root`, `cors_allow_origins`, `get_viewer_asset_root()`.
- New helpers: `app/viewer/assets.py` (path derivation/containment/status/`viewer_asset_ref`),
  `app/query/selection.py` (trusted selection resolution).
- New read-only DB selectors: `catalog.list_selector_models`, `catalog.get_model_asset_identity`,
  `entities.resolve_entities_by_global_ids`.

### Asset-root / naming behavior

- Root resolved by `Settings.get_viewer_asset_root()` — default `<repo>/model_assets`, overridable
  via `VIEWER_ASSET_ROOT`. The resolved server path is never returned to clients.
- Expected artifact path derived from DB identity only:
  `{root}/{source_model_id}/{source_fingerprint}.frag`. Containment enforced by resolving both
  sides and checking `relative_to`. No request-supplied path/filename/drive/traversal is accepted.
- Status classification (`compute_asset_status`): `ready` (fingerprint file present), `stale`
  (a `.frag` exists for a different fingerprint), `missing` (none), `unavailable` (catalog status
  `unavailable` or unresolvable root). Asset endpoint maps these to 200 / 409 / 404 / 503; unknown
  model → 404. Streaming via `FileResponse` (chunked, never loaded whole into memory), fingerprint
  `ETag` + conditional `If-None-Match` → 304, `application/octet-stream`, Range provided by the
  framework. No server path appears in any body, header, or error.

### GlobalId resolution & query integration

- `resolve_entities_by_global_ids`: every predicate scoped by `source_model_id` (cross-model IDs
  never resolve), compact rows only (no `canonical_json`), parameterized ORM, no write, no LLM.
- `app/query/selection.py`: trim / stable-dedupe / preserve order, active-model requirement,
  bounded unresolved-ID warnings, and GlobalId-vs-integer conflict rejection.
- `POST /api/query`: rejects a GlobalId selection with no active model before any LLM/DB work;
  otherwise resolves `selected_global_ids` → entity IDs before planner context and carries bounded
  selection warnings on the response.

### Backward-compatibility decisions

- `selected_entity_ids` retained only as deprecated/internal; it never overrides a conflicting
  `selected_global_ids` selection — disagreement is rejected (spec_v006 §10.4).
- `viewer_actions.viewer_source_location` on model confirmation now emits the safe HTTP reference
  `/api/models/{id}/viewer-asset` instead of the database filesystem path.

### CORS / OpenAPI results

- CORS: explicit allowlist (default `http://localhost:5173`), `allow_credentials=False`, no wildcard.
  Configured origin is echoed; an unconfigured origin is not (tests).
- OpenAPI: all three new paths and the request/response schemas are present, and
  `selected_global_ids` appears on `SessionQueryRequest` (tests).

### Tests and startup results

- `poetry run ruff check app tests` — clean; `ruff format` applied to changed files.
- `poetry run pytest -m "not live"` — 268 passed. Live package auto-skips without DB.
- New offline tests: viewer-asset helpers; selection resolution; model/asset/resolve endpoints
  (ordering, safe default name, empty catalog, field allowlist, ready/missing/stale/unknown-model,
  ETag/304, no path leakage, resolver order/dedupe/unresolved/>5/cross-model/unknown-model); CORS
  allow/deny; OpenAPI presence; zero-OpenAI deterministic paths; query GlobalId contract.
- App imports and serves via `TestClient`; `poetry run uvicorn app.main:app` unchanged.

### Database before/after counts (read-only live validation, no OpenAI)

| table | before | after |
| --- | --- | --- |
| ifc_source_models | 1 | 1 |
| ifc_entities | 6989 | 6989 |
| ifc_relationships | 3473 | 3473 |
| relationship_members | 17668 | 17668 |
| rag_documents | 10462 | 10462 |
| source_model_catalog_entries | 1 | 1 |
| model_families | 1 | 1 |

Live checks exercised only the read-only model-list/asset/resolve paths: `/api/models` returned the
Schependomlaan model with `viewer_asset_status="missing"` (artifact not yet prepared — Task 11);
`/api/models/1/viewer-asset` returned bounded 404 `missing`; sampled real GlobalIds resolved with
IFC class/name and a bogus ID reported as unresolved; resolving under a non-existent model → 404.

### Confirmation

No IFC parsing/conversion, no database mutation/migration, no PostGIS work, and no OpenAI call
occurred in any Task 10 deterministic operation or in validation.

