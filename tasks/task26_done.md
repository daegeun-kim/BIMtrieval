# Task 26: Synchronized Query Explanation Panel

## Goal

Add one new frontend panel that explains the latest highlighted query result with an
appropriate structured visualization.

The natural-language query backend remains the main product. The new panel is a visual
explanation of the backend's already-computed authoritative result; it is not a second
analysis system, collaboration feature, report builder, or replacement for the chat.

When the latest answer highlights model objects:

- open a separate **Query Explanation** card above the chat;
- reduce the chat to the lower 40% of the right-side column;
- use the upper 60% for the explanation card;
- keep the explanation content synchronized with the objects currently highlighted in
  the 3D viewer;
- let a user select a displayed table/chart group to highlight only that subgroup, with
  an **All results** action that restores the original result.

Start small. Do not add unrelated panels, persistence, collaboration, role management,
automatic reports, or speculative analysis.

---

## 1. Hard backend boundary

The existing query and LLM pipeline must remain behaviorally unchanged.

Do not change:

- semantic-manifest generation or loading;
- candidate recommendations or constraint ledger;
- binder, correction, or grounded-answer prompts or schemas;
- model assignments, reasoning settings, or LLM call count;
- binding, validation, closure, SQL/RAG/graph mode derivation, or execution semantics;
- exact/zero/partial/unavailable/ambiguous classification;
- answer-packet content sent to the final LLM;
- final grounding validation or deterministic fallback;
- the predicate used to produce the reported answer and viewer identities;
- the prose answer returned by the current pipeline.

Do not run an additional LLM call for the panel. Do not parse the prose answer to construct
the visualization.

The panel may use only structured information already calculated for the accepted answer.
Do not automatically calculate additional floor, type, material, property, or other
breakdowns merely to make a richer chart.

### 1.1 Additive presentation contract

The current public response does not expose all structured fields already present on the
authoritative primary `AnswerPartResult`. Add one optional, bounded presentation payload
to `QueryResponseEnvelope` for the primary visual answer part.

Expose only what the pipeline already established, as applicable:

- answer-part ID and request label;
- operation and result status;
- plain-language interpretation;
- retrieval modes/basis;
- exact total;
- existing class breakdown;
- existing distribution buckets;
- existing aggregate value, unit, matched count, coverage count, and completeness;
- existing relationship endpoint summary;
- limitation and known/unknown parts;
- shown identity count, true result count, and truncation state;
- bounded rows/groups and the GlobalIds required for supported viewer interaction.

The exact schema/component names are implementation details, but the contract must be
typed, allowlisted, bounded, additive, and regenerated into the frontend OpenAPI types.
Never expose raw SQL, prompts, predicates, canonical JSON, complete manifests, credentials,
or internal database diagnostics.

Any identity hydration needed solely to reproduce an already-calculated displayed group
must happen deterministically after the normal query result is complete. It must not alter
the query interpretation, answer facts, LLM inputs/outputs, or primary viewer result.
Never invent subgroup membership. If an authoritative identity subset cannot be supplied,
do not present that value as an interactive selectable group.

Existing clients that ignore the optional payload must continue to work.

---

## 2. Panel lifecycle and synchronization

The explanation card represents the current query-result highlight, not general chat
history.

- Open it only after the latest completed query returns a non-empty primary highlighted
  object set and an explanation payload for that same result.
- Replace its content when a newer qualifying query result is applied.
- If a newer completed query has no highlighted result, retire both the previous
  explanation and the previous query highlight so the panel and viewer cannot disagree.
- Close and clear it on Clear Chat, Reset App, model switch/unload, or an explicit viewer
  selection-clear action.
- Give the explanation card its own close control. Closing it also clears its query-result
  highlight.
- A stale, canceled, failed, or superseded request must never reopen or overwrite the
  current explanation.
- Preserve the original full-result primary/context GlobalIds in frontend state so
  **All results** can restore the exact original viewer roles without another LLM query.

Opening the existing component panel by clicking an object does not replace the query
explanation or its result highlight. It only adds the existing selected-object/detail
context.

If an existing deterministic component-panel action such as **Same type** or **Same
family** replaces the query highlight with a different group, retire the query explanation
at the same time. The explanation must never describe one set while the viewer emphasizes
another.

---

## 3. Fixed desktop layout

Keep the current full-height, resizable chat layout unchanged whenever no explanation card
is open.

When the explanation card is open:

- create a fixed right-side column occupying 40% of the viewport width;
- preserve the existing 20 px outer viewport margins;
- render the explanation and chat as two visually separate floating cards with the same
  surface, border, rounded corners, shadow, typography, spacing, and measured-drawing
  styling as the existing chat panel;
- keep a 12 px gap between the two cards;
- allocate 60% of the available column height to the explanation card and 40% to the chat;
- place the explanation card above and the chat below;
- keep this Task 26 layout fixed: do not add a vertical splitter, horizontal resizer, saved
  explanation-panel preference, or drag/reorder behavior.

When the 320 px component-detail panel opens:

- keep it immediately left of the explanation/chat column, with the existing 12 px gap;
- reduce the explanation/chat column from 40vw to 32vw;
- keep the explanation and chat at the same 60/40 height split;
- restore the column to 40vw when the component panel closes.

Update the viewer-obstruction calculation from the same live layout state so camera fitting
and visible-region centering account for the complete right-side panel stack. Do not create
a second independent set of hard-coded obstruction measurements.

Keep the existing component panel itself and its contents unchanged. Handle the existing
chat collapse/restore control coherently within the fixed stacked layout without adding a
new layout mode; the minor interaction choice is left to implementation so long as panels
do not overlap and the result can be restored accessibly.

---

## 4. Explanation content

The explanation card always contains two content regions:

1. the appropriate visualization or table;
2. a persistent basic-information text region at its right.

Do not show a chart or table alone.

The right-side information region must state, in compact plain language:

- what question/result part the card represents;
- what the backend interpreted;
- what objects or subgroup are currently highlighted;
- shown count versus exact/true count where truncation exists;
- operation/result status and answer basis;
- active limitation, coverage note, or known/unknown split where applicable.

When the user selects a chart/table group, update this text so it clearly distinguishes the
selected subgroup from the full answer, for example:

```text
Showing: IfcDoor
5 of 9 query-result objects
Full result: 9 external doors on floor 3
```

The basic-information text is descriptive only. It must not introduce a new LLM
interpretation or factual claim.

### 4.1 Initial visualization set

Choose the visualization from the authoritative operation/data:

- **count / existence:** headline metric plus existing class breakdown when meaningful;
- **list:** exact total plus a bounded, scrollable result/group table;
- **group distribution:** compact horizontal bar chart from the existing distribution;
- **aggregate / extremum:** value and unit with matched/coverage information;
- **relationship:** endpoint count and bounded endpoint/class summary;
- **partial:** known-versus-unknown presentation alongside any supported exact portion.

Show only the backend-designated primary visual answer part for a multi-part question.
Do not union unrelated answer parts.

Use restrained, accessible styling consistent with the current bright measured-drawing
theme. A large charting dependency is not required; the implementation may use ordinary
React/CSS/SVG where sufficient.

---

## 5. Viewer interaction

Displayed interactive rows/groups must be backed by authoritative GlobalIds from the
accepted result.

- Clicking a chart bar or table group applies that subgroup as the viewer's primary
  highlight.
- Make the active group visually clear in the explanation card.
- Provide **All results** whenever a subgroup is active.
- **All results** restores the original primary and relationship-context roles exactly.
- Preserve the exact total even when viewer identities are capped; disclose truncation
  rather than implying the displayed identities are exhaustive.
- Never issue a hidden natural-language query or LLM call when selecting or restoring a
  group.
- Never allow a chart count, right-side information text, and viewer highlight to describe
  different sets without an explicit shown-versus-total disclosure.

Clicking an individual object continues to use the existing deterministic object-detail
flow and existing component panel. Do not redesign that panel in this task.

---

## 6. State and clearing

Keep explanation state serializable and current-session only. Store only the bounded
presentation payload, original viewer roles, active subgroup, and lifecycle state needed
for this UI.

Do not persist explanation content or selected groups to local storage, create saved
reports, or add backend write tables.

Clear/retire the state consistently for:

- Clear Chat;
- Reset App;
- model switch/unload;
- manual explanation close;
- a newer answer with no highlight;
- a component group action that replaces the query result;
- canceled/superseded request protection.

Manual object selection and the existing selected-object query chips remain unchanged.

---

## 7. Validation

Add focused backend and frontend tests without making live OpenAI calls.

Backend contract tests must verify:

- the optional explanation payload is allowlisted and OpenAPI-generated;
- it is derived from the already-computed primary visual answer part;
- exact totals, coverage, distributions, limitations, and identities remain bounded and
  truthful;
- clarification/no-highlight responses do not expose a stale explanation;
- presentation serialization does not change prompts, LLM calls, answer text, answer
  facts, viewer totals, or primary viewer identities;
- no extra semantic breakdown is calculated for presentation.

Frontend tests must verify:

- qualifying highlighted answer opens the fixed 60/40 stack;
- a non-highlighted newer answer closes the panel and clears the previous query highlight;
- a newer qualifying answer replaces both explanation and highlight;
- each supported operation selects the appropriate presentation;
- every presentation retains the right-side basic-information text;
- group/table selection updates viewer highlight and displayed basic information;
- **All results** restores original primary/context roles;
- manual close, Clear Chat, Reset App, and model switch clear panel and highlight;
- stale/canceled responses cannot restore old content;
- component selection opens the existing 320 px panel and reduces the shared column to
  32vw without overlap;
- closing the component panel restores 40vw;
- existing component detail behavior remains intact;
- keyboard/focus behavior and reduced-motion support remain usable.

Run the existing frontend build, typecheck, lint, component/unit tests, and critical
Playwright path, plus relevant backend offline contract/query tests. Do not rerun the
costly live LLM benchmark merely for this presentation task.

---

## Acceptance outcome

After a query highlights objects, the user sees:

```text
right side, upper 60%: Query Explanation card
right side, lower 40%: existing Chat card
optional left neighbor: existing Component Detail card
```

The explanation card visualizes only the accepted result data, always includes compact
plain-language information about what is currently shown, and stays synchronized with
the 3D highlight through subgroup selection, restoration, new queries, clearing, and
component-panel interaction.

The existing query/LLM pipeline produces the same interpretations, facts, answers, viewer
result sets, and call behavior as before Task 26.
