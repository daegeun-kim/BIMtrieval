# Specification v006: Frontend Application (Hub)

## 1. Purpose and authority

Define the frontend for the BIM RAG project: a lightweight, desktop-oriented, local application that
connects the natural-language query pipeline to an interactive 3D BIM viewer.

This specification is the **hub** of the frontend specification family. It is authoritative for what
is shared across the whole application:

```text
purpose, scope, and product boundaries
technology baseline and development workflow
shared layout and the panel system
application and model lifecycle
shared deterministic backend contracts
state, persistence, and clearing semantics
cross-cutting failure behavior
accessibility, security, and privacy
testing policy and acceptance criteria
```

Feature behavior is owned by four sibling specifications, each authoritative in its own area:

| Spec | Owns |
| --- | --- |
| `spec_v008_3d_viewer.md` | viewer assets and delivery, coordinate model, camera/navigation, selection and picking, highlighting and appearance, rendering/resource policy, floor-plan mode |
| `spec_v009_chat_panel.md` | conversation UI, composer, answer rendering and evidence, citations, selection chips, request lifecycle, chat controls |
| `spec_v010_explanation_panel.md` | explanation presentation contract, opening gate, tables, bar chart, grouped relationship diagram, viewer synchronization, panel lifecycle |
| `spec_v011_component_panel.md` | component detail and highlight-group contracts, panel behavior, isolated preview, Same type / Same family |

Backend query semantics — interpretation, planning, retrieval, execution, classification, and answer
wording — remain governed by:

```text
spec_v002_query_architecture.md
spec_v003_sql_query_path.md
spec_v004_rag_query_path.md
spec_v005_hybrid_query_orchestration.md
```

Frontend specifications reference those semantics; they never restate or reinterpret them. Where an
older frontend example conflicts with this family, this family takes precedence. Every rule has exactly
one owning specification; cross-feature dependencies are expressed as links, not duplicated normative
text.

## 2. Owner intent

This is an interaction and visualization test for the BIM RAG pipeline, not a complete BIM authoring
product. Start small, lightweight, and fast. Validate that a user can:

1. select and load an existing preprocessed BIM model;
2. navigate and select objects in a 3D viewer;
3. ask natural-language questions;
4. receive grounded answers from SQL, graph, RAG, or hybrid retrieval;
5. see primary and relationship-context results highlighted in the model;
6. use selected viewer objects as bounded context for follow-up questions;
7. clear the conversation or reset the complete visible application state.

The LLM layer must remain as small as possible. Model listing, asset delivery, GlobalId resolution,
selection, caching, UI behavior, panel presentation, and resets are deterministic operations and must
not invoke an LLM. **Submitting a question is the only frontend action that may reach an LLM.** The
frontend never connects directly to PostgreSQL or OpenAI.

Visual and component-level details may be decided during implementation with the installed
`frontend-design` workflow, but that design discretion must not expand product scope, change data/API
contracts, add unnecessary panels, or compromise rendering performance.

## 3. Independent application boundary

The repository contains independent applications:

```text
ingestion/   # IFC -> PostgreSQL tables and pgvector documents
backend/     # read-only FastAPI query service
frontend/    # this React/Three.js application
```

The frontend must not import ingestion or backend source code. It consumes versioned HTTP contracts
and immutable viewer assets only.

PostgreSQL remains the source for model metadata, BIM attributes, relationships, canonical identity,
and embeddings. A prepared Fragments file is the browser rendering representation; that artifact is
data, not shared application code.

## 4. Scope

### 4.1 Included

- React + TypeScript frontend application with Vite tooling and npm dependency management
- bright-mode, desktop-first interface
- full-window Three.js / That Open BIM viewer
- floating, resizable, collapsible chat panel
- minimal model selector using display names, with explicit model-load confirmation
- optimized prepared Fragments asset loading and IndexedDB artifact caching
- IFC GlobalId-based viewer/backend identity
- maximum-five viewer selection with chat-context chips
- SQL/RAG/graph/hybrid answer display with primary/context highlighting and background dimming
- clickable entity citations that center and moderately enlarge the target
- compact, collapsed evidence details
- a synchronized query explanation panel for results a structured visualization materially improves
- a bounded read-only component panel with an isolated preview and deterministic group highlighting
- top-down orthographic floor-plan mode inside the existing viewer
- Clear Chat and Reset App controls
- loading, cancellation, error, retry, and degraded-state behavior
- local frontend/backend development integration
- the deterministic narrow backend contracts in §9 and in the feature specifications
- unit/component tests and a bounded browser integration suite

### 4.2 Excluded

- user IFC upload
- IFC parsing during normal frontend startup, and runtime IFC-to-Fragments conversion in FastAPI
- PostGIS geometry ingestion or direct PostGIS-to-Three.js rendering
- mobile-first UI
- authentication or multi-user accounts
- persistent chat history after the browser tab/session ends
- dashboards, catalog cards, or a catalog landing page
- a full object property panel
- storey/class visibility controls, hide/isolate tools
- user-authored clipping planes, measurements, a general storey browser, reflected ceiling plans,
  elevations, or other drawing modes — the fixed automatic horizontal cut, lower boundary, and compact
  floor button stack of floor-plan mode are the only sectioning in scope (`spec_v008` §8)
- annotations, saved viewpoints, exports, or saved visualizations
- model, metadata, or geometry editing
- streamed LLM tokens
- frontend OpenAI access or frontend database access
- charting systems beyond the specific bar chart and relationship diagram of `spec_v010`
- production/cloud deployment

No excluded feature may be added merely because a component library makes it available.

## 5. UX reference

The local Explorentory frontend is a behavioral reference only:

```text
C:\Users\kdgki\Desktop\MSCDP\Projects\Capstone\Explorentory\frontend
```

Retain its interaction principles: visualization is the dominant workspace; conversation is
continuously available; the input stays anchored at the bottom of the chat surface; panels resize
without breaking the visualization; loading and connection failures are visible and actionable; reset
behavior is explicit; visual and conversational selections stay linked.

Do not copy its global plain-JavaScript implementation or real-estate-specific workflow. Use a typed
component/state architecture appropriate for BIM geometry and API contracts.

## 6. Technology baseline

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

Verify current That Open package names, compatibility, worker/WASM setup, and recommended Fragments
APIs against official documentation before implementation. Do not use the deprecated `web-ifc-three`
or `web-ifc-viewer` packages.

Keep dependencies small; record the reason for every material dependency. Do not add a large UI
framework or a charting library unless a concrete need cannot be met cleanly with lightweight
components, CSS, and SVG.

Architecture invariants:

- one typed API client over generated OpenAPI types;
- all imperative scene code behind `src/viewer/ViewerAdapter.ts` — React requests typed viewer actions
  and never touches Three.js objects directly;
- a small serializable store plus a controller for async flows;
- the Fragments worker bundled locally, never from a CDN.

Normal development:

```powershell
cd frontend
npm install
npm run dev
```

The development URL is `http://localhost:5173`. VS Code Go Live is not the source-development
workflow. A static server may serve `dist/` only after `npm run build` if built asset paths and runtime
configuration are verified.

## 7. Shared layout and panel system

### 7.1 Primary layout and theme

The 3D viewer fills the browser viewport. Conversational and explanatory surfaces float above it near
the right edge as separate cards; the page is never divided by a full-height hard separator.

All floating cards share one surface treatment: clear outer margin from viewport edges (20 px),
rounded corners, restrained bright-mode surface with shadow/border separation, and consistent
typography and spacing.

Implement one coherent **bright theme**. Do not add a theme toggle or dark-theme assets. Use readable
contrast, visible focus states, and colors that remain distinguishable over varied model materials.

### 7.2 The panel set

- **Chat panel** — floating card with a resizable width within safe desktop bounds, a collapse/expand
  control, an answer-history region, a bottom-anchored composer, and compact model/reset controls that
  do not dominate the conversation. When collapsed, the viewer expands visually and a small accessible
  control restores the panel. Behavior: `spec_v009`.
- **Right-side stack** — when the explanation panel is open, `.right-stack` becomes a fixed right-side
  column: 12 px gap, explanation above (60%) and chat below (40%), both rendered as separate floating
  cards. No splitter, no resizer, no saved preference, no reordering. Inside the stack the chat drops
  its inline width and drag handle (`.panel-stacked`); the user's stored width preference is preserved
  and applies again when the stack closes. Collapsing the chat inside the stack reuses the existing
  collapsed state — the chat becomes the restore tab and the explanation card takes the freed height
  (`.right-stack-collapsed`). No new layout mode, no overlap, accessibly restorable.
- **Component panel** — a 320 px card docked immediately left of the right-side column with the same
  12 px gap. Behavior: `spec_v011`.
- **Viewer overlay controls** — Reset app at the top-left; the Fit control and the Fine/Standard/Fast
  visualization-quality control together at the bottom-left (`spec_v008` §7.5); and the floor button
  stack under Reset app (`spec_v008` §8). Clear Chat stays inside the chat panel. Reset app, Fit, and
  Clear Chat are never adjacent to one another.

Resizing or collapsing any panel must trigger the viewer/renderer resize path without stretching or
clipping the canvas.

### 7.3 One panel-geometry source

The right-side column is 40vw wide, or 32vw while the component panel is docked beside it.
`explanationColumnWidthPx(viewportWidth, componentOpen)` computes it in px in `App.tsx`, and that
single value feeds both the `--chat-w` CSS variable (read by the column and the component panel's dock
position) and `effectiveViewportObstructionPx`, which the viewer consumes for camera fitting and
visible-region centering (`spec_v008` §4.4).

**There must never be a second set of hard-coded panel measurements.** Any new panel or width rule
extends this single computation.

### 7.4 Minimal information

Do not display branding or a product title beyond a neutral browser title. Show only:

- the active model display name;
- concise model/loading status;
- minimal technical/model information near the bottom-left of the viewer when useful;
- selection count/chips near the composer;
- collapsed evidence summaries beneath answers.

Do not create a permanent metadata inspector or dashboard.

## 8. Application and model lifecycle

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

A model can be proposed through either the deterministic display-name selector or the compact candidate
controls returned by a catalog chat answer (`spec_v009` §4.4).

**Both routes require explicit user confirmation before downloading or loading geometry.** Confirmation
uses the existing backend model-confirmation semantics and the frontend asset endpoint
(`spec_v008` §2.3). Never load a candidate merely because the planner mentioned it.

During loading, display bounded phases such as metadata, download/cache, viewer initialization, and
scene ready. Progress must not imply precision the underlying library cannot provide.

If model loading fails, keep chat available for catalog/general questions and provide one explicit
retry action. Do not loop automatically.

### 8.3 Model switching

The selector remains available after load. Switching requires confirmation, cancels outstanding viewer
and query work, clears model-specific results, selections, and panels, safely disposes the old scene,
and loads the new artifact. Cross-model selected GlobalIds and highlights are never retained.

## 9. Shared deterministic backend contracts

These contracts are read-only, LLM-free, bounded, and field-allowlisted. They never write the database,
parse IFC, or return a server filesystem path. Route naming may follow existing backend conventions,
but behavior and separation are fixed.

### 9.1 Model list

```text
GET /api/models
```

Bounded selector list: `source_model_id`, `display_name` (safe `"Model {id}"` default when null),
`source_fingerprint` (or an opaque asset version), and `viewer_asset_status`
(`ready | missing | stale | unavailable`). Deterministic order by id.

Do not expose local filesystem paths, database credentials, canonical JSON, or ingestion details. The
selector displays only `display_name`; the other fields support identity, caching, and status
internally or appear as minimal bottom-left viewer information.

### 9.2 GlobalId resolution

```text
POST /api/models/{source_model_id}/entities/resolve
```

```json
{ "global_ids": ["IFC-GLOBAL-ID"] }
```

Requirements: maximum five identifiers; trim and stably deduplicate; scope every lookup to the route
`source_model_id`; reject malformed or cross-model identity; return compact mappings only
(`entity_id`, `global_id`, `ifc_class`, `name`) with explicit `unresolved` reporting; never return full
canonical JSON; never invoke an LLM; never write the database.

### 9.3 Query request selection

```text
POST /api/query
```

The frontend supplies selected IFC GlobalIds (`selected_global_ids`, maximum five) scoped by
`active_source_model_id`; it never needs database integer ids. Trusted backend code resolves them to
canonical entity ids before building planner context or selected-object retrieval plans. A selection
with no active model is rejected before any LLM or database work.

GlobalIds are the public browser contract. The deprecated `selected_entity_ids` never overrides a
conflicting GlobalId selection, and the two representations are never accepted together when they
disagree.

### 9.4 Query response fields the whole frontend depends on

`POST /api/query` additively carries:

- `result_summary` — `exact_total`, `viewer_match_count`, `viewer_matches_total`, `truncated`,
  `class_counts` (exact per-IFC-class counts over the full matching set), and `sample_detail`;
- `viewer_actions` — the semantic roles, `primary_global_ids` (the full matching set up to 2,000),
  `viewer_matches_total`, `viewer_matches_truncated`, and `viewer_source_location` (the safe HTTP asset
  reference, never a filesystem path);
- `answer_explanation` — the optional presentation payload owned by `spec_v010`.

**Three independent limits** must never be conflated: the exact total, the 2,000-identity viewer cap,
and the 50-item LLM evidence bound. `primary_entities` remains bounded evidence for grounding and
citations and is **not** the highlight set. `sample_detail` is populated only on explicit sample-detail
intent.

### 9.5 CORS and configuration

Allow only the configured local frontend origin, initially:

```text
http://localhost:5173
```

Never wildcard CORS with credentials. `viewer_asset_root` and `cors_allow_origins` are backend-owned
settings. The frontend reads its base URL from:

```text
VITE_API_BASE_URL=http://localhost:8000
```

No frontend environment variable may contain OpenAI or database credentials.

### 9.6 Generated types

Frontend TypeScript API types are generated from the FastAPI OpenAPI document (`npm run gen:api` into
`frontend/src/types/api.ts`). Generation stays reproducible and checked by tests. Do not hand-maintain
multiple contradictory response interfaces. Regenerating types is the first step of any task consuming
a new or extended contract.

### 9.7 Feature-owned contracts

The remaining narrow contracts are owned by their feature specification and are not restated here:

| Contract | Owner |
| --- | --- |
| `GET /api/models/{id}/viewer-asset` | `spec_v008` §2.3 |
| `GET /api/models/{id}/floors` | `spec_v008` §8.1 |
| `GET /api/models/{id}/entities/{global_id}/details` | `spec_v011` §2.1 |
| `POST /api/models/{id}/entities/highlight-group` | `spec_v011` §2.2 |
| `answer_explanation` payload and topology transport | `spec_v010` §3 |

## 10. State, persistence, and clearing

Use a small typed store with separate conceptual state for:

- tab/session identity;
- active/pending model;
- model and artifact status;
- chat messages and bounded history;
- manual viewer selections;
- current query evidence and viewer roles;
- explanation payload, original highlight identities, and active subgroup;
- component panel selection and detail state;
- viewer mode (3D / plan) and active floor band;
- pending request/cancellation identity;
- panel dimensions and collapse state.

All store state is serializable and current-session only. Persist only appropriate current-tab state to
`sessionStorage`; never place chat history in localStorage. Mutable Three.js / That Open objects, saved
camera poses, and live clipping objects stay inside the imperative viewer layer, not the store. Model
artifacts persist separately in IndexedDB (`spec_v008` §2.4).

### 10.1 Clear Chat

Clear Chat must:

- cancel/retire the current query;
- clear visible messages and the bounded history supplied to the LLM;
- clear current answer evidence and query-result highlights/dimming;
- retire the explanation panel and any component-panel group highlight (both are query-result roles);
- establish a fresh backend/frontend conversation identity;
- keep the active model loaded;
- keep manual viewer selection and selection chips;
- keep the component panel itself, the IndexedDB model cache, and panel layout preferences.

It must not delete or alter database data.

### 10.2 Reset App

Reset App must:

- cancel/retire pending requests and loads;
- clear messages, LLM history, evidence, manual selections, result roles, the explanation panel, and
  the component panel;
- clear the active/pending model and leave floor-plan mode;
- return the viewer's visualization mode to **Standard** (`spec_v008` §7.5) — it is the only control
  that does; Clear Chat and a model switch both keep the user's selection;
- dispose/unload scene geometry, previews, and viewer resources;
- return to the initial model-selection state;
- establish a fresh session identity;
- keep the IndexedDB model cache;
- keep safe UI layout preferences that do not change initial product state.

It must not delete stored models, database data, vectors, or prepared artifacts.

Both controls require clear labels and tooltips. Reset App requires lightweight confirmation when
accidental activation would discard a meaningful conversation.

## 11. Cross-cutting failure behavior

Provide explicit, recoverable states for: backend unavailable; model list unavailable; asset
missing/stale; artifact download failure; IndexedDB unavailable or quota denied; worker/WASM
initialization failure; unsupported or corrupt Fragments artifact; a GlobalId that is not renderable or
resolvable; query timeout or cancellation; LLM unavailable; SQL/RAG degraded modes returned by the
backend; and a stale response after a model or reset change.

Errors must be bounded and actionable. Never expose credentials, local paths, stack traces, prompts, or
provider internals. Never crash the whole UI because one entity cannot be highlighted, one panel cannot
load, or one optional feature is unavailable — a feature whose data is missing degrades truthfully (it
is disabled with a stated reason or omitted), and is never faked.

Feature-specific failure behavior: `spec_v008` §8.8 and §9, `spec_v009` §9, `spec_v011` §8.

## 12. Accessibility and desktop support

Target current desktop Chromium/Edge for the local prototype and maintain sensible behavior at common
laptop resolutions. Phone support is not required.

Require:

- keyboard-operable chat, model, panel, and reset controls;
- visible focus indicators;
- labels/tooltips for icon-only controls;
- sufficient bright-theme contrast, and status conveyed by text in addition to color;
- reduced-motion respect for nonessential transitions;
- an accessible non-canvas representation of selected and result entity names in chat, chips, tables,
  and diagram descriptions.

The 3D canvas itself need not be fully keyboard-navigable in this MVP, but all essential query and
reset behavior must remain available without precise pointer interaction.

## 13. Security and privacy

- No `OPENAI_API_KEY`, `db_url`, database credential, or complete local source path in frontend source,
  build output, storage, logs, errors, or network payloads.
- The frontend calls only the backend HTTP API and the approved viewer-asset route.
- Sanitize Markdown and URLs; treat all API strings and model names as untrusted display data.
- Never construct an asset URL from an arbitrary filesystem path, and do not allow directory traversal
  through model ids or asset routes.
- Do not place full model data or chat history in analytics; no analytics are required.
- No authentication for this local MVP, but keep boundaries compatible with later auth.

## 14. Testing and validation

### 14.1 Unit and component tests

Cover: generated API type use and response validation; model selector and confirmation; chat
submission, Enter/Shift+Enter, cancellation, clarification, error, and manual retry; evidence collapse
and safe Markdown; selection-chip maximum and removal; GlobalId resolution scope and deduplication;
viewer-action role mapping; picking, moderate-fit, and camera-guard behavior through viewer-adapter
tests; edge overlay build/recolor/dispose; projected-size eligibility; floor-band geometry and plan-mode
lifecycle; explanation gate, presentation selection, table/bar/graph rendering, group selection and
**All results**; component detail/group staleness; stale response rejection; Clear Chat versus Reset App
semantics; `sessionStorage` restoration; IndexedDB key invalidation and quota fallback; and absence of
secret/config leakage.

Mock network, viewer, worker, and LLM-backed API behavior. Frontend tests must never call OpenAI or
PostgreSQL directly.

### 14.2 Browser integration tests

Use the small tracked fixture artifact, not the production IFC, for automated browser tests. Cover the
critical path:

```text
start -> list models -> confirm/load -> select object -> ask -> receive answer
-> highlight primary/context -> click citation -> Clear Chat -> Reset App
```

plus deterministic viewer modes that can run against the fixture (floor-plan entry/exit).

Keep full-model performance validation as a separate local manual check so routine tests stay fast and
reliable.

### 14.3 Contract tests

Validate the frontend against backend OpenAPI and representative payloads for: the model list; viewer
asset success/missing/stale; GlobalId resolution; component details and highlight groups; the floors
contract; query answers for SQL, RAG, graph, hybrid, clarify, error, and catalog-candidate routes;
stable `viewer_actions` including empty groups; the additive `answer_explanation` payload; and CORS from
`http://localhost:5173`.

Additive backend fields must be proven additive: a non-qualifying response differs from a qualifying one
only by the new optional field.

### 14.4 Full local acceptance test

```powershell
cd backend
poetry run uvicorn app.main:app --reload
```

```powershell
cd frontend
npm install
npm run dev
```

Prepare the current model artifact once if absent, then verify uncached and cached loading, selection
identity, representative chat queries, highlighting, citations, panel behavior, both clear operations,
resource disposal, and database non-mutation.

### 14.5 Evidence discipline

Report measured results; never invent unsupported performance claims. Headless-browser GL numbers are
software rendering and are valid only as relative before/after evidence — real interaction smoothness is
confirmed on the owner's hardware (`spec_v008` §7.1). A costly live LLM benchmark is not rerun for a
deterministic presentation or viewer change; state plainly when it was skipped.

## 15. Acceptance criteria

The frontend is acceptable only when:

1. React/TypeScript/Vite/npm development and production builds succeed, with typecheck and lint clean.
2. The design conforms to the minimal bright floating-panel intent.
3. Backend and frontend remain independent applications.
4. No frontend code imports backend/ingestion code or contains secrets.
5. The prepared artifact is reproducible, validated, immutable, and identity-compatible.
6. The backend serves artifacts safely without parsing IFC or writing the database.
7. Models load successfully from both network and IndexedDB cache paths.
8. Viewer selection resolves by GlobalId within the active model, maximum five.
9. SQL/RAG/graph/hybrid answers produce correct role-based viewer behavior.
10. Citation clicks center and moderately enlarge objects without excessive zoom.
11. Panels resize, collapse, stack, and close without breaking the viewer or its centering.
12. The explanation panel opens only for results that satisfy its deterministic gate, and its subgroup
    highlighting stays inside the identities the pipeline returned.
13. The component panel degrades truthfully when type/family data is absent.
14. Floor-plan mode derives floors from the single authoritative contract and restores the exact prior
    perspective view.
15. Clear Chat and Reset App follow their distinct required semantics.
16. Normal UI actions other than question submission do not invoke an LLM.
17. Errors are bounded, actionable, and expose no internal secrets or paths.
18. Automated tests pass without live OpenAI or direct database access from frontend tests.
19. Full local integration works with backend `:8000` and frontend `:5173`.
20. No IFC/database/vector/PostGIS mutation occurs during frontend operation or validation.
21. No excluded feature has been added.

## 16. Standing implementation rules

- **Backend contract first.** A frontend feature that depends on a new or extended backend contract must
  not be implemented before that contract exists, is tested, and its types are regenerated. The contract
  work and the frontend work are separate tasks.
- **Additive contracts.** Extend response envelopes with optional fields; a client ignoring them keeps
  working. Never repurpose an existing field's meaning.
- **Deterministic by default.** Any behavior that can be computed from already-returned data must be,
  and structurally so — presentation modules take no database session and import nothing from the query,
  execution, or LLM layers.
- **Truthful degradation.** Missing source data disables a control with a stated reason; it is never
  inferred from names, geometry, proximity, or an LLM.
- **One owner per rule.** New requirements go into the owning specification and are referenced, not
  duplicated, elsewhere.

## 17. Deferred PostGIS direction

PostGIS is valuable for later spatial SQL such as 3D proximity, intersection, bounding boxes, centroids,
and spatial filtering. It is not part of this frontend specification family.

A future PostGIS specification should keep geometry ingestion under the independent ingestion
application and expose only safe read-only spatial operations to the backend. Even then, PostGIS
geometry does not replace the optimized Fragments viewer artifact.

Do not install PostGIS, add geometry tables, extract IFC geometry into PostgreSQL, or add spatial
planner operations under this family.
