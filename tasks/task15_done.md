# Task 15: Query Terminal Output and Viewer Selection Refinements

## Prerequisites

Require:

```text
tasks/task13_done.md
tasks/task14_done.md
```

This is one combined backend/frontend correction task. Preserve all completed behavior except where
this task explicitly changes it.

## Objective

Make four bounded changes:

1. simplify backend terminal output while always showing database queries and per-question OpenAI
   token usage;
2. attempt efficient same-color edges on all model entities;
3. restrict picking to blue query results while query highlighting is active and visually focus
   manually selected results;
4. double the isolated entity-preview height.

Do not change zoom limits or add/move a Fit Building control in this task. The owner withdrew that
request after confirming that a Fit control already exists.

## 1. Backend terminal output

### API status output

Stop printing terminal status records for successful API calls.

Print an API status record only when the final HTTP response status is in this range:

```text
400–599
```

Do not print routine `200`, other successful `2xx`, redirect `3xx`, or `304 Not Modified` endpoint
records. Keep errors concise and do not expose request bodies, chat history, credentials, database
addresses, filesystem paths, or internal exception details.

This requirement applies whether or not `BIM_RAG_TRACE` is enabled. Existing request IDs may remain
for correlation, but do not add more routine API-call output.

### Database query output

Whenever the backend actually submits a SQL-path or RAG/vector-search statement to PostgreSQL,
print the exact parameterized SQL statement in the backend terminal. This is standard operational
output and must not depend on `BIM_RAG_TRACE=1`.

The terminal should clearly identify the path, for example:

```text
[SQL]
SELECT ... FROM ... WHERE ...

[RAG]
SELECT ... FROM rag_documents ... ORDER BY embedding <=> ...
```

Requirements:

- print the actual final SQL sent through the database layer, not a natural-language description;
- retain bind placeholders and never print/interpolate parameter values;
- for RAG, print the actual vector-search SQL statement, never the embedding vector;
- print once per submitted database statement;
- use readable multiline SQL when available without rewriting its meaning;
- do not print SQL that was planned but never submitted;
- do not duplicate the same statement through both normal output and trace output;
- continue to omit database URL, credentials, canonical JSON results, vectors, and full result
  records.

If existing `BIM_RAG_TRACE=1` SQL/RAG records contain useful timing and result summaries, preserve
those optional details without causing duplicate statement output. Successful API status lines must
still remain suppressed.

### OpenAI token usage

After each submitted user query finishes its OpenAI work, print one per-question usage summary:

```text
[OpenAI usage]
prompt_tokens: ...
completion_tokens: ...
total_tokens: ...
```

The values must be the sum of all OpenAI calls made for that one user question, including the
planner and answerer when both run. Use the usage returned by the OpenAI API; do not estimate it.
Print exactly these three aggregate numbers—no cumulative total across questions or backend uptime
and no token-cost estimate.

If a query makes no OpenAI call, do not print a misleading zero-usage block. If only some calls
complete and report usage before a later failure, print only the usage actually reported and keep
the failure handling truthful.

Never print API keys, prompts, complete messages, chat history, or model response bodies with the
usage summary.

## 2. Edges on all model entities

Attempt to add visible edges to every rendered model entity, not only transparent/dimmed entities.

Required appearance:

- approximately 1 px edge thickness;
- edge color follows the entity's current face color, including roof/wall/other base roles and
  primary/context/manual/dim query roles;
- for transparent faces, the edge is less transparent (more opaque) than the face so the entity
  remains legible;
- edges update correctly when highlight roles change and restore correctly when highlights clear;
- keep all edge color, opacity, and thickness values centralized in `viewerTheme.ts` with the other
  viewer materials.

Use a maintained, efficient That Open/Fragments or Three.js rendering mechanism compatible with the
installed versions. Do not create an unbounded React component or render loop per entity.

Before keeping the feature, compare the current full model with edges disabled and enabled. Measure
at least model scene-ready time, highlight-update time, and ordinary orbit/pan/zoom responsiveness.
Keep edges only if they introduce no visible instability and no more than approximately 10% slowdown
in the measured load/highlight operations.

If an efficient implementation is unavailable, requires generating separate edge geometry for
thousands of entities, causes visual artifacts, or exceeds that performance threshold:

1. remove the attempted edge implementation cleanly;
2. preserve the existing face rendering unchanged;
3. report why edges were omitted and the measured result in the completion report.

Do not compromise viewer stability or responsiveness to force this optional feature.

## 3. Picking and focused query-result appearance

The picking rules depend on whether query-result roles are active.

### No active query highlighting

Preserve the current behavior:

- any rendered entity with a GlobalId may be manually selected;
- Ctrl/Shift additive selection and the existing maximum-five limit remain available;
- the existing manual-selection appearance remains unchanged.

### Active query highlighting

When blue primary query results are present:

- only blue primary-result entities may be picked;
- transparent/dimmed non-results may not be selected;
- context/yellow entities may not be selected;
- clicking a nonselectable transparent or context entity does nothing and does not replace the
  current selection;
- a plain click on a blue result focuses that entity and opens/updates the entity panel normally;
- Ctrl/Shift additive selection remains limited to blue primary results and the existing maximum
  five entities;
- clicking empty viewer space clears the focused manual selection and restores the complete blue
  result set to its normal appearance.

After one or more blue results are manually focused:

- focused entities remain opaque blue;
- all other primary query results remain blue but use lower opacity;
- context and dimmed background roles remain unchanged;
- removing the final focused selection restores all primary results to their normal opaque blue;
- do not change focused query results to the normal teal manual-selection color.

Perform eligibility using the already-resolved active query-result identity/local-ID set. Do not
call the backend or an LLM to decide whether a clicked object is selectable. A transparent object
must not briefly enter selection state before being rejected.

Keep the entity panel, selection chips, selected GlobalIds supplied with later chat queries, Clear
Chat behavior, Reset App behavior, model switching, and stale-response guards consistent with the
completed application.

## 4. Entity preview height

Increase the isolated 3D viewport inside the entity/component panel from its current approximately
`160px` height to approximately `320px`—twice the current height.

Requirements:

- enlarge the interactive preview canvas, not the text/property list;
- keep it responsive when the application viewport height is constrained;
- preserve preview centering, guarded fit, orbit/pan/zoom, idle auto-rotation, reduced-motion
  behavior, and resource disposal;
- keep the property list below the preview usable and scrollable;
- do not redesign or broaden the entity panel.

## Tests and validation

### Backend

Add/update tests proving:

- no terminal API status record for `2xx`, `3xx`, or `304` responses;
- one bounded API status record for `4xx` and `5xx` responses;
- SQL and RAG statements print whenever actually submitted, even without `BIM_RAG_TRACE`;
- SQL is parameterized and parameter values/vector contents are absent;
- optional trace mode does not duplicate SQL/RAG statements;
- one per-question OpenAI usage block correctly sums planner and answerer prompt, completion, and
  total tokens;
- no cumulative usage and no usage block for a zero-OpenAI deterministic request;
- normal tests make no live OpenAI call and existing backend tests still pass.

Run the established backend Ruff and non-live pytest commands.

### Frontend

Add/update tests proving:

- edges, if retained, follow every base/highlight role and centralized theme values;
- edge cleanup/restoration and performance fallback are safe;
- without query roles, ordinary selection behavior is unchanged;
- with query roles, only primary blue results are pickable;
- dim/context clicks do not alter selection;
- focused results stay opaque blue while other primary results become translucent blue;
- empty-space/final-selection clearing restores all primary opacity;
- additive selection remains primary-only and capped at five;
- the entity preview is approximately twice its previous height and remains responsive;
- the existing frontend typecheck, lint, unit, build, and E2E suites pass.

Use the current full model for a bounded manual browser validation of edge performance and picking.
Do not submit unnecessary OpenAI questions during testing. Confirm no database tables, vectors,
source models, or prepared model artifacts change.

## Prohibited actions

- Do not change zoom-out behavior or add/move a Fit Building button.
- Do not redesign the frontend or entity panel.
- Do not modify ingestion, database schemas/data, vectors, or model artifacts.
- Do not add PostGIS, raw IFC parsing, upload, or new LLM calls.
- Do not print SQL parameter values, vectors, secrets, prompts, messages, or result records.
- Do not print successful API endpoint status records.
- Do not add cumulative token accounting or cost estimation.
- Do not make dimmed/context geometry selectable while query roles are active.
- Do not retain edge rendering if it materially harms performance or stability.

## Acceptance criteria

1. API status output appears only for HTTP `400–599`.
2. Every submitted SQL/RAG database statement is printed once as exact parameterized SQL.
3. Each OpenAI-backed user question prints prompt, completion, and total tokens once, with no
   cumulative counter.
4. Edges appear on all entities and follow current face roles, or are cleanly omitted with measured
   evidence that the performance requirement was not met.
5. During query highlighting, only primary blue results can be selected.
6. Focused results remain opaque blue and unfocused primary results become translucent blue.
7. Without query highlighting, existing selection behavior is preserved.
8. The isolated entity viewport is approximately twice its previous height.
9. Existing backend/frontend behavior and tests remain valid.
10. Database, vector, ingestion, and prepared-model state remain unchanged.

## Completion report

Rename this file to `tasks/task15_done.md` only when complete. Append:

- backend terminal-output changes and safe example output;
- SQL/RAG statement-printing and no-parameter verification;
- per-question OpenAI token aggregation verification;
- edge implementation approach and measured enabled/disabled comparison, or reason omitted;
- query-active and query-inactive selection results;
- focused/unfocused blue opacity behavior;
- entity-preview height and responsive behavior;
- backend/frontend automated and manual test results;
- database/vector/model-artifact non-mutation confirmation;
- explicit statuses:

```text
API error-only status output: VALIDATED
Submitted SQL/RAG output: VALIDATED
Per-question OpenAI token usage: VALIDATED
All-entity edges: VALIDATED or OMITTED FOR MEASURED PERFORMANCE
Query-result-only picking: VALIDATED
Focused blue result appearance: VALIDATED
Entity preview height: VALIDATED
Backend/frontend regression: VALIDATED
Database/vector/model artifacts: UNCHANGED
```

---

# Completion Report (2026-07-15)

All four bounded changes implemented and validated. No zoom/Fit change, no panel redesign, no
ingestion/database/vector/artifact mutation.

## 1. Backend terminal output

**Changed:** `app/config/trace.py` (restructured), `app/api/app.py` (middleware + uvicorn access
quieting), `app/query/service.py` (per-question usage). Tests: `tests/test_trace_mode.py`
(rewritten, 26 tests), `tests/test_openai_usage_output.py` (new, 9 tests).

### API status output — errors only

The request middleware always establishes the correlation id, but emits a bounded `[API error]`
record ONLY for HTTP 400–599 — trace on or off. Successful 2xx/3xx/304 print nothing; uvicorn's
own per-request access lines are also raised above INFO so a successful call is fully silent.
Unhandled crashes produce one status-500 record and re-raise — no exception internals, bodies,
chat history, credentials, or paths (verified by test with a route that raises an error carrying
a fake path and key).

### Submitted SQL/RAG statements — always printed

The SQLAlchemy `after_cursor_execute` hook now logs every statement the moment it is actually
submitted — once each, in SQLAlchemy's multiline parameterized form, labelled `[SQL]` or `[RAG]`
(the label contextvar is set by the always-active RAG search context). `parameters` is never read,
so values structurally cannot print; the pgvector embedding is a bound parameter and shows as
`%(embedding_1)s`. Planned-but-unsubmitted SQL cannot print because only the cursor hook emits.
Trace summaries (`[trace] sql`/`[trace] rag`) keep timing/counts/histograms but **no longer carry
statements** — the no-duplication rule, verified by a count-occurrences test.

Live capture (uvicorn on :8001, real DB, safe values):

```text
[SQL]
SELECT count(*) AS count_1
FROM ifc_entities
WHERE ifc_entities.source_model_id = %(source_model_id_1)s
  AND ifc_entities.ifc_class IN (%(ifc_class_1_1)s)
[SQL]
SELECT ifc_entities.global_id, ifc_entities.ifc_class
FROM ifc_entities
WHERE ... ORDER BY ifc_entities.id  LIMIT %(param_1)s
[API error]
  request_id: fb2c0e24b260
  method: GET
  route: /api/models/{source_model_id}/entities/{global_id}/details
  status: 404
  elapsed_s: 0.0094
```

Checks over the whole captured session: API records for 200s = **0**; `[API error]` = 1 (the 404);
12 `[SQL]` statements, **0 parameter values** (the question text/`IfcDoor`/session id never
appear); vector/statement duplication = none.

### Per-question OpenAI usage

`_handle_question` snapshots the client call log and, in a `finally`, sums only the calls added for
that question — the usage the OpenAI API itself reported for planner (+ repair) + answerer. Live:

```text
[OpenAI usage]
  prompt_tokens: 6220
  completion_tokens: 2408
  total_tokens: 8628
```

No block for zero-OpenAI requests (reset/confirmation/guards never build a client; details/group
endpoints never reach the service); a failure after a completed planner call prints only what was
reported (calls are logged post-completion). No cumulative counter, no cost estimate — verified by
tests including a two-question sequence asserting the second block is NOT a running total.

## 2. Edges on all entities — KEPT, with measured evidence

**Installed-API survey:** Fragments 3.4.6 `MaterialDefinition` has no stroke/edge property (the
format's `Stroke` enum holds only `DEFAULT`); `OBC.EdgeProjector` makes 2D drawings;
`components-front` (postprocessing outliner) is not installed. Implemented instead with maintained
three.js: **one merged `LineSegments`** (`src/viewer/EdgeOverlay.ts`) built from the already-loaded
model's `getItemsGeometry` → `THREE.EdgesGeometry` per mesh → single position buffer + RGBA
vertex-color attribute + localId→vertex-range index. One object, one draw call — no per-entity
component or render loop. All colors/alphas/threshold/darken factor live in `viewerTheme.ts`
(`EDGES` block). ~1px comes from WebGL's native line width.

Behavior: edge color follows the entity's CURRENT face color (base roof/wall/other and
primary/primaryUnfocused/context/manual/dim roles) darkened ×0.72 for legibility; transparent faces
get MORE opaque edges (dim face 0.16 → edge 0.40; unfocused face 0.45 → edge 0.75). Recolor
rewrites only entities whose role changed and uploads only the dirty span
(`BufferAttribute.addUpdateRange`). Build runs async AFTER scene-ready in yielded slices
(MessageChannel yield — `setTimeout(0)` is clamped to ~1s in background tabs, which measurably
turned the ~1s build into ~30s before the fix). Disposed on unload/switch/reset; a mid-build model
switch abandons cleanly (tested).

**Measured gate (real GPU, headed Chromium, matched runs, forced-GC heap):**

| metric | edges disabled | edges enabled | verdict |
|---|---|---|---|
| load → scene-ready | 1.20 s | 1.12 s (+ async 1.08 s build after ready) | no slowdown |
| highlight update (880-wall focus flip, median) | 12.5 ms | 11.1 ms | within noise |
| orbit responsiveness | 60.5 fps | 60.5 fps | identical (vsync) |
| settled JS heap after highlight | 138.9 MB | 150.9 MB | +12 MB (the ~10 MB buffers) |

Scale: 3,505 items / 5,973 meshes / 258k triangles → **187,411 edge segments**. Well within the
≤~10% criterion on load and highlight; no visible instability or artifacts (verified by
screenshot at model and highlight states). Earlier scary numbers (7.5 fps, 830 ms) were traced to
headless Chromium's software GL renderer plus a then-broken build — documented and excluded.

## 3. Picking and focused appearance

`ViewerAdapter` keeps the resolved primary/context local-id sets. With blue primaries present:
non-primary hits return before ANY selection state changes (no flicker, no replacement, no
backend/LLM call — the adapter has no API client); plain click focuses a blue result and
opens/updates the panel through the existing selection flow; Ctrl/Shift additive stays primary-only
and capped at five; empty-space click clears focus and restores all primaries to opaque blue.
Focused primaries render opaque `#1f6feb`; unfocused primaries the same blue at 0.45 opacity
(`primaryUnfocused` in `viewerTheme.ts`) — never teal; context/dim unchanged. Without query roles,
prior behavior is untouched (teal manual, everything pickable) — locked by tests.

Live screenshot evidence: 880 walls highlighted → click a wall → that wall opaque blue, 879
translucent blue with blue edges, dim/context unchanged, panel opened on it (`buitenblad_(#403467)`,
IfcWall), chip added; type/family truthfully disabled.

## 4. Entity preview height

`PREVIEW.viewportHeightPx = 320` in `viewerTheme.ts`, applied as `height: min(320px, 36vh)` on the
preview canvas — exactly the interactive viewport doubles (160→320), responsive on short viewports,
property list below stays scrollable. Centering, guarded fit, orbit/zoom, idle auto-rotation,
reduced motion, and disposal are untouched (same PreviewScene; the canvas just resizes). Measured
live: preview canvas height **320 px**.

## Automated + manual test results

```text
backend   poetry run pytest -m "not live"   366 passed   (365→366 incl. rewritten trace suite,
                                                          +9 usage tests, +uvicorn-quiet test)
          poetry run ruff check app tests    clean
frontend  npm run typecheck / lint           clean
          npm run test                       138 passed  (117 baseline + 21 new picking/edges/preview)
          npm run build                      ok (11.0 s)
          npm run test:e2e                   2 passed
manual    headed-browser validation: base/highlight/focused screenshots, picking flow,
          panel + 320px preview, edge gate measurements (tables above)
```

One real OpenAI question ("How many doors are there?" → 205) was submitted solely to capture the
live `[SQL]`/`[OpenAI usage]` terminal evidence; all other validation was LLM-free.

## Database / vector / artifact state

```text
ifc_source_models 1 · ifc_entities 6989 · ifc_relationships 3473 · relationship_members 17668
rag_documents 10462 · model_families 1 · source_model_catalog_entries 1
vectors: 10462/10462, dim 1024 — UNCHANGED; prepared artifact untouched (Jul 14 timestamp)
```

## Statuses

```text
API error-only status output: VALIDATED
Submitted SQL/RAG output: VALIDATED
Per-question OpenAI token usage: VALIDATED
All-entity edges: VALIDATED
Query-result-only picking: VALIDATED
Focused blue result appearance: VALIDATED
Entity preview height: VALIDATED
Backend/frontend regression: VALIDATED
Database/vector/model artifacts: UNCHANGED
```
