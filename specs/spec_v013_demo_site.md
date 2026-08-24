# spec_v013 — Public static demo site

## Purpose

`spec_v001`–`spec_v011` specify the product; `spec_v012` specifies its delivery.
This specification covers the one thing neither provides: **a link a stranger can
click**.

BIMtrieval currently runs only for someone who clones the repository, stands up
PostgreSQL, imports an IFC model, and supplies their own `OPENAI_API_KEY`. That
is the correct posture for the application and `spec_v012` §7 defends it. It is
also a wall between the project and every reviewer, recruiter, or collaborator
who will not do those four things to look at a portfolio project.

This specification adds a **separate static demo site** that shows the real
interface — real 3D model, real answers, real citations — driven entirely by
frozen fixtures. It runs no backend, holds no database, and calls no LLM.

**The existing three applications are not modified.** `frontend/src/` is read and
imported, never edited. The demo is additive and can be deleted without trace.

## Shared constraints

- No file under `frontend/src/`, `backend/`, or `ingestion/` is modified by this
  specification. The demo composes the existing frontend; it does not fork it.
- No `OPENAI_API_KEY` is used at build time, at deploy time, or at run time. No
  key reaches the browser, the repository, or GitHub Actions.
- `.env` is never read, printed, copied, or inspected. Fixture capture runs
  against an already-running local stack the owner started.
- The demo's default build never enters the existing `frontend/` offline gate.
  `npm test`, `npm run typecheck`, `npm run lint`, and `npm run build` keep their
  current meaning.
- GitHub-side actions (enabling Pages, DNS, repository settings) remain manual
  owner steps, documented here and never performed by an assistant.
- The demo dataset is redistributable under a license that is checked and cited.

---

## 1. What the demo is, and is not

### 1.1 What it is

A single-page static site, served from GitHub Pages, that boots directly into the
BIMtrieval interface with the Schependomlaan model already loaded. The visitor
gets:

- the **real 3D viewer** — the same `ViewerAdapter`, the same That Open engine,
  the same 5.5 MB Fragments artifact the local application loads. Orbit, zoom,
  select, floor-plan mode, and component details all work as they really work.
- **three canned questions**, chosen from a list rather than typed.
- for each, the **real recorded response** — the answer text, the route badge,
  the citations, the entity highlights in 3D, and the explanation panel — exactly
  as the live system produced it.

Nothing on screen is a mockup. Every pixel is the shipping frontend.

### 1.2 What it is not

Stated plainly on the site itself, not buried:

- **Not a live system.** Three questions, frozen in advance. The free-text
  composer is replaced by a picker; there is no way to ask a fourth question.
- **Not a hosted instance.** No database, no backend, no API key, no per-visitor
  cost.
- **Not evidence of latency.** The recorded answers appear in milliseconds. The
  captured runs took 5.9–22.3 s. The demo must not imply otherwise, and §6.4
  requires it to state the recorded latency.

`spec_v012` §7's reasoning is preserved and unweakened: a public *live* endpoint
would spend the author's tokens on every visitor, and asking visitors to paste
their own key into a web page teaches a habit nobody should have. This demo does
neither. It is not a reversal of that decision — it is the option that decision
left open.

---

## 2. Hosting and URL

| | Decision |
| --- | --- |
| Host | GitHub Pages, from the `daegeun-kim/BIMtrieval` repository |
| Source | GitHub Actions (`actions/deploy-pages`), not a `gh-pages` branch |
| URL | `https://daegeun-kim.github.io/BIMtrieval/` |
| Vite `base` | `/BIMtrieval/` |

### 2.1 Why this URL and not `daegeunkim.com/bimtrieval/`

GitHub Pages propagates a custom domain to other repositories **only when the
domain is configured on a user site** (`<user>.github.io`). `daegeun-kim.github.io`
returns 404 — there is no user-site repository. The portfolio's `daegeunkim.com`
is attached to a *project* repository, so it does not propagate, and the demo
cannot be served at a path beneath it.

The portfolio links out to the Pages URL from its existing BIMtrieval project
page. One outbound link; no DNS work.

### 2.2 The subdomain option, deliberately deferred

`bimtrieval.daegeunkim.com` remains available later at the cost of one GoDaddy
CNAME to `daegeun-kim.github.io` plus a custom domain on this repository. It is
not taken now. To keep that door open at a one-line cost, the Vite `base` is read
from an environment variable (§9.2) rather than hardcoded — moving to a subdomain
later means changing `base` to `/`, nothing more.

### 2.3 Prerequisites the owner must verify

- The `BIMtrieval` repository is **public** (GitHub Pages on the free tier
  requires it).
- Pages source is set to **GitHub Actions**.

Both are manual owner steps (§10).

---

## 3. Directory layout

The demo is a sibling of `src/` inside `frontend/`, so it shares `node_modules`,
`tsconfig`, and the dependency set. A top-level `demo/` would need its own copy
of the entire React/Three/That Open toolchain to import across into
`frontend/src/`; this placement needs none.

```
frontend/
  src/                          UNTOUCHED — read and imported only
  demo-site/
    index.html                  demo entry document
    vite.config.ts              own config; sets base + the two aliases
    tsconfig.json               own project; adds resolveJsonModule
    playwright.config.ts        browser suite config (§11.2)
    README.md                   how to run and re-capture
    src/
      main.tsx                  demo entry point
      DemoApp.tsx               wraps the real App, auto-loads the model
      fixtureClient.ts          stands in for src/api/client.ts
      DemoComposer.tsx          stands in for src/chat/Composer.tsx
      fixtures.ts               fixture loading + lookup
      demoCamera.ts             opening camera pose (§6.5)
      DemoBanner.tsx            the "this is a demo" disclosure (§6.4)
      demo.css                  styles for the picker and banner only
    scripts/
      capture.ts                owner-run fixture recorder (§7.2)
      probe.ts                  scratch tool for choosing questions (§5)
    e2e/
      demo.spec.ts              browser suite (§11.2)
    public/
      model.frag                5.5 MB Schependomlaan artifact
      ATTRIBUTION.txt           CC BY 4.0 notice (§8.2)
    fixtures/                   frozen JSON (§7)
```

`frontend/dist-demo/` is the build output, and is ignored.

`frontend/demo-site/public/model.frag` sits outside `model_assets/`, so the
existing `.gitignore` rule (`model_assets/*`) is untouched and no ignore
exception is needed. The 5.5 MB binary is committed deliberately — it is the
demo's payload, not experiment output, and §8 records why it is redistributable.

---

## 4. Substitution mechanism

The core design. The demo replaces exactly **two modules** by Vite alias, and
changes nothing else.

### 4.1 Why two aliases suffice

| Module | Imported by | Import sites |
| --- | --- | --- |
| `src/api/client.ts` | `src/state/controller.ts:6` | **1** |
| `src/chat/Composer.tsx` | `src/chat/ChatPanel.tsx:13` | **1** |

`api` is a singleton exported once and consumed once. Every network call the
frontend makes — model list, floors, query, entity details, highlight groups,
viewer asset — passes through `ApiClient`'s eight public methods. Replacing that
one module replaces the entire backend.

`Composer` is a zero-prop default export. Replacing that one module replaces the
entire input surface.

Everything else — the viewer, the chat transcript, the explanation panel, the
component panel, the store, the controller, the floor controls — runs unmodified
and unaware.

### 4.2 The alias

In `frontend/demo-site/vite.config.ts`:

```ts
resolve: {
  alias: [
    { find: /^.*\/api\/client$/,   replacement: "<demo>/src/fixtureClient.ts" },
    { find: /^.*\/chat\/Composer$/, replacement: "<demo>/src/DemoComposer.tsx" },
  ],
}
```

Resolved to absolute paths. The patterns match the relative specifiers used
inside `frontend/src/` (`../api/client`, `./Composer`).

### 4.3 `fixtureClient.ts` — the contract

Exports the same surface as `src/api/client.ts` so the alias is type-compatible:
`ApiClient`, `api`, `ViewerAssetResult`, `QueryRenderTiming`. It re-exports the
error and response types from `src/api/types.ts` rather than redefining them, so
a backend type change breaks the demo's typecheck instead of silently drifting.

Method behaviour:

| Method | Demo behaviour |
| --- | --- |
| `listModels` | returns `fixtures/models.json` |
| `modelFloors` | returns `fixtures/floors.json` |
| `query` | dispatches on the request (§4.4) |
| `fetchViewerAsset` | fetches `public/model.frag`, returns bytes + a fixed ETag |
| `entityDetails` | looks up the captured set; falls back per §7.3 |
| `highlightGroup` | looks up the captured set; falls back per §7.3 |
| `resolveEntities` | returns `fixtures/resolve.json` entries |
| `reportQueryRenderTiming` | no-op |
| `viewerAssetUrl` | the static asset path |

Each method resolves asynchronously with a small artificial delay (≈120 ms) so
the interface exercises its real pending states — spinners, disabled controls,
cancel affordances — rather than snapping to a finished frame. This is a
presentation detail, not a simulation of real latency; §6.4 carries the honest
number.

### 4.4 `query` dispatch

`ApiClient.query` serves three distinct purposes in the real application, and the
fixture client dispatches on the request shape:

1. `confirm_model_id` present → the model-load handshake issued by
   `controller.confirmAndLoadModel` ([controller.ts:121](../frontend/src/state/controller.ts)).
   Returns `fixtures/load-model.json`.
2. `question` matching a canned question id → returns that question's frozen
   envelope.
3. anything else → returns a refusal envelope stating the demo answers only the
   three listed questions. This path should be unreachable through the UI (the
   composer is a picker), and exists so an unexpected code path degrades
   honestly instead of throwing.

### 4.5 `DemoComposer.tsx`

Replaces the free-text textarea with three buttons, one per question. Before it
is asked, a button shows **only the question text**.

- Renders `SelectionChips` from `src/chat/` unchanged, so the selection UI is the
  real one.
- Disables all buttons while `pending` is true.
- On click: applies the question's recorded pre-selection if it has one (§5.3),
  then calls `controller.submitQuestion(<question text>)` — the identical entry
  point the real composer uses ([Composer.tsx:22](../frontend/src/chat/Composer.tsx)).
- **After** the answer is asked, the card reveals what the router did: `routed
  to <route>`, the recorded cost, and one line on what that path means.

The route is withheld until submission on purpose (§5.1).

### 4.6 `DemoApp.tsx` — skipping model confirmation

The real application boots to the model catalog and requires an explicit
"load this model" confirmation. The demo skips it: a visitor should see the
building immediately.

`DemoApp` renders the real `App` unmodified and runs one effect that subscribes
to the store; when `models` is populated and `activeModel` is still null, it
calls `controller.confirmAndLoadModel(models[0])` — the same public method the
confirm dialog calls. The confirmation is performed, not bypassed; only the click
is automated.

No `src/` file changes, because the demo supplies its own entry point
(`demo-site/src/main.tsx`) rather than reusing `src/main.tsx`.

---

## 5. The three questions

Chosen by **measuring the current pipeline**, not by reading the published
benchmark. That file records an earlier architecture (§5.4), and every question
taken from it behaved differently or worse when actually asked.

| id | Question | Operation | Basis | Panel |
| --- | --- | --- | --- | --- |
| `count-01` | *How many doors are in this model?* | `count` | `exact_sql` | `result_table` |
| `group-01` | *Break down the elements by IFC class.* | `group_distribution` | `exact_sql` | **`bar_chart`** |
| `describe-01` | *Describe the walls in this model.* | qualitative | **`hybrid_evidence`** | none |

Three different bound operations, two retrieval bases, and two panel types — one
of which is a chart rather than a table.

### 5.1 Why these three, and why the route is hidden until asked

They demonstrate that the router is not decoration. A visitor asks three
plain-English questions and watches the system take three genuinely different
paths — deterministic SQL, graph traversal over containment relationships, and
semantic vector retrieval — each producing a different kind of evidence and a
different 3D highlight. That is the project's central claim, shown rather than
asserted.

Which is exactly why the buttons do **not** carry route labels before they are
pressed. A card reading "SQL — list five walls" presents the route as a property
of the question, something the demo's author sorted in advance; the visitor
learns a taxonomy and never sees a decision happen. Revealing `routed to sql`
*after* submission presents it as an outcome — the thing the system worked out
from plain English, which is the part worth showing. Same three facts, opposite
lesson.

### 5.2 What was tried and dropped

Every one of these was asked against the running backend before being discarded:

| Question | Why it is not in the demo |
| --- | --- |
| *List five walls with their names.* | Answers "I can't list five because the other four are not provided here" — the evidence packet carries one example, not five |
| *What elements are contained in this storey?* | Wildly unstable: "3,505 elements" on one run, "this storey contains 1 element" on another, "contains none" on a third. The last two are **wrong**. Independently disqualified: the Schependomlaan file carries faulty storey labelling, which this project does not attempt to correct, so a floor-scoped question is asking the system to be right about data that is not |
| *Show elements related to exterior facade walls…* | Returns a clarification: "exterior facade" is not a queryable attribute |
| *Break down the entity count by storey.* | Returns a clarification; the model reports one storey, so it could only ever be a single bar; and the same floor-labelling fault applies |
| *In general, what is IFC…* | Binds "IFC" to `IfcProject` and answers "a total of 1" instead of explaining IFC |
| *Among the doors, which relate to fire separation?* | Zero results — the semantic modifier is dropped and the SQL scope is empty |
| *List the aggregation relationships.* | Clarifies: the relationship candidate is "not in this request's slate" |

The pattern is consistent and worth stating plainly: **aggregate, count, and
distribution questions are reliable; questions that need specific identities
listed back are not**, because the answer packet is bounded and does not carry
them.

### 5.3 Why no `rag` question, and what replaces it

There is no independent semantic route to demonstrate, because the pipeline no
longer has one. RAG is subordinate by design: `_execute_qualitative`
([execute.py:474](../backend/app/query/binding/execute.py)) runs semantic
ranking **strictly inside an already-resolved SQL scope**, and only for the
`description` and `comparison` operations —
[validate.py:475](../backend/app/query/binding/validate.py) rejects
`semantic_ranking_text` on anything else.

`describe-01` is the demo's semantic example: it reaches `hybrid_evidence`, which
is the basis emitted when RAG candidates contributed. That is genuinely the
semantic path firing — just not as a route of its own.

### 5.4 The published benchmark records an earlier pipeline

`evaluation/results/benchmark_v003.json` reports a route breakdown — `sql` 18/19,
`rag` 3/3, `graph` 1/1 — that the current backend **cannot produce**:

- `QueryRoute.RAG` and `QueryRoute.GRAPH` appear nowhere in `backend/app/`. Every
  active-model question returns `route: hybrid`, hardcoded at
  [service.py:363](../backend/app/query/service.py).
- `AnswerBasis.SEMANTIC_RETRIEVAL` is defined and never emitted.
- The service docstring says so directly: *"There is no route-classification
  call."* Retrieval mode is derived from the bound operation
  ([llm/schemas.py:87](../backend/app/llm/schemas.py) §5.1).

This is a deliberate redesign (task24), not a regression — but the benchmark and
the README were not updated to match, and the harness that produced them
(`run_benchmark_v003.py`) was deleted in `236c90d`. **This is a documentation
problem for the repository, not for the demo**, and it is recorded here because
this specification is where it was discovered. It is the owner's to resolve; §12
carries it.

The demo takes the honest path available to it: it labels each answer with the
`answer_basis` its recording actually reports, and never prints `route`.

### 5.5 Pre-selection is supported but currently unused

The mechanism for replaying a question that was asked with something selected in
the viewer is built and kept: a question may carry a `preSelection`, which the
picker applies through the store's own public actions (`setManualGuids`,
`setResolvedChips`) before submitting, so the selection chip appears exactly as
it would after a real click and nothing under `src/` is touched.

None of the three current questions needs it — the storey question that did was
dropped in §5.2. The capture script still resolves the model's storey from the
floors endpoint rather than hardcoding an entity id, so the path stays exercised
and correct if a selection-dependent question returns.

---

## 6. Site behaviour

### 6.1 Boot sequence

1. The page arrives and paints a **spinner immediately**, from inline CSS in
   `index.html`, before any JavaScript has run.
2. Static assets load; the real `App` mounts. React clears `#root`, which removes
   that first spinner with no teardown code.
3. The curtain (§6.5) covers the canvas and carries its own spinner, so the
   indicator is continuous across the handover.
4. `controller.bootstrap()` runs; the fixture client returns the one-model
   catalog. Quality is set to Fast (§6.6).
5. `DemoApp`'s effect auto-confirms; the 5.5 MB artifact loads; the application's
   own phase card (Metadata → Download → Scene → Ready) takes over the
   storytelling.
6. Once `loadPhase` reaches `ready`, `demoCamera.frameForDemo()` poses the
   opening frame and the curtain lifts, taking its spinner with it.
7. The disclosure card and the three question buttons are live.

The two spinners exist because the engine bundle is several megabytes: there is a
real window between "the page arrived" and "React mounted", and another before
the model list returns, during which the screen would otherwise be a flat,
unexplained grey. A motionless grey field reads as a page that has failed, not
one that is working — and for a demo whose entire job is a first impression, that
is the most expensive possible misunderstanding.

`demo.spec.ts` asserts the spinner is visible on arrival and gone once the
curtain lifts, so the demo can neither start blank nor spin forever.

### 6.2 What a visitor can do

Everything the real frontend allows, except type a question: orbit and zoom,
click elements to open the component panel, switch to floor-plan mode, ask the
three questions in any order, open the explanation panel, clear the chat.

### 6.3 What degrades

Clicking an element outside the captured detail set (§7.3), and any code path
reaching `query` with an unrecognised question (§4.4). Both produce an explicit,
honest "not captured in this demo" message. Neither fabricates.

### 6.4 Disclosure

A persistent, non-dismissable card states in one line that this is a static demo
with three pre-recorded answers and no live backend, and links to the repository.

It docks **directly above the application's status readout and matches its
width**, so the two read as one stack in the bottom-left corner rather than as a
demo element competing with the real UI. That geometry is measured from
`.readout` at runtime: the readout sizes to its content under a `44vw` cap, and
this card is a sibling of `.app` and cannot read the layout variables inside it,
so no fixed number would be right. `demo.spec.ts` asserts the alignment. Each asked question additionally reveals its **recorded latency** from the
capture run alongside the retrieval basis, so the instant response never reads as
a performance claim. Measured on the captured runs: 5.9 s, 22.3 s and 7.3 s.

Token counts are not shown. The response envelope does not carry them, and
copying figures from the published benchmark would attach one run's cost to a
different run's answer.

### 6.5 Opening camera

The application's `fitAll()` frames the model from whatever direction the camera
already faces and grows the target box by `VIEWER_CAMERA.fitExpand` (1.9) so
surroundings stay visible. Both are right for a working tool, where the user
arrives with a task. They are wrong for the demo's first frame, which lands
side-on and distant — a building rendered as an elevation drawing.

`demoCamera.frameForDemo()` therefore poses the camera once, after `fitAll()` has
run, to a three-quarter aerial view — **keeping the distance the application
itself computed** and multiplying it by `0.85`. It runs exactly once and never
again: every later camera move belongs to the visitor.

Deriving the distance independently from the model's bounding box was the first
attempt, and it framed a corner of the roof. The application's fit already
accounts for the viewport obstruction from the chat panel, the lens, and the
model bounds; reconstructing that from the box discards all three. Re-aiming a
good distance is a smaller and more reliable change than recomputing one.

This is a demo-only presentation choice, so it does not touch
`viewerCustomization.ts` — the real application's framing is unchanged. Reaching
the camera controls needs a cast past `ViewerAdapter`'s private fields; the
alternative was a demo-only parameter on the adapter, i.e. editing `src/` for a
cosmetic reason. The reach is guarded and returns `false` if the internals move,
in which case the application's own framing stands and the demo is merely less
handsome.

---

### 6.6 Visualization quality opens on Fast

The application defaults to **Standard** quality, which is right for someone who
chose to run it on their own machine. The demo has no idea what it has landed on
— a phone, an old laptop, a locked-down work machine — so it opens on **Fast**
and lets the visitor turn it up.

`controller.setVisualizationMode("fast")` is called before the model load, not
after, so the geometry arrives at the intended quality instead of being rebuilt a
moment later. Only the starting point changes: the Fine / Standard / Fast control
is the application's own `VisualizationModeControl`, still in the bottom-left
readout and fully operable.

`demo.spec.ts` asserts both halves — that Fast is selected on arrival, and that
another mode can still be clicked. The second half is not ceremony: the
disclosure card originally sat on top of that control, so the choice existed but
could not be made (§14.8).

---

### 6.7 Mobile layout

The application is desktop-first by design — floating panels docked right, a
status readout bottom-left, a viewer filling everything behind them. On a phone
that has nowhere to go, because nothing fits beside anything.

The demo restacks it along the usual convention for a viewer-plus-conversation
app on a small screen: **the thing you are looking at on top, the thing you are
reading and typing into below it.** Viewer in the upper two thirds, panels
as a full-width sheet under it.

All of it is CSS in `demo.css`, inside a single `max-width: 768px` media query.
Above that width not one declaration applies, so the desktop rendering is
exactly the application's own. Two details are worth recording:

- **The viewer is genuinely resized, not merely covered.** The canvas is what
  the renderer measures for its aspect ratio, so a canvas extending behind the
  sheet would frame the model for a viewport the visitor cannot see.
- **The camera obstruction is zeroed.** `App` derives it from the chat panel's
  width, which is correct when the panel is beside the viewer and badly wrong
  when it is below — the model would be framed into a sliver. `DemoApp` sets it
  to `0` on mobile; child effects run before parent effects in React, so this
  lands after the application's own call, and it keys off the same store values
  so the two cannot drift apart.

Two things shrink rather than move. The status readout drops its model name,
fingerprint, and phase — desktop luxuries that would cost a third of the viewer
to repeat what the page already says — and keeps its actions row, which carries
Fit and the quality control the demo opens on. The disclosure card carries a
second, shorter wording: the full paragraph rendered at 228 px on a 390 px
screen, over half the viewer and on top of the 3D controls. Trimming the type
was not enough; the sentence had to be shorter. The narrow attribution is
shorter but not lighter — title, author, source, licence, and the fact of
modification are all still named, because those are the licence's requirements
rather than a house style.

`demo-site/e2e/mobile.spec.ts` runs the suite at 390 x 844: the viewer and panel
stack full-width and meet exactly, the picker and the quality control are
clickable, the page does not scroll sideways, and the disclosure and CC BY credit
survive the narrow layout.

---

### 6.8 Touch orbits around the touched point

The application resolves an orbit pivot from whatever is under the cursor, but
only for the middle mouse button — the one it maps to `ROTATE`:

```
if (e.button === 1) { void this.setPivotFromCursor(e); ... }
```

A touch reports `button === 0`, so that branch never runs on a phone. Meanwhile
`configureControls` sets only `mouseButtons` and leaves `touches` at the
camera-controls default, where one finger rotates. The model therefore orbited
around whatever the target happened to be — usually the centre of the last fit —
rather than around the thing being dragged, which reads as the building sliding
away from your finger.

`demoTouchPivot.ts` forwards a primary touch to the application's own
`setPivotFromCursor`. It resolves nothing itself: no raycasting, no target
arithmetic, no second definition of what a pivot is, so if that method changes,
touch changes with it. The listener is registered with `capture` on the viewer
container, which runs before camera-controls' own listener on the canvas inside
it. Only the primary pointer qualifies — a pinch's second finger would otherwise
move the ground mid-zoom.

The module exposes a counter on `window` purely as a test seam. Where the pivot
lands is the application's logic and its tests; what belongs here is narrower —
that a touch reaches the resolver and a mouse press does not — and nothing else
can observe that from outside. A browser test that cannot fail would be worse
than none.

---

## 7. Fixture data contract

### 7.1 Files

```
fixtures/
  questions.json      demo manifest: id, label, route badge, preSelection, latency, tokens
  models.json         ModelListResponse
  floors.json         ModelFloorsResponse
  load-model.json     QueryResponseEnvelope for the confirm handshake
  answers/
    count-01.json     QueryResponseEnvelope
    group-01.json     QueryResponseEnvelope
    describe-01.json  QueryResponseEnvelope
  resolve.json        ResolveEntitiesResponse entries for the pre-selection
  entities.json       EntityDetailsResponse keyed by global_id
  highlights.json     HighlightGroupResponse keyed by global_id + scope
```

Every response file is the **verbatim JSON envelope** the backend returned, not a
hand-authored approximation. Typed against `src/api/types.ts` so drift breaks the
typecheck.

### 7.2 Capture procedure

Owner-run, against a live local stack: `npm run capture:demo`.

1. Owner starts PostgreSQL and the backend with their own `.env`, with the
   Schependomlaan model imported as `source_model_id: 1`.
2. The script narrows the catalog to that one model — the local catalog holds
   four, and offering models whose artifacts the demo does not ship would give
   visitors three ways to break the page.
3. Each question is asked **in its own fresh session**, re-performing the
   model-load handshake first. The backend keeps chat history and selection in
   server-side session state, so sharing one session lets the second question be
   answered in the shadow of the first — which is exactly what made the first
   capture attempt disagree with everything measured before it.
4. Each question is asked `ATTEMPTS` times (default 3) and the best-scoring
   answer is kept (§7.4).
5. The deterministic endpoints — floors, resolve, entity details, highlight
   groups — are captured for everything reachable from the kept answers. These
   are LLM-free and cost no tokens.
6. `model_assets/1/57fafa…frag` is copied to `demo-site/public/model.frag`.

No key is read, printed, or handled at any step. The script talks HTTP to a
process the owner already started.

`scripts/probe.ts` is the companion tool for *choosing* questions: it asks
candidates and reports route, basis, operation, presentation and counts without
writing fixtures.

### 7.3 Bounded capture and the fallback

Details are captured for entities reachable from the three answers — the 5 walls,
the storey and its 200 related elements, the 20 facade elements and their 50
context entities. Roughly 300 of the model's 6,989 entities.

A visitor clicking any other element gets an explicit notice that this element's
details were not captured for the demo, with the repository link. This is a
stated limitation, not a silent failure.

If the captured payload proves small, the set may be widened toward all 6,989
entities (token-free, purely a bytes question) in a sharded, lazily-fetched form.
Decided by measurement after the first capture, not in advance.


### 7.4 The pipeline is nondeterministic, and capture keeps the best of N

The binder is an LLM, so the same question against the same data does not give
the same answer twice. Measured on this model:

| Question | One run | The next run |
| --- | --- | --- |
| *List five walls with their names.* | 50 entities, `result_table`, five names | 1 entity, no panel, "I can't list five" |
| *What elements are contained in this storey?* | `graph_traversal`, **3,505 elements** | "contains none" — **wrong** |
| *Describe the walls in this model.* | `hybrid_evidence` | `exact_sql` |

A single capture is therefore a coin flip on quality, and one bad flip publishes
a demo that misrepresents the system as worse than it is — or, in the storey
case, publishes a confidently wrong number.

Capture asks each question three times and keeps the highest-scoring answer,
scoring for: retrieved something, produced a panel, did not have to refuse, and
reached the basis the question was chosen to demonstrate. Every attempt is
logged, so the spread is visible when it runs.

**This is selection among real recorded runs. Nothing is edited or synthesised.**
It does show the system at its best rather than its average, and that is stated
here rather than left implied. The questions in §5 were chosen partly *for*
stability: `count-01` and `group-01` returned identical results on all three
attempts.

---

## 8. Dataset and attribution

### 8.1 The model

**IFC Schependomlaan incl planningsdata** — the design model for a Dutch
residential project, made in ArchiCAD by ROOT bv, published through
openBIMstandards and distributed in buildingSMART's `Sample-Test-Files`
repository at `IFC 2x3/Schependomlaan`. 6,989 entities, 3,473 relationships.

It is already the model every published BIMtrieval benchmark ran against, so the
demo shows the system on the dataset its evidence describes.

### 8.2 License

`buildingSMART/Sample-Test-Files` carries **CC BY 4.0**, which permits
redistribution and modification with attribution.

`ATTRIBUTION.txt` ships in `public/`, and the same notice appears in the site
footer — CC BY requires attribution reach the recipient, and a file nobody opens
does not achieve that. The notice names the model, the originating authors, the
buildingSMART source, the license with its URL, and — as CC BY separately
requires — **states that the file was modified**: converted from IFC to the That
Open Fragments binary format for web rendering.

### 8.3 A residual licence question, accepted by the owner

The repository-level grant on `buildingSMART/Sample-Test-Files` is CC BY 4.0, and
that is the basis on which this demo redistributes the model. One loose end was
identified and **deliberately not closed**: the openBIMstandards publication of
this dataset describes permission granted "for scientific and academic
purposes," which is narrower than CC BY 4.0. Confirming that no README inside
`IFC 2x3/Schependomlaan` restates that narrower term — and therefore that the
repository grant governs — was specified as a blocking pre-publication check.

The owner has elected to proceed without it. The risk is recorded here rather
than quietly dropped, because the decision is reversible and the fix is cheap:

- **If the narrower term does govern**, a portfolio demo is a weaker fit for
  "scientific and academic purposes" than a research project is, and the model
  would need replacing.
- **The fallback** is an expanded synthetic model derived from
  `frontend/tests/fixtures/smoke-wall.ifc`, which the project owns outright. Less
  impressive, zero licensing exposure. The three questions would need re-capture
  and re-selection against it.
- **Nothing else depends on the choice of model.** The substitution mechanism,
  the fixture contract, the picker, and the deploy path are all model-agnostic,
  so swapping the dataset is a re-capture, not a rewrite.

Attribution is given in full either way (§8.2), which is what CC BY 4.0 requires
and what an academic-use term would also expect.

---

## 9. Build and deploy

### 9.1 Scripts

Added to `frontend/package.json`, separately named so they never enter the
existing offline gate:

```
dev:demo        vite --config demo-site/vite.config.ts
build:demo      tsc -p demo-site/tsconfig.json && vite build --config demo-site/vite.config.ts
preview:demo    vite preview --config demo-site/vite.config.ts
typecheck:demo  tsc -p demo-site/tsconfig.json
capture:demo    tsx demo-site/scripts/capture.ts
```

`npm run build`, `npm test`, `npm run typecheck`, and `npm run lint` keep their
current meaning and current output.

### 9.2 Vite configuration

The demo config imports the existing `frontend/vite.config.ts` settings it needs
— the `optimizeDeps.exclude` for the That Open workers and WASM, and the
`manualChunks` split — rather than restating them, so an engine upgrade does not
have to be applied twice. It adds `base` (from `VITE_DEMO_BASE`, defaulting to
`/BIMtrieval/`), the two aliases (§4.2), and `build.outDir` of `dist-demo`.

### 9.3 Workflow

`.github/workflows/demo-pages.yml`:

- triggers on push to `main` under `paths: frontend/demo-site/**`,
  `frontend/src/**`, `frontend/package.json`, and the workflow file itself —
  so a demo-only change deploys, and a change to the shared frontend source the
  demo imports also redeploys.
- also exposes `workflow_dispatch` for a manual redeploy.
- Node 22, `npm ci`, `npm run build:demo`, then `actions/upload-pages-artifact`
  and `actions/deploy-pages`.
- permissions `pages: write`, `id-token: write`, `contents: read`.
- **no secrets of any kind.** The workflow that builds the demo has no reason to
  hold a credential, and holding none is checkable.

### 9.4 SPA routing

The demo is a single route with no client-side router, so no `404.html` fallback
is required. If routing is added later, the standard Pages `404.html` copy step
goes here.

---

## 10. Manual owner steps

Performed by the owner; never by an assistant (`AGENTS.md` scope constraint).

1. Confirm the `BIMtrieval` repository is **public**.
2. Repository → Settings → Pages → Source = **GitHub Actions**.
3. Start the local stack and grant permission for the capture run (§7.2).
4. After the first successful deploy, verify `https://daegeun-kim.github.io/BIMtrieval/`
   loads, the model renders, and all three questions replay.
5. Add the link to the portfolio's BIMtrieval project page.
6. Update `README.md` (§12) — deferred until the demo is live.
7. Decide how to resolve the stale published benchmark (§5.4, §12) — independent
   of the demo, but discovered by it.

The Schependomlaan licence check that was step 1 has been consciously set aside;
§8.3 records what was accepted and what the fallback is.

---

## 11. Validation

### 11.1 Offline checks

Added to the frontend's existing test suite, so they run in the default gate:

- **`src/` is unmodified** — a test asserting the demo introduces no edit under
  `frontend/src/`, enforcing this specification's central constraint.
- **Fixture completeness** — every question in `questions.json` has an answer
  envelope; every `preSelection` global_id has a `resolve.json` entry.
- **The demo still makes its argument** — the three questions cover three
  different bound operations and more than one retrieval basis. A re-capture that
  collapses them onto one operation leaves a working demo that has stopped
  demonstrating anything, and that fails here.
- **The route really is uniform** — asserted deliberately, so a later reader does
  not "fix" the badge back to `route` and print "hybrid" three times.
- **Fixture typing** — every captured envelope satisfies the `src/api/types.ts`
  types, so a backend contract change fails the build rather than shipping a
  stale demo.
- **No secrets** — no fixture, config, or workflow file contains a
  credential-shaped string, matching the existing
  `backend/tests/test_deployment_policy.py` posture.
- **Alias coverage** — `src/api/client.ts` and `src/chat/Composer.tsx` are each
  imported exactly once in `src/`, so a future refactor that adds a second import
  site fails loudly instead of leaving the demo half-live. This is the guard that
  keeps §4.1 true over time.
- **`build:demo` succeeds** with the correct `base` in emitted asset paths.

### 11.2 Browser check

`demo-site/e2e/demo.spec.ts`, run by `npm run test:e2e:demo` against its own
Playwright config so neither suite starts the other's dev server. Three cases:

- the demo boots straight into the model with **no confirmation dialog**, and the
  load overlay retires — exercising the real Fragments worker and WebGL;
- the picker shows no route badge until a question is asked, and reveals `routed
  to …` with the recorded cost afterwards;
- the disclosure banner and the CC BY attribution are on the page.

The 3D artifact is stubbed with the small tracked `smoke-wall.frag`, so the suite
does not depend on the 5.5 MB model that is absent from Git (§14.4). The source
fingerprint is only ever a cache key and is never validated against the bytes, so
the substitution loads cleanly.

Unlike the application's browser suite, this one **is** wired into the deploy
workflow. The output here is a public page, and the structural guards in §11.1
cannot see a runtime break.

### 11.3 Acceptance

The demo is complete when a visitor with no account, no key, and no local setup
opens one URL, sees the building, asks three questions, gets three grounded
answers with citations and 3D highlights by three different routes, and can tell
from the page that it is a recording.

---

## 12. Documentation changes

Deferred until the demo is live, then applied in one pass:

- `README.md` — the "There is no hosted demo, deliberately" paragraph
  (`README.md:119`) becomes **factually wrong** the moment the link exists. It is
  narrowed, not deleted: there is still no hosted *live-query* backend, no shared
  key, and no public database, and those reasons stand. The demo link is added
  above it, with one line saying what the demo is and what it is not.
- `docs/self-hosting.md` — a pointer noting the demo is not an instance.
- `frontend/demo-site/README.md` — how to run and re-capture the demo locally.

Separately, and **not** a demo task: the published benchmark and the README
describe route behaviour the current backend cannot produce (§5.4). Building this
demo is what surfaced it. `AGENTS.md` requires documentation to be current and
non-contradictory, so it needs resolving — by re-running a benchmark against the
current pipeline, or by marking the published one as describing a superseded
architecture. It is the owner's call and is listed in §10.

Per `AGENTS.md`, the superseded claim is corrected rather than left to
contradict the new one.

---

## 13. Risks and open items

| Risk | Handling |
| --- | --- |
| Schependomlaan's academic-use wording narrows the CC BY grant | **Accepted by the owner** (§8.3). Attribution given in full; synthetic-model fallback specified and cheap, since nothing but the fixtures depends on the model |
| 5.5 MB artifact on a cold load | Within Pages limits; the existing `manualChunks` split already separates the engine. Measure after deploy; a loading state already exists |
| Frozen answers drift from backend behaviour | Fixtures typed against `src/api/types.ts`; typecheck fails on contract change |
| A future refactor adds a second `api` import site | Alias-coverage test (§11.1) fails the build |
| Demo mistaken for a live system | Persistent banner + per-answer recorded latency (§6.4) |
| Pre-selection replay looks stitched | Captured with the selection genuinely made (§5.3, §7.2) |

Open, to decide by measurement rather than in advance:

- whether the captured detail set widens beyond ~300 entities (§7.3);
- whether the demo later moves to `bimtrieval.daegeunkim.com` (§2.2).

---

## 14. Implementation notes

Recorded where the build differed from the plan above, so the specification and
the tree do not disagree.

### 14.1 The alias must match the whole specifier

A regex alias substitutes only the span it matches. Anchoring on `/api/client`
alone rewrote `../api/client` to `..<absolute path>` and the build failed to
resolve it. Both patterns now match the entire specifier
(`/^.*\/api\/client$/`, `/^\.\/Composer$/`).

### 14.2 Fixture typing is enforced at runtime, not by `tsc`

§7.1 planned to type the recorded envelopes against `src/api/types.ts`. Imported
JSON is typed as its own literal shape and does not structurally satisfy the
OpenAPI-derived unions — a recorded `"sql"` is a `string`, not a `QueryRoute` —
so the loaders in `fixtures.ts` cast, and the guarantee moves to
`tests/demo-site.test.ts`, which runs in the offline gate. The demo's own sources
are still fully type-checked (`typecheck:demo`).

### 14.3 Highlight groups are captured for primary entities only

Capturing three scopes for every context entity would have tripled the request
count for entities a visitor is unlikely to click first. Uncaptured groups
degrade with the same honest notice as uncaptured details (§7.3).

### 14.4 The 3D artifact is committed

`frontend/demo-site/public/model.frag` (5.5 MB) is tracked. It was briefly
`.gitignore`d pending the §8.3 licence check; the owner elected to proceed, so
the rule is gone and a comment marks the path as intentionally not ignored —
otherwise the next reader of `.gitignore` sees a 5.5 MB binary under `public/`
and assumes it was committed by accident.

The deploy workflow still fails loudly if the artifact is absent, so a mis-clone
or a stray ignore rule cannot quietly publish an empty viewer.

### 14.5 The route badges were removed from the un-asked cards

The first build labelled every button with its route and a description. That
inverted the demo's own argument — see §5.1. The route, the retrieval basis, the
bound operation and the recorded latency now appear only after the question is
asked.

### 14.6 The badge shows `answer_basis`, and the manifest is generated

The first manifest hand-wrote `route: sql | graph | rag` next to each question.
Capture then recorded envelopes saying `hybrid` — so the card would have printed
a label its own answer contradicted. Every labelled field is now written by
`capture.ts` from the recording; only `text` and `blurb` are editorial.

### 14.7 Two capture bugs, both found by disagreeing results

- **One session for all three questions.** The backend keeps chat history
  server-side, so questions 2 and 3 were answered in the shadow of question 1.
  Each question — and now each retry — gets its own session.
- **A hardcoded `selected_entity_ids: [254]`,** copied from the benchmark. Entity
  ids shift between imports. The storey is now resolved from the floors endpoint
  by `global_id`, which is also what the viewer does when a visitor clicks.

### 14.8 Three bugs in one corner of the screen

The disclosure card and the application's status readout both want the
bottom-left. Getting them to share it took three goes:

1. **The card covered the readout entirely**, hiding the Fine / Standard / Fast
   control. It rendered and reported the right state; it just could not be
   clicked. Found by an e2e case that *clicks* the control rather than reading
   it — an assertion that only reads UI state cannot see an unreachable element.
2. **Moved to the top of the screen**, which cleared the collision but left the
   card floating away from the UI it belongs to.
3. **Docked above the readout and matched to its width** by measuring `.readout`
   at runtime. The first version of that measurement connected its
   `MutationObserver` only when the readout was missing at mount, then stopped
   observing — so the card docked once against a half-rendered readout and kept
   those numbers, ending up 175 px wide against a 213 px card and overlapping it
   by 33 px. Both observers now stay live, because React can also replace the
   node and orphan a `ResizeObserver` pointed at the old one.

`demo.spec.ts` now asserts the left edge, the width, and a positive gap.

### 14.9 Measuring a card mid-reflow, twice

The disclosure card docks by measuring `.readout`, and that measurement has now
been wrong in two different ways:

- **Stale.** The mutation observer was connected only when the readout was
  missing at mount, then stopped. The card docked once against a half-rendered
  readout and kept those numbers (§14.8).
- **Transient.** Crossing the mobile breakpoint reflows the readout — the media
  query hides its text lines, the remaining controls re-wrap — and a measurement
  taken inside the `resize` handler caught it mid-reflow. The card pinned itself
  at 34 px wide and 1200 px tall, off the top of the screen. **Rotating a phone
  is enough to reach it.**

Both come from the same root: a synchronous read of a layout that has not
settled. Measurement now happens on the next animation frame rather than inside
the event, a resize gets a second look 250 ms later for reflows that span several
frames, and an implausibly narrow reading is discarded rather than cached.

`mobile.spec.ts` rotates portrait → landscape → desktop → portrait and asserts
the card stays sane at every step.

A third variant of the same fault followed on the live site: **before the model
loads**, the readout is an empty shell with no measurable width, so the card
never docks and falls back to CSS — and the desktop fallback (`bottom: 150px`)
lands inside the panel sheet on a phone. Every test then written waited for the
curtain to lift, so none of them could see the state that was broken. The mobile
fallback is now anchored to the viewer band, and `mobile.spec.ts` has a case that
holds the page in its loading state by never fulfilling the model request.

### 14.10 Verified

`npm run build:demo` succeeds; the emitted `index.html` carries the
`/BIMtrieval/` base; **no backend URL survives anywhere in the demo bundle**; all
487 existing frontend tests, `tsc -b --force`, and `eslint .` still pass; the 13
guards in `tests/demo-site.test.ts` pass; and the 14 browser cases in
`demo-site/e2e/` (6 desktop, 8 mobile) pass.

Served locally, the demo boots, auto-loads the model without a confirmation
click, renders the picker showing question text alone, replays a question through
the real controller and the real transcript, and reveals
`answered by · exact SQL · group distribution · took 22.3 s` afterwards.

The 3D scene renders correctly in a real browser and under Playwright Chromium,
where `demo.spec.ts` watches the load overlay retire in ~5 s with the real
Fragments worker and WebGL. It does **not** finish in the embedded browser used
for interactive checks during development, which stalls at the *Scene* phase with
no console error and every asset served 200 — a limitation of that environment
alone.

Two things no automated check can judge, both needing a human (§10, step 4):
whether the opening framing looks right (`DIRECTION` and `ZOOM` in
`demoCamera.ts`), and whether the explanation panel renders as intended — it
opens only once `viewer.hasModel()` is true, so it is invisible in the embedded
browser even though the recorded envelope carries `select_and_fit` and a full set
of highlight ids.
