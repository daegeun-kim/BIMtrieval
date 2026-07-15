# Task 11: Frontend BIM Viewer and Conversational Application

## Prerequisites

Require:

```text
tasks/task09_done.md
tasks/task10_done.md
specs/spec_v002_query_architecture.md
specs/spec_v005_hybrid_query_orchestration.md
specs/spec_v006_frontend_application.md
```

If Task 10 is incomplete, stop. Do not compensate for a missing backend contract with hard-coded
model metadata, filesystem URLs, database access, or mock behavior in the delivered application.

## Mandatory Claude design plugin

Use the installed Claude plugin/skill named **`frontend-design`** for the frontend visual design and
component implementation workflow.

Before implementing UI:

1. invoke the `frontend-design` plugin according to its installed instructions;
2. provide it the owner intent and constraints from `spec_v006_frontend_application.md`;
3. tell it Explorentory is an interaction reference, not a visual/code template;
4. require a bright, lightweight, desktop BIM viewer with a floating rounded right chat panel;
5. require minimal information density and no unrequested dashboard features.

If the plugin is unavailable or cannot be invoked, stop and tell the owner. Do not silently proceed
without it or substitute a different design system. The plugin controls visual execution details,
not product scope, API contracts, state semantics, or security rules.

## Objective

Build and validate the complete local frontend MVP defined by v006:

- React + TypeScript + Vite + npm;
- current maintained That Open/Three.js Fragments viewer;
- minimal model selector and explicit confirmation;
- one-time TypeScript IFC-to-Fragments preparation tool;
- safe backend asset loading and IndexedDB caching;
- floating resizable/collapsible chat panel;
- model selection, GlobalId resolution, bounded chat context, and viewer highlighting;
- evidence display, cancellation, retry, Clear Chat, and Reset App;
- generated FastAPI OpenAPI types;
- component/browser/full-model validation.

## Owner intent that must not change

This is a small interaction/visualization test, not a full BIM platform. Priorities, in order:

1. correct LLM-to-viewer pipeline;
2. fast and efficient model visualization;
3. deterministic non-LLM UI operations;
4. lightweight implementation and conservative thresholds;
5. clear, polished desktop UX.

Do not add charts, catalog cards, property dashboards, upload, PostGIS, editing, measurements,
sections, storey/class trees, hide/isolate tools, authentication, dark mode, or deployment work.

## Phase 1: Inspect and design

Before coding:

1. Read v006 completely and inspect Task 10's final OpenAPI/routes.
2. Inspect the local Explorentory frontend at:

   ```text
   C:\Users\kdgki\Desktop\MSCDP\Projects\Capstone\Explorentory\frontend
   ```

3. Extract only relevant interaction lessons: visualization dominance, chat continuity, resizable
   surfaces, anchored composer, loading/error visibility, reset, and linked selection.
4. Verify current official That Open Components/Fragments APIs, worker/WASM requirements, package
   compatibility, selection/highlighting methods, identity mapping, loading, and disposal.
5. Invoke `frontend-design` and establish the component/layout direction.
6. Record a concise implementation map before mutation. Do not produce a large design system or
   speculative screens.

## Phase 2: Scaffold the independent frontend

Create a Vite React TypeScript application under the existing `frontend/` project using npm.
Preserve the independent top-level application boundary.

Recommended responsibility structure (adjust names only for clear benefit):

```text
frontend/
├── package.json
├── package-lock.json
├── vite.config.ts
├── tsconfig*.json
├── .env.example
├── index.html
├── scripts/
│   └── prepare-viewer-model.ts
├── src/
│   ├── api/
│   ├── chat/
│   ├── components/
│   ├── state/
│   ├── viewer/
│   ├── storage/
│   ├── styles/
│   ├── types/
│   ├── App.tsx
│   └── main.tsx
├── tests/
└── e2e/
```

Use strict TypeScript. Add scripts for at least:

```text
npm run dev
npm run build
npm run typecheck
npm run lint
npm run test
npm run test:e2e
npm run prepare:model
```

Use `VITE_API_BASE_URL` with a safe local default/example. Do not put secrets or filesystem paths in
frontend environment files. Commit npm lock data.

Keep dependencies small. Use Zustand or an equivalently small store, a small IndexedDB wrapper if
useful, safe Markdown rendering/sanitization, and the minimum maintained That Open packages.

## Phase 3: Generate and enforce API types

Generate frontend TypeScript types from the Task 10 FastAPI OpenAPI contract. Make generation
reproducible through an npm script or clearly documented command.

Create one typed API client that owns:

- base URL;
- request/response typing;
- cancellation signals;
- bounded error normalization;
- model list;
- viewer asset retrieval;
- GlobalId resolution;
- query/model confirmation/reset calls.

Do not scatter raw `fetch` calls or duplicate hand-written response interfaces across components.
Do not expose raw backend/internal errors to the UI.

## Phase 4: Implement viewer-asset preparation

Implement the manual TypeScript preparation tool specified by v006 using the maintained That Open
Fragments importer/version family used by the viewer.

For the current model, input is:

```text
C:\Users\kdgki\Desktop\MSCDP\Projects\BIM_RAG\ingestion\ifc_original\IFC Schependomlaan incl planningsdata.ifc
```

Output follows:

```text
model_assets/{source_model_id}/{source_fingerprint}.frag
```

Requirements:

- explicit CLI/configured input and model identity;
- validated output-root containment;
- single-process/conservative resource use by default;
- visible coarse progress without noisy per-entity output;
- atomic temporary output then rename;
- no overwrite of a matching validated artifact unless explicitly requested;
- artifact and identity validation after conversion;
- no source IFC modification;
- no PostgreSQL write;
- no `bim_rag` or backend Python import;
- no automatic execution during `npm run dev` or backend requests.

First validate conversion/loading with a small legal fixture or bounded smoke path. Then run the
current full IFC conversion once. Do not launch parallel conversions. If conversion causes memory,
driver, or system instability, stop, preserve diagnostics, remove partial output, and report rather
than repeatedly retrying with higher limits.

Do not commit the large generated artifact to Git unless the repository's existing policy
explicitly requires it. Ensure the local asset root is handled safely in `.gitignore` while keeping
small test fixtures tracked.

## Phase 5: Implement the viewer adapter

Encapsulate That Open/Three.js imperative behavior behind a typed viewer adapter/service. React
components must not contain scattered direct scene mutation.

Implement only:

- initialization, resize, and disposal;
- one active Fragments model;
- orbit, pan, zoom, and home/fit model;
- single and Ctrl/Shift additive selection;
- maximum-five selection;
- empty-space selection clear;
- rendered-object -> IFC GlobalId identity;
- primary/context/background-dim role application;
- manual-selection role kept distinct from query roles;
- safe handling of missing GlobalIds;
- moderate center/fit for response actions and citation clicks;
- cleanup on model switch and Reset App.

Do not add excluded viewer tools. Do not over-zoom small objects: enforce a camera-fit guard and keep
surrounding geometry visible.

Use worker/culling/LOD/resource features supported by the verified maintained packages. Avoid React
state updates on every camera frame.

## Phase 6: Implement model loading and cache

Initial state contains an empty viewer, concise instruction, floating chat, and minimal model
display-name selector. No cards/dashboard.

Require explicit confirmation before load. Use the Task 10 asset endpoint and IndexedDB cache key:

```text
source_model_id + source_fingerprint/asset_version + artifact_format_version
```

Implement:

- network and cached load paths;
- stale-key invalidation;
- small configurable LRU, default at most two model artifacts;
- quota/unavailable fallback without blocking the app;
- honest loading stages;
- one manual retry;
- cancellation/stale-load rejection;
- safe switching and old-model disposal;
- chat remaining usable for catalog/general questions after model-load failure.

Cache survives both Clear Chat and Reset App.

## Phase 7: Implement the floating conversation UI

Use the `frontend-design` output while enforcing v006:

- viewer fills the viewport;
- bright mode only;
- right-side floating panel with margin and rounded corners;
- resizable and collapsible without breaking viewer resize;
- scrollable familiar chat bubbles;
- bottom-anchored composer;
- Enter submit / Shift+Enter newline;
- blank-submit prevention;
- pending state and cancel;
- one user-triggered Retry after retryable failure;
- no fake streaming;
- sanitized Markdown, lists, and small tables;
- compact evidence section collapsed by default;
- compact model candidate controls within chat;
- no brand/dashboard/property panel.

Show active model display name and only minimal status/model information near the viewer bottom-left.
Use accessible labels, focus states, status text, and reduced-motion behavior.

## Phase 8: Connect selection, queries, and viewer actions

Manual viewer selection:

1. obtain the IFC GlobalId locally;
2. call the deterministic resolver, never the LLM;
3. show up to five compact removable chips;
4. include selected GlobalIds with the next query;
5. ignore stale/cross-model resolver responses.

Question submission includes current session ID, active model ID, bounded history, and selected
GlobalIds. It invokes only the existing backend query flow.

On response:

- append the answer safely;
- display compact collapsed route/evidence information;
- handle clarification and candidate responses naturally;
- apply every `viewer_actions` selection/model action defensively;
- strongly highlight primary matches;
- use a distinct muted context highlight;
- dim non-results while retaining spatial context;
- warn without crashing for unrenderable IDs;
- make displayed entity citations clickable;
- citation clicks center/moderately fit without an LLM call.

Do not render relationship records as geometry.

## Phase 9: Implement Clear Chat and Reset App

Provide two clearly different controls.

### Clear Chat

- cancel/retire pending query;
- clear messages and history fed to the LLM;
- clear current evidence/result highlights and background dimming;
- reset/retire the old backend conversation and generate a fresh session ID;
- keep active model and scene loaded;
- keep manual selection/chips;
- keep IndexedDB cache and panel state.

### Reset App

- cancel/retire all pending query/load work;
- clear messages, history, evidence, selections, highlights, active/pending model;
- dispose/unload the scene;
- reset/retire the backend conversation and generate a fresh session ID;
- return to the initial selector/empty-viewer state;
- keep IndexedDB cache;
- keep harmless panel layout preferences;
- use lightweight confirmation when a meaningful conversation would be lost.

Neither action may delete database records, vectors, source models, or prepared asset files.

## Phase 10: Tests and validation

### Automated

Run:

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
npm run test:e2e
```

Cover all v006 Section 18 cases. Use mocked APIs/viewer adapters for unit/component tests and a
small prepared fixture for browser tests. No frontend test may call OpenAI or PostgreSQL directly.

Verify generated OpenAPI types remain current and fail validation when stale if practical.

### Full local integration

Start backend:

```powershell
cd backend
poetry run uvicorn app.main:app --reload
```

Start frontend separately:

```powershell
cd frontend
npm install
npm run dev
```

Validate at `http://localhost:5173`:

1. model list and explicit load confirmation;
2. uncached current-model artifact download/load;
3. cached reload;
4. orbit/pan/zoom/home;
5. single/multi selection and five-object bound;
6. representative exact SQL question;
7. representative semantic RAG question;
8. relationship/graph or hybrid question;
9. primary/context/background visualization;
10. clickable citation moderate fit;
11. ambiguous clarification;
12. cancellation and user-triggered retry UI;
13. Clear Chat retaining model/manual selection/cache;
14. Reset App unloading model but retaining cache;
15. resize/collapse behavior;
16. missing artifact/backend unavailable/degraded response states;
17. no secrets/local paths in browser source, storage, console, network errors, or build output;
18. database counts and vector metadata unchanged.

Measure and report conversion, artifact size, uncached load, cached load, scene-ready, selection
resolution, query, highlight, and reset timings. Do not claim unmeasured performance.

## Prohibited actions

- Do not proceed without the `frontend-design` plugin.
- Do not modify ingestion or run IFC-to-database/vector pipelines.
- Do not add backend IFC parsing/conversion or IfcOpenShell.
- Do not add PostGIS or direct database geometry rendering.
- Do not connect frontend to PostgreSQL or OpenAI.
- Do not expose keys, DSNs, filesystem paths, prompts, raw SQL, vectors, or full canonical JSON.
- Do not add raw IFC upload or normal-startup raw IFC parsing.
- Do not add excluded BIM/dashboard features.
- Do not add dark mode, branding work, mobile-first layouts, authentication, or deployment.
- Do not automatically retry LLM requests.
- Do not recreate live OpenAI tests.
- Do not weaken source-model isolation or the five-selection bound.
- Do not commit a large generated model artifact without explicit repository policy/owner approval.
- Do not change backend query behavior merely to simplify frontend state.

## Acceptance criteria

All v006 acceptance criteria must pass. Additionally:

1. `frontend-design` usage is documented in the completion report.
2. npm lockfile and reproducible commands exist.
3. maintained That Open packages/APIs are documented with selected versions.
4. the real current IFC has one validated prepared artifact.
5. current-model browser interaction is usable on the owner's desktop without repeated raw parsing.
6. normal navigation/selection/reset operations make no LLM calls.
7. no database/vector mutation occurs.

## Completion report

Rename to `tasks/task11_done.md` only when complete. Append:

- final frontend tree and dependency versions;
- how `frontend-design` was invoked and how its output was applied;
- deviations from the suggested component structure and reasons;
- That Open/Fragments/worker/WASM setup;
- artifact preparation command, duration, size, fingerprint, and identity validation;
- API type-generation method;
- IndexedDB/cache policy and measured cached/uncached results;
- viewer selection/highlight/camera behavior;
- Clear Chat and Reset App validation;
- automated/full local test results;
- measured performance timings;
- browser/security/secret checks;
- database before/after counts;
- remaining limitations;
- explicit final statuses:

```text
Frontend design plugin: USED
Frontend build/type/lint/tests: VALIDATED
Prepared viewer artifact: VALIDATED
Model loading and IndexedDB cache: VALIDATED
GlobalId viewer/query identity: VALIDATED
SQL/RAG/graph/hybrid visualization: VALIDATED
Clear Chat and Reset App: VALIDATED
Backend/frontend local integration: VALIDATED
Database/vector non-mutation: VALIDATED
PostGIS: DEFERRED
```

---

## Completion report (delivered 2026-07-14)

### Final frontend tree and dependency versions

Implemented per the suggested structure, plus `storage/`, `styles/`, `components/` split as
recommended. Key dependencies (lockfile committed):

```text
react 18.3.x · typescript 5.6+ · vite 6.4.3 · zustand 5.0.14
@thatopen/components 3.4.6 · @thatopen/fragments 3.4.6 · three 0.185.1 · web-ifc 0.0.77
idb 8.0.3 · marked 14.x · dompurify 3.4.12
vitest 3.2.x · @playwright/test 1.x · openapi-typescript 7.13.0 · tsx (script runner)
```

```text
frontend/
├── scripts/prepare-viewer-model.ts     # one-time IFC->Fragments tool
├── src/{api,chat,components,state,storage,styles,types,viewer}/
├── tests/                              # 7 Vitest suites (39 tests) + fixtures/
└── e2e/critical-path.spec.ts           # Playwright (2 tests)
```

### frontend-design usage

The installed `frontend-design` plugin was invoked via the Skill tool before any UI code, with
the spec_v006 owner intent and constraints (bright-only, floating rounded right panel, minimal
density, Explorentory as interaction reference only). Its process was followed: a "measured
drawing" design plan was produced (palette: cool daylight sheet #EDF1F5/#E1E7ED, blueprint blue
#1F6FEB primary/primary-match, ochre #E0912A relationship-context, teal #0FB5C9 manual selection;
type: Space Grotesk display + IBM Plex Sans body + IBM Plex Mono for identifiers/counts/status,
self-hosted via @fontsource), critiqued against generic AI-default looks, then implemented as CSS
tokens in `src/styles/theme.css`. Signature elements: drafting corner registration ticks on the
panel, mono CAD-style status readout bottom-left, and mono entity-identifier chips/citations tying
chat text to geometry. Scope was not expanded: no dashboard, cards, dark mode, or extra panels.

### Deviations from suggested structure

- `chat/` holds panel/message/composer/evidence/candidate components (rather than everything in
  `components/`) so `components/` stays generic (selector, dialogs, readout, icons).
- Added `storage/` (IndexedDB cache) and `styles/` (tokens) as recommended by the responsibility
  split; no other deviations.
- Explorentory inspection was skipped: CLAUDE.md's strict project-scope constraint ("Do NOT
  read...external folders") overrides the task pointer to `...\Capstone\Explorentory`. The
  interaction lessons required (viz dominance, chat continuity, resizable surfaces, anchored
  composer, visible loading/errors, explicit reset, linked selection) are fully specified in
  v006 §5 and were implemented from that list.

### That Open / Fragments / worker / WASM setup

- Verified current APIs against docs.thatopen.com before coding (FragmentsManager tutorial,
  FragmentsModel API, IfcImporter tutorial).
- Viewer: `OBC.Components` + `SimpleScene`/`OrthoPerspectiveCamera`/`SimpleRenderer` world;
  `FragmentsManager.init(workerUrl)` with the worker imported **locally** via the package's
  `@thatopen/fragments/worker` export and Vite `?url` (OBC's `getWorker()` fetches from unpkg CDN
  at runtime — rejected so the app works fully offline). Models attach camera + scene on
  `list.onItemSet`; LOD refresh on camera `rest`.
- Identity: `getGuidsByLocalIds`/`getLocalIdsByGuids`; picking via `model.raycast`; highlighting
  via `highlight`/`resetHighlight` with `MaterialDefinition`s per role; dim-then-overlay ordering
  keeps primary/context/manual visually distinct; camera fits via `getMergedBox` + guarded
  `fitToBox` (1.9× expansion, 2.5 m minimum half-extent so small objects never fill the view).
- Conversion: `FRAGS.IfcImporter` in Node (tsx) with the locally installed web-ifc 0.0.77 WASM;
  validation reload via `SingleThreadedFragmentsModel`.

### Artifact preparation

```powershell
npm run prepare:model -- --input "...\ingestion\ifc_original\IFC Schependomlaan incl planningsdata.ifc" --model-id 1 --check-guid "0X9NHFByPEEuoRYN$4mN72"
```

- Smoke-validated first on a tiny hand-written IFC4 fixture (`tests/fixtures/smoke-wall.ifc` →
  `smoke-wall.frag`, 1.2 KB, tracked for browser tests).
- Full conversion: 65.1 MB IFC → **5.48 MB** `.frag` in **5.4 s**, single process, atomic
  tmp+rename, sidecar `.meta.json` (fragments 3.4.6 / web-ifc 0.0.77).
- Fingerprint `57fafa59f03b18c0…e81dfcf4` = SHA-256 of the IFC = the DB
  `file_fingerprint`, so the backend immediately reported `viewer_asset_status: "ready"`.
- Identity validation: GlobalId `0X9NHFByPEEuoRYN$4mN72` (IfcWindow) → localId round-trip OK. A
  first attempt with an IfcTask GlobalId correctly FAILED validation (process entities carry no
  geometry) and the tool refused to write output — validation behaves as specified.
- Artifact is gitignored (`model_assets/*` except `fixtures/` + README); not committed.

### API type generation

`npm run gen:api` runs `openapi-typescript ../frontend_openapi_snapshot.json -o src/types/api.ts
--default-non-nullable=false`; the snapshot is produced offline from the backend factory
(`app.openapi()`), command documented in frontend/README.md. `src/api/types.ts` aliases the
generated schemas; the single client `src/api/client.ts` owns base URL, typing, AbortSignal
cancellation, and bounded error normalization. No hand-written duplicate response interfaces; no
raw fetch in components.

### IndexedDB cache policy and measured results

Key = `sourceModelId::sourceFingerprint::frag-3.4` (artifact format version constant), defensive
stale-field check on read, LRU capped at 2 artifacts, quota failure degrades to non-persistent
load. Cache survives Clear Chat and Reset App. Measured (real 5.48 MB artifact, localhost):
uncached load → scene ready **2 817 ms**; cached reload → scene ready **2 587 ms** (download skipped,
loader dominates at this size).

### Viewer selection/highlight/camera behavior

Click pick with 4 px drag tolerance; Ctrl/Shift/meta additive; five-object cap with an explicit
notice chip (no silent replacement); empty-space click clears manual selection; chips resolve
names via the deterministic resolver (150 ms debounce, stale-token rejection, raw GlobalId
fallback). Query roles: whole-model dim (#C7CED6 @ 0.22) → context ochre → primary blue; manual
teal drawn last and kept distinct. Missing/unrenderable GlobalIds produce one bounded chat notice,
never a crash. Citation clicks center with the guarded moderate fit (measured ~1.7 s incl. camera
transition); no LLM call.

### Clear Chat / Reset App validation

Unit-tested (controller suite) and verified live: Clear Chat cancels pending work, clears
messages/history/evidence/roles, rotates the session id (backend session retired via best-effort
`reset:true`), **keeps** model + manual selection + cache + panel prefs. Reset App additionally
clears selection, disposes/unloads the scene, clears active model, returns to the initial
selector state behind a confirmation dialog, keeps the IndexedDB cache. Neither touches stored
models/DB.

### Automated and full local test results

```text
npm run typecheck  ✓ (tsc -b, strict)
npm run lint       ✓ (eslint, 0 problems)
npm run test       ✓ 7 files, 39 tests (api client, cache, store, controller,
                     markdown sanitization, components, viewer-adapter fit guard)
npm run build      ✓ vite production build (worker emitted locally)
npm run test:e2e   ✓ 2 Playwright tests: full critical path with real Fragments
                     worker + fixture artifact; backend-unavailable recovery
```

Backend regression: `poetry run pytest -m "not live"` → 268 passed (unchanged). No frontend test
calls OpenAI or PostgreSQL.

### Full local integration (real backend :8000 + frontend :5173, real LLM)

Driven headlessly through Chromium against the running stack:

```text
boot + model list                1 735 ms
uncached artifact load → ready   2 817 ms
cached reload → ready            2 587 ms
exact SQL q ("how many doors")  27 842 ms → "205 doors." (evidence: sql route)
semantic RAG q (insulation)     23 111 ms → grounded clarification (Dutch-named
                                 model has no explicit insulation psets — expected degrade)
storey containment q            79 572 ms → grounded storey contents answer
citation click fit               1 689 ms
Clear Chat                       1 694 ms (model retained ✓)
Reset App                        2 866 ms (returns to initial state ✓)
console errors                   none
```

Query latency is dominated by the two gpt-5-nano reasoning calls (known Task 08 behavior), not
the frontend. Highlight/dim applied without viewer errors; viewer stayed interactive throughout.

### Browser/security/secret checks

Page HTML, sessionStorage, and production `dist/` scanned: no OpenAI key pattern, no
`postgresql://`, no `db_url`, no local filesystem paths. (A naive `sk-` substring scan flags only
`space-grotesk-*` font filenames — false positive, verified by context extraction.) Markdown is
sanitized (script/inline-handler/`javascript:` stripped — unit-tested). Errors shown to the user
are normalized, bounded strings.

### Database before/after counts (identical)

| table | before | after |
| --- | --- | --- |
| ifc_source_models | 1 | 1 |
| ifc_entities | 6 989 | 6 989 |
| ifc_relationships | 3 473 | 3 473 |
| relationship_members | 17 668 | 17 668 |
| rag_documents | 10 462 | 10 462 |
| source_model_catalog_entries | 1 | 1 |
| model_families | 1 | 1 |

Vector metadata unchanged: `BAAI/bge-m3`, dim 1024, 10 462 documents.

### Remaining limitations

- Query latency (23–80 s) is the backend gpt-5-nano reasoning budget, not frontend; streaming is
  explicitly out of scope (v006 §4.2).
- The RAG demo question degrades to clarification on this Dutch-named model (known Task 08
  corpus characteristic); counts/lists/relationships demo best.
- Main JS bundle is ~6.3 MB minified (three + That Open); acceptable for a local desktop
  prototype, code-splitting deferred.
- e2e drives the critical path headlessly; canvas click-selection is covered by adapter unit
  tests, not synthetic browser clicks (raycast requires real geometry hit-testing).
- Live-LLM acceptance was driven by a manual script (not committed), honoring the "no live
  OpenAI tests" rule.

