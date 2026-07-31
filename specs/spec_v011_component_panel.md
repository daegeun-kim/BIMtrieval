# Specification v011: Component Panel

## 1. Purpose and authority

A bounded, read-only panel that shows what the database already stores about **one** selected object,
with an isolated preview of that object and three deterministic highlight actions: `Instance`,
`Same type`, and `Same family`.

This specification is authoritative for the component detail and highlight-group contracts, the
panel's behavior and placement, the isolated preview, and the panel's lifecycle and staleness rules.

It is governed by `spec_v006_frontend_application.md`, which owns the shared layout system,
application lifecycle, state and clearing semantics, security, testing policy, and acceptance
criteria. Related frontend specs: `spec_v008_3d_viewer.md` (selection, picking, highlighting, camera
fit), `spec_v009_chat_panel.md` (chat and citations), `spec_v010_explanation_panel.md` (structured
explanation of the latest query result).

Every action in this panel is deterministic: no OpenAI call, no embedding, no IFC parse, no database
write, no chat message, and no session/conversation mutation. This is not a full object property
panel, an editor, or a metadata dashboard.

## 2. Backend contracts

Both routes are read-only, active-model scoped, deterministic, and LLM-free.

```text
GET  /api/models/{source_model_id}/entities/{global_id}/details
POST /api/models/{source_model_id}/entities/highlight-group
```

### 2.1 Details

Returns an allowlisted, count- and length-bounded schema — never raw canonical JSON, geometry,
vectors, SQL, prompts, or paths:

- `instance` — always available for a valid entity: GlobalId, IFC class, name, description,
  object/predefined type, tag, storey name/GlobalId, elevation (when stored), materials, and
  allowlisted quantities/properties.
- `type` — present **only** when the source IFC explicitly supplied type data.
- `family` — present **only** when an allowlisted family-like property exists in a stored property
  set, returned with its source property-set and property name.
- `availability` — truthful `instance` / `same_type` / `same_family` flags plus a concise reason for
  each unavailable action, so the frontend can disable a button and say why.

Absent optional layers are **omitted**, never returned as empty placeholders. An unknown or
cross-model GlobalId returns the same bounded `404 unknown_entity`, never revealing that the entity
exists in another model.

### 2.2 Highlight group

Takes `{selected_global_id, scope: instance|type|family}` and returns the selected scope, truthful
`available`, the **exact** `total`, up to 2,000 deterministically ordered `global_ids`, a `truncated`
flag, compact `class_counts`, and a bounded `unavailable_reason`.

Matching is exact:

- `instance` = the selected entity;
- `type` = the explicit type GlobalId, falling back to the exact normalized stored type name only when
  the IFC gave no GlobalId;
- `family` = the exact normalized value of the same allowlisted stored property the selection's family
  came from.

Never a name-derived guess, never an inferred grouping, never an LLM.

### 2.3 Truthful degradation

A model whose entities carry no explicit `canonical_json.type` makes `same_type` and `same_family`
unavailable. The panel must then **disable those buttons with the concrete backend reason**, not hide
them, invent a grouping, or report an error. This is correct behavior. Models that do expose type or
family data enable the actions automatically from already-stored canonical data — no schema change and
no re-ingestion.

## 3. Opening and content

The panel opens when a single object is focused in the viewer — a plain click on a pickable object
(`spec_v008` §5), or a citation click (`spec_v009` §5). It shows:

- the isolated preview (§5);
- a bounded, read-only detail list built strictly from §2.1, with absent fields omitted;
- the `Instance` / `Same type` / `Same family` actions (§4);
- a close control.

The detail list is scrollable; the panel never dumps the full component set behind a query result and
never displays raw canonical JSON.

## 4. Highlight actions

Each action calls §2.2 and applies the returned identities as the viewer's primary highlight through
the same role machinery a query result uses (`spec_v008` §6.1), including the 2,000-identity cap and
its truncation disclosure. Group fit uses the shared moderate fit policy (`spec_v008` §4.3).

An action never creates a chat message, an LLM call, a backend query, or a session mutation. An
unavailable action is disabled with its stated reason.

Because a `Same type` / `Same family` highlight replaces the current query-result highlight, it retires
the explanation panel at the same moment (`spec_v010` §11). Opening the component panel by clicking an
object does **not** retire it.

## 5. Isolated preview

The preview renders **only the selected instance**, from geometry buffers extracted out of the
already-loaded model (`getItemsGeometry`). There is no second download, no re-parse, and no model
clone. It is lazy: it is constructed when the panel opens and disposed on change, close, model switch,
and reset — every GPU resource, material, and listener released.

Viewport height is `min(320px, 36vh)` (`PREVIEW.viewportHeightPx`), responsive on short viewports, with
the detail list scrollable below it.

Power management (`PreviewScene.ts`), independent of the main viewer:

- rendering is gated on an `IntersectionObserver` (fully paused when off-screen or obscured) and on
  `document.visibilitychange` (paused when backgrounded), stopping the RAF chain entirely rather than
  skipping work inside it;
- auto-rotation is capped at 30 fps (balanced) / 20 fps (large-model profile) and bounded to a **12 s
  lifetime**, after which an idle preview draws nothing;
- pixel ratio is dynamic: 1.0 while actively dragging or wheel-zooming, 1.25 otherwise, including while
  auto-rotating.

The profile that sizes the fps cap and pixel ratio comes from `detectProfile()`, which influences no
main-viewer rendering decision (`spec_v008` §7.4). The main viewer's projected-size visibility policy
never affects the preview (`spec_v008` §7.3).

## 6. Placement

The panel is a floating card 320 px wide, docked immediately left of the right-side panel column with
the existing 12 px gap, sharing the card surface, border, radius, shadow, typography, and spacing of
the other panels.

Its open state feeds the single obstruction/`--chat-w` calculation that drives camera centering and the
explanation column width; there is no second set of hard-coded panel measurements (`spec_v006` §7.3,
`spec_v008` §4.4).

## 7. Lifecycle and staleness

- Stale detail and highlight-group responses are rejected across rapid selection changes, panel close,
  model switch, Clear Chat, and Reset App — a superseded response may never repaint the panel or change
  viewer roles.
- Closing the panel clears its own group highlight.
- Clear Chat drops the panel's group highlight (a query-result role) while keeping the panel, the
  manual selection, the loaded model, and the artifact cache (`spec_v006` §10.1).
- Reset App and model switch close and dispose the panel and its preview entirely (`spec_v006` §10.2).
- Panel state is serializable and current-session only; nothing is persisted to local storage.

## 8. Failure behavior

A details or highlight-group failure shows a bounded, actionable message inside the panel and never
unloads the model, breaks the viewer, or affects chat. An unknown or cross-model GlobalId is reported
as unknown without revealing other models. No credentials, paths, prompts, or stack traces are exposed
(`spec_v006` §11, §13).
