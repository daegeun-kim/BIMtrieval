# Specification v006: Frontend BIM Viewer and Conversational Application

## 1. Purpose and authority

Define the first runnable frontend for the BIM RAG project: a lightweight, desktop-oriented,
local application that connects the completed natural-language query pipeline to an interactive
3D BIM viewer.

This specification is authoritative for frontend behavior and for the narrow read-only backend
contracts required by the frontend. It is governed by:

```text
spec_v002_query_architecture.md
spec_v003_sql_query_path.md
spec_v004_rag_query_path.md
spec_v005_hybrid_query_orchestration.md
tasks/task09_done.md
```

Where an older frontend example conflicts with this specification, v006 takes precedence.
Backend query semantics remain governed by v002-v005.

## 2. Owner intent

This is an interaction and visualization test for the BIM RAG pipeline, not a complete BIM
authoring product. Start small, lightweight, and fast. Validate that a user can:

1. select and load an existing preprocessed BIM model;
2. navigate and select objects in a 3D viewer;
3. ask natural-language questions;
4. receive grounded answers from SQL, graph, RAG, or hybrid retrieval;
5. see primary and relationship-context results highlighted in the model;
6. use selected viewer objects as bounded context for follow-up questions;
7. clear the conversation or reset the complete visible application state.

The LLM layer must remain as small as possible. Model listing, asset delivery, GlobalId resolution,
selection, caching, UI behavior, and resets are deterministic operations and must not invoke an
LLM. The frontend never connects directly to PostgreSQL or OpenAI.

Visual and component-level details may be decided during implementation with Claude's installed
`frontend-design` plugin, but that design discretion must not expand the product scope, change the
data/API contracts, add unnecessary panels, or compromise rendering performance.

## 3. Independent application boundary

The repository contains independent applications:

```text
ingestion/   # IFC -> PostgreSQL tables and pgvector documents
backend/     # read-only FastAPI query service
frontend/    # this React/Three.js application
```

The frontend must not import ingestion or backend source code. It consumes versioned HTTP
contracts and immutable viewer assets only.

PostgreSQL remains the source for model metadata, BIM attributes, relationships, canonical
identity, and embeddings. A prepared Fragments file is the browser rendering representation.
The viewer artifact is data, not shared application code.

## 4. Scope

### 4.1 Included

- React + TypeScript frontend application
- Vite development/build tooling
- npm dependency management
- bright-mode, desktop-first interface
- full-window Three.js/That Open BIM viewer
- floating, resizable, collapsible chat panel
- minimal model selector using display names
- explicit model-load confirmation
- optimized prepared Fragments asset loading
- IndexedDB artifact caching
- IFC GlobalId-based viewer/backend identity
- maximum-five viewer selection with chat-context chips
- SQL/RAG/graph/hybrid answer display
- primary/context highlighting and background dimming
- clickable entity citations that center and moderately enlarge the target
- compact, collapsed evidence details
- Clear Chat and Reset App controls
- loading, cancellation, error, retry, and degraded-state behavior
- local frontend/backend development integration
- deterministic narrow backend contracts defined in Section 10
- unit/component and bounded browser integration tests

### 4.2 Excluded

- user IFC upload
- IFC parsing during normal frontend startup
- runtime IFC-to-Fragments conversion in FastAPI
- PostGIS geometry ingestion or direct PostGIS-to-Three.js rendering
- mobile-first UI
- authentication or multi-user accounts
- persistent chat history after the browser tab/session ends
- charts, dashboards, catalog cards, or a catalog landing page
- full object property panel
- storey/class visibility controls
- hide/isolate tools
- measurement and section planes
- annotations or saved viewpoints
- model or metadata editing
- geometry editing
- streamed LLM tokens
- frontend OpenAI access
- frontend database access
- production/cloud deployment

## 5. Explorentory as UX reference

Use the local Explorentory frontend as a behavioral reference:

```text
C:\Users\kdgki\Desktop\MSCDP\Projects\Capstone\Explorentory\frontend
```

Retain useful interaction principles:

- visualization is the dominant workspace;
- conversation is continuously available;
- the input stays anchored at the bottom of the chat surface;
- panels can be resized without breaking the visualization;
- loading and connection failures are visible and actionable;
- reset behavior is explicit;
- visual and conversational selections remain linked.

Do not copy Explorentory's global plain-JavaScript implementation or real-estate-specific workflow.
Use a typed component/state architecture appropriate for BIM geometry and API contracts.

## 6. Technology baseline

Use:

```text
React
TypeScript with strict type checking
Vite
npm
Three.js
current maintained That Open Components / Fragments packages
Zustand or an equivalently small state layer
IndexedDB through a small maintained wrapper where helpful
Vitest
React Testing Library
Playwright for a small critical-path browser suite
```

Before implementation, verify current That Open package names, compatibility, worker/WASM setup,
and recommended Fragments APIs against official documentation. Do not use deprecated
`web-ifc-three` or `web-ifc-viewer` packages when the maintained Components/Fragments stack is
available.

Keep dependencies small. Do not add a large UI framework unless the `frontend-design` workflow
shows a concrete need that cannot be met cleanly with lightweight components and CSS. Record the
reason for every material dependency.

Normal development is:

```powershell
cd frontend
npm install
npm run dev
```

The development URL is `http://localhost:5173`. VS Code Go Live is not the source-development
workflow. A static server may serve `dist/` only after `npm run build` if the built asset paths and
runtime configuration are verified.

## 7. Visual structure

### 7.1 Primary layout

The 3D viewer fills the browser viewport. The conversational surface floats above the viewer near
the right edge rather than dividing the page with a full-height hard separator.

The chat panel must have:

- clear outer margin from viewport edges;
- rounded/filleted corners;
- restrained bright-mode surface and shadow/border separation;
- a resizable width within safe desktop bounds;
- a collapse/expand control;
- an answer-history region;
- a bottom-anchored composer;
- compact model/reset controls that do not dominate the conversation.

When collapsed, the viewer expands visually and a small accessible control restores the panel.
Resizing must trigger the viewer/renderer resize path without stretching or clipping the canvas.

### 7.2 Bright mode only

Implement one coherent bright theme. Do not add a theme toggle or dark-theme assets. Use readable
contrast, visible focus states, and colors that remain distinguishable over varied model materials.

### 7.3 Minimal information

Do not display branding or a product title beyond a neutral browser title if required. Show only:

- active model display name;
- concise model/loading status;
- minimal technical/model information near the bottom-left of the viewer when useful;
- selection count/chips near the composer;
- collapsed evidence summaries beneath answers.

Do not create a permanent metadata inspector or dashboard.

## 8. Application lifecycle

### 8.1 Initial state

On startup:

- create or restore one tab-scoped frontend session from `sessionStorage`;
- show an empty viewer with a concise instruction;
- show the floating chat panel;
- fetch the deterministic model list;
- populate a minimal display-name selector;
- do not auto-load a large model;
- allow catalog/general questions before a model is active.

There is no catalog page and no card grid.

### 8.2 Selecting and loading a model

A model can be proposed through either:

- the deterministic display-name selector; or
- compact candidate controls returned by a catalog chat answer.

Both routes require explicit user confirmation before downloading/loading geometry. Confirmation
uses the existing backend model-confirmation semantics and the frontend asset endpoint. Never load
a candidate merely because the planner mentioned it.

During loading, display bounded phases such as metadata, download/cache, viewer initialization,
and scene ready. Progress must not imply precision the underlying library cannot provide.

If model loading fails, keep chat available for catalog/general questions and provide one explicit
retry action. Do not loop automatically.

### 8.3 Model switching

The selector remains available after load. Switching requires confirmation, cancels outstanding
viewer work, clears model-specific results/selections, safely disposes the old scene, and loads the
new artifact. Do not retain cross-model selected GlobalIds or highlights.

## 9. Viewer asset preparation and delivery

### 9.1 Rendering representation

Use a prepared That Open Fragments artifact for normal visualization. Do not reconstruct the scene
from PostGIS and do not parse the raw IFC on every load.

The repository-level local artifact convention is:

```text
model_assets/
└── {source_model_id}/
    └── {source_fingerprint}.frag
```

The backend derives the expected path from allowlisted configuration plus database model identity.
No user-supplied filesystem path may be joined or opened directly.

### 9.2 One-time TypeScript preparation tool

Provide a manual TypeScript/npm preparation command under the frontend project, using the same
maintained That Open Fragments importer/version family used by the viewer. It may read a local IFC
path and must write only to the validated artifact convention.

For the initial model, prepare from:

```text
C:\Users\kdgki\Desktop\MSCDP\Projects\BIM_RAG\ingestion\ifc_original\IFC Schependomlaan incl planningsdata.ifc
```

This tool:

- is not imported or invoked by FastAPI;
- is not part of normal `npm run dev` startup;
- does not import `bim_rag`;
- does not write PostgreSQL;
- does not replace or edit the source IFC;
- preserves the identity information needed to map rendered items to IFC GlobalIds;
- records format/library version and source fingerprint metadata;
- writes atomically so a failed conversion cannot leave a valid-looking partial artifact;
- validates the completed artifact by loading it and sampling identity mappings.

Do not add a Python/IfcOpenShell converter to the backend. If current That Open APIs require a
minor adjustment to the file extension or sidecar metadata, Claude may choose the supported format
while preserving this architecture and documenting the choice.

### 9.3 Backend delivery

The backend streams only the expected artifact for an existing model. Require:

- model existence and current fingerprint validation;
- path containment under the configured asset root;
- no arbitrary path query parameter;
- correct binary content type;
- `ETag` or equivalent fingerprint-aware caching;
- bounded errors for absent, stale, or unreadable artifacts;
- optional range support only if the library/browser benefits and implementation remains simple;
- no conversion and no database write.

### 9.4 IndexedDB cache

Cache the downloaded artifact in IndexedDB using a key containing at least:

```text
source_model_id
source_fingerprint
artifact_format_version
```

Validate the key before reuse. Never reuse a stale artifact after the source fingerprint or format
changes. Start with a small configurable LRU limit appropriate to a local prototype (recommended
default: at most two model artifacts) and gracefully handle quota denial by falling back to a
non-persistent load.

The cache survives Clear Chat and Reset App. Cache persistence is a performance optimization, not
conversation/application state. No cache-management UI is required in the MVP.

## 10. Narrow deterministic backend contracts

Implement these contracts in a separate backend task before frontend integration. Exact route
naming may be adjusted to match existing conventions, but behavior and separation are fixed.

### 10.1 Model list

Provide a read-only model-list endpoint for the minimal selector. Return only bounded fields needed
by the UI, including:

```text
source_model_id
display_name
source_fingerprint or opaque asset version
viewer_asset_status
```

Do not expose local filesystem paths, database credentials, canonical JSON, or ingestion details.
The selector displays only `display_name`; other fields support identity/cache/status internally or
appear as minimal bottom-left viewer information.

### 10.2 Viewer asset

Provide a read-only binary endpoint such as:

```text
GET /api/models/{source_model_id}/viewer-asset
```

Follow Section 9.3.

### 10.3 GlobalId resolution

Provide a deterministic read-only endpoint such as:

```text
POST /api/models/{source_model_id}/entities/resolve
```

Request:

```json
{
  "global_ids": ["IFC-GLOBAL-ID"]
}
```

Requirements:

- maximum five identifiers;
- trim/deduplicate while preserving stable order;
- scope every lookup to the route `source_model_id`;
- reject malformed or cross-model identity;
- return compact mappings such as entity ID, GlobalId, IFC class, and name;
- never return full canonical JSON;
- never invoke an LLM;
- never write the database.

### 10.4 Query request selection

Extend `POST /api/query` compatibly so the frontend can supply selected IFC GlobalIds scoped by
`active_source_model_id`. The frontend must not need database integer IDs. Trusted backend code
resolves GlobalIds before building planner context or selected-object retrieval plans.

Retain backward compatibility for existing internal/backend tests where practical, but make
GlobalIds the public browser contract. Never accept both representations when they disagree.

### 10.5 CORS and configuration

Allow only the configured local frontend origin, initially:

```text
http://localhost:5173
```

Do not use wildcard CORS with credentials. The frontend reads its base URL from:

```text
VITE_API_BASE_URL=http://localhost:8000
```

No frontend environment variable may contain OpenAI or database credentials.

### 10.6 OpenAPI types

Generate or derive frontend TypeScript API types from FastAPI OpenAPI. Keep generation reproducible
and checked by CI/tests. Do not hand-maintain multiple contradictory response interfaces.

### 10.7 Implementation status (Task 10 — delivered)

The narrow backend contracts in §10 are implemented and validated (see `tasks/task10_done.md`). As
built, read-only and LLM-free:

- `GET /api/models` — bounded selector list: `source_model_id`, `display_name` (safe
  `"Model {id}"` default when null), `source_fingerprint`, `viewer_asset_status`
  (`ready | missing | stale | unavailable`). Deterministic order by id; field-allowlisted.
- `GET /api/models/{source_model_id}/viewer-asset` — verifies model existence, derives the expected
  path `{root}/{source_model_id}/{source_fingerprint}.frag` from database identity only, enforces
  containment under the configured root, streams via `FileResponse` with a fingerprint `ETag` and
  `If-None-Match` → 304, and returns bounded 404 `missing` / 409 `stale` / 503 `unavailable`. No
  server path is ever returned.
- `POST /api/models/{source_model_id}/entities/resolve` — 1–5 GlobalIds, trimmed/stable-deduped,
  every lookup scoped to the route model (no cross-model resolution), compact identity only
  (`entity_id`, `global_id`, `ifc_class`, `name`), with explicit `unresolved` reporting.
- `POST /api/query` — public `selected_global_ids` (max 5) resolved to canonical entity IDs by
  trusted backend code before planner context; selection with no active model is rejected before any
  LLM/DB work; deprecated `selected_entity_ids` never overrides a conflicting GlobalId selection.
- `viewer_actions.viewer_source_location` now carries the safe HTTP reference
  `/api/models/{id}/viewer-asset`, never a filesystem path.
- CORS: explicit allowlist (`viewer_asset_root` and `cors_allow_origins` are backend-owned settings;
  default origin `http://localhost:5173`, no wildcard-with-credentials).

The asset root default is `<repo>/model_assets` (overridable via `VIEWER_ASSET_ROOT`). The current
model reports `viewer_asset_status="missing"` until the Task 11 preparation tool writes the artifact.

## 11. Viewer behavior

### 11.1 Camera and basic controls

Provide only the controls needed for the LLM/viewer experiment:

- orbit, pan, and zoom with conventional mouse controls;
- fit/home model;
- click selection;
- Ctrl/Shift additive selection;
- response-driven highlight and fit;
- citation-driven center and fit.

Do not add hide/isolate, measurements, sections, storey browser, class tree, or editing controls.

Fitting an object/result must center and enlarge it only moderately. Keep surrounding geometry
visible and enforce a maximum approach/zoom so one small element never fills the entire viewport.

### 11.2 Manual selection

- Maximum five selected objects.
- Clicking an object obtains its IFC GlobalId locally and resolves it through the deterministic
  backend endpoint.
- Show compact removable selection chips near the composer.
- If five objects are already selected, explain the limit rather than silently replacing one.
- Clicking empty viewer space clears manual selection.
- No separate Clear Selection button is required.
- Debounce/deduplicate resolution requests and ignore stale responses after model/session changes.

Selected objects are included with the next question. Selecting geometry alone never calls the
LLM.

### 11.3 Query results

Apply the complete semantic roles returned in `viewer_actions`:

- primary matches: strong accessible highlight;
- relationship context: distinct secondary, more muted highlight;
- non-results: visibly dimmed while retaining spatial context;
- relationship records themselves: evidence only, never rendered as meshes.

Implement `select_and_fit`, `select_only`, `clear`, and `none` defensively. Missing/unrenderable
GlobalIds must create a bounded warning without breaking the answer or viewer.

Manual selection and query-result roles must remain internally distinct even if they overlap.

### 11.4 Clickable answer entities

Entity references displayed with an answer are clickable. Clicking one:

- verifies it belongs to the active model;
- selects/highlights the rendered object;
- centers it;
- zooms only slightly/moderately;
- does not submit a query or call the LLM.

## 12. Chat behavior

### 12.1 Conversation surface

Use familiar chat interaction standards:

- visually distinct user and assistant messages;
- scrollable history with sensible auto-scroll behavior;
- composer fixed at the panel bottom;
- Enter submits;
- Shift+Enter inserts a newline;
- disabled submit for blank input;
- visible pending state;
- cancel control while a request is pending;
- no automatic duplicate submission;
- accessible keyboard/focus behavior.

The `frontend-design` plugin may determine precise message styling and micro-interactions.

### 12.2 Answer rendering

Render sanitized Markdown supporting ordinary paragraphs, lists, emphasis, code snippets, and
small tables. Disable raw HTML and unsafe URL protocols.

Each answer may include a compact evidence disclosure, collapsed by default, containing:

- route and answer basis;
- SQL/RAG/relationship counts where present;
- primary entities;
- relationship-context entities;
- relationships;
- warnings/notes.

Never display raw prompts, raw SQL, vectors, credentials, unrestricted canonical JSON, or internal
stack traces.

Clarification questions from the backend appear as normal assistant messages. Catalog candidates
appear as compact selectable controls, not a separate catalog page.

### 12.3 Request lifecycle

The current backend is non-streaming. Show honest staged/busy feedback rather than fake token
streaming. Allow frontend cancellation through `AbortController`; treat server cancellation as
best-effort. Ignore late responses whose request, session, or active model is no longer current.

For a retryable connection/provider failure, show one user-triggered Retry action. This is an MVP
convenience expected to be reconsidered later. Never retry an LLM query automatically.

## 13. State and clearing semantics

Use a small typed store with separate conceptual state for:

- tab/session identity;
- active/pending model;
- model and artifact status;
- chat messages and bounded history;
- manual viewer selections;
- current query evidence and viewer roles;
- pending request/cancellation identity;
- panel dimensions/collapse state.

Persist only appropriate current-tab state to `sessionStorage`. Do not use localStorage for chat
history. Persist model artifacts separately in IndexedDB.

### 13.1 Clear Chat

Clear Chat must:

- cancel/retire the current query;
- clear visible messages and bounded history supplied to the LLM;
- clear current answer evidence and query-result highlights/dimming;
- establish a fresh backend/frontend conversation identity;
- keep the active model loaded;
- keep manual viewer selection and selection chips;
- keep the IndexedDB model cache;
- keep panel layout preferences.

It must not delete or alter database data.

### 13.2 Reset App

Reset App must:

- cancel/retire pending requests and loads;
- clear messages, LLM history, evidence, manual selections, and result roles;
- clear the active/pending model;
- dispose/unload scene geometry and viewer resources;
- return to the initial model-selection state;
- establish a fresh session identity;
- keep the IndexedDB model cache;
- keep safe UI layout preferences if they do not change initial product state.

It must not delete stored models, database data, vectors, or prepared artifacts.

Both controls require clear labels/tooltips. Reset App should require lightweight confirmation if
accidental activation would discard a meaningful conversation.

## 14. Performance and resource policy

Prioritize responsiveness and conservative thresholds:

- load only one active model into the scene;
- use prepared Fragments, workers, culling/LOD facilities supported by the maintained stack;
- do not fetch full canonical JSON for selection or chat display;
- keep selection at five;
- keep evidence lists bounded by the backend contract;
- avoid rerendering the whole React tree on camera movement;
- keep Three.js/That Open mutable objects outside serializable React state where appropriate;
- debounce resize and identity-resolution work;
- dispose models, materials, workers, event listeners, object URLs, and GPU resources on switch/reset;
- cache at most a small number of artifacts initially;
- measure first-load, cached-load, scene-ready, query, highlight, and reset timing;
- report actual results rather than inventing unsupported performance claims.

If the current IFC cannot meet usable local interaction with supported Fragments settings, report
the measured bottleneck before raising limits, adding large dependencies, or reducing identity
correctness.

## 15. Failure behavior

Provide explicit, recoverable states for:

- backend unavailable;
- model list unavailable;
- asset missing/stale;
- artifact download failure;
- IndexedDB unavailable/quota denied;
- worker/WASM initialization failure;
- unsupported/corrupt Fragments artifact;
- GlobalId not renderable or not resolvable;
- query timeout/cancellation;
- LLM unavailable;
- SQL/RAG degraded modes returned by backend;
- stale response after model/reset change.

Do not expose credentials, local paths, stack traces, prompts, or provider internals. Do not crash
the whole UI because one entity cannot be highlighted.

## 16. Accessibility and desktop support

Target current desktop Chromium/Edge for the local prototype. Maintain sensible behavior at common
laptop resolutions. Phone support is not required.

Require:

- keyboard-operable chat/model/reset controls;
- visible focus indicators;
- labels/tooltips for icon-only controls;
- sufficient bright-theme contrast;
- status text in addition to color;
- reduced-motion respect for nonessential transitions;
- an accessible non-canvas representation of selected/result entity names in chat/chips.

The 3D canvas itself need not be fully keyboard-navigable in this MVP, but all essential query and
reset behavior must remain available without precise pointer interaction.

## 17. Security and privacy

- No `OPENAI_API_KEY`, `db_url`, database credential, or complete local source path in frontend
  source, build output, storage, logs, errors, or network payloads.
- The frontend calls only the backend HTTP API and approved local viewer-asset route.
- Sanitize Markdown and URLs.
- Treat all API strings and model names as untrusted display data.
- Never construct an asset URL from an arbitrary filesystem path.
- Do not allow directory traversal through model IDs or asset routes.
- Do not place full model data or chat history in analytics; no analytics are required.
- Do not add authentication for this local MVP, but keep boundaries compatible with later auth.

## 18. Testing and validation

### 18.1 Unit/component tests

Cover:

- generated API type use and response validation;
- model selector and confirmation;
- chat submission, Enter/Shift+Enter, cancellation, clarification, error, and manual retry;
- evidence collapse and safe Markdown;
- selected-chip maximum/removal;
- GlobalId resolution scope/deduplication;
- viewer-action role mapping;
- moderate fit/camera guard behavior through viewer-adapter tests;
- stale response rejection;
- Clear Chat versus Reset App semantics;
- sessionStorage restoration;
- IndexedDB key invalidation and quota fallback;
- no secret/config leakage.

Mock network, viewer, worker, and LLM-backed API behavior. Frontend tests must never call OpenAI or
PostgreSQL directly.

### 18.2 Browser integration tests

Use a small stable prepared fixture artifact, not the full production IFC, for automated browser
tests. Cover the critical path:

```text
start -> list models -> confirm/load -> select object -> ask -> receive answer
-> highlight primary/context -> click citation -> Clear Chat -> Reset App
```

Keep full-model performance validation as a separate local manual check so routine tests remain
fast and reliable.

### 18.3 Contract tests

Validate the frontend against backend OpenAPI and representative payloads for:

- model list;
- viewer asset success/missing/stale;
- GlobalId resolution;
- query answers for SQL, RAG, graph, hybrid, clarify, error, and catalog candidate routes;
- stable `viewer_actions` including empty groups;
- CORS from `http://localhost:5173`.

### 18.4 Full local acceptance test

Run backend:

```powershell
cd backend
poetry run uvicorn app.main:app --reload
```

Run frontend in a separate terminal:

```powershell
cd frontend
npm install
npm run dev
```

Prepare the current model artifact once if absent, then verify uncached and cached loading,
selection identity, representative chat queries, highlighting, citations, both clear operations,
resource disposal, and database non-mutation.

## 19. Deferred PostGIS direction

PostGIS is valuable for later spatial SQL such as 3D proximity, intersection, bounding boxes,
centroids, and spatial filtering. It is not part of this frontend specification.

A future PostGIS specification should keep geometry ingestion under the independent ingestion
application and expose only safe read-only spatial operations to the backend. Even then, PostGIS
geometry does not replace the optimized Fragments viewer artifact.

Do not install PostGIS, add geometry tables, extract IFC geometry into PostgreSQL, or add spatial
planner operations under v006.

## 20. Acceptance criteria

The frontend MVP is acceptable only when:

1. React/TypeScript/Vite/npm development and production builds succeed.
2. The design is implemented using Claude's `frontend-design` plugin and conforms to the minimal
   bright floating-panel intent.
3. The backend and frontend remain independent applications.
4. No frontend code imports backend/ingestion code or contains secrets.
5. The prepared artifact is reproducible, validated, immutable, and identity-compatible.
6. The backend serves artifacts safely without parsing IFC or writing the database.
7. The current model loads successfully from both network and IndexedDB cache paths.
8. Viewer selection resolves by GlobalId within the active model, maximum five.
9. SQL/RAG/graph/hybrid answers produce correct role-based viewer behavior.
10. Citation clicks center and moderately enlarge objects without excessive zoom.
11. The floating chat panel resizes/collapses without breaking the viewer.
12. Clear Chat and Reset App follow their distinct required semantics.
13. Normal UI actions other than question submission/model-catalog questions do not invoke an LLM.
14. Errors are bounded, actionable, and do not expose internal secrets/paths.
15. Automated tests pass without live OpenAI or direct database access from frontend tests.
16. Full local integration works with backend `:8000` and frontend `:5173`.
17. No IFC/database/vector/PostGIS mutation occurs during frontend operation or validation.
18. No excluded feature is added merely because a component library makes it available.

## 21. Required implementation sequencing

Implement in two tasks:

1. A narrow backend viewer-contract task: model list, safe artifact delivery, GlobalId resolution,
   browser selection contract, CORS, and contract tests. No frontend implementation.
2. A frontend implementation task using the completed backend contract and Claude's
   `frontend-design` plugin.

Do not combine these tasks. The frontend task must stop if the backend contract prerequisite is
not complete or if the installed `frontend-design` plugin cannot be invoked.

## 22. Implementation status (Tasks 10 + 11 — delivered)

Both sequenced tasks are complete (details: `tasks/task10_done.md`, `tasks/task11_done.md`).

- Frontend delivered at `frontend/`: React 18 + TS strict + Vite 6 + npm; That Open
  `@thatopen/components`/`@thatopen/fragments` 3.4.6, three 0.185.1, zustand 5; design implemented
  with the `frontend-design` plugin ("measured drawing": bright sheet, blueprint-blue primary,
  ochre context, teal manual selection, Space Grotesk / IBM Plex Sans / IBM Plex Mono).
- Architecture: single typed API client over generated OpenAPI types (`npm run gen:api`); all
  imperative scene code in `src/viewer/ViewerAdapter.ts`; zustand store for serializable state +
  controller for async flows; fragments worker bundled locally (no CDN).
- Prepared artifact: `npm run prepare:model` converted the Schependomlaan IFC (65.1 MB) to a
  validated 5.48 MB `.frag` in ~5 s at `model_assets/1/{sha256}.frag` with GlobalId identity
  round-trip validation; artifact gitignored, small `smoke-wall` fixture tracked for tests.
- Caching: IndexedDB keyed by model id + fingerprint + format version, LRU 2, quota fallback;
  survives Clear Chat and Reset App. Measured: uncached load→ready 2.8 s, cached 2.6 s.
- Validation: typecheck/lint/39 unit tests/build/2 Playwright e2e all green; backend regression
  268 tests green; full live integration exercised SQL/RAG/graph questions with role-based
  highlighting, citations, clear/reset; DB and vector metadata byte-identical before/after.
- PostGIS remains deferred (§19).
