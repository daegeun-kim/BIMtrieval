# Specification v009: Chat Panel

## 1. Purpose and authority

This specification is authoritative for the conversational surface: message presentation, the
composer, answer rendering and its bounded evidence, entity citations, selected-object chips, the
request lifecycle, and the chat panel's own controls.

It is governed by `spec_v006_frontend_application.md`, which owns the shared layout and panel
geometry, application/model lifecycle, state and clearing semantics, the shared backend query
contract, accessibility, security, testing policy, and acceptance criteria. Query interpretation,
routing, answer content, evidence content, and clarification behavior are produced by the backend and
owned by `spec_v002` through `spec_v005`; this specification never restates or reinterprets them.

Related frontend specs: `spec_v008_3d_viewer.md` (viewer selection, highlighting, camera fit),
`spec_v010_explanation_panel.md` (structured visualization of the latest highlighted result),
`spec_v011_component_panel.md` (per-object details).

Submitting a question is the only chat action that may reach an LLM. Rendering, collapsing, citation
clicks, chip removal, cancellation, and clearing are deterministic frontend operations.

## 2. Conversation surface

Use familiar chat interaction standards:

- visually distinct user and assistant messages;
- a scrollable answer history with sensible auto-scroll behavior;
- a composer fixed at the panel bottom;
- Enter submits, Shift+Enter inserts a newline;
- submit disabled for blank input;
- a visible pending state;
- a cancel control while a request is pending;
- no automatic duplicate submission;
- accessible keyboard and focus behavior.

Chat history is bounded and current-session only; it is never written to localStorage
(`spec_v006` §10).

Precise message styling and micro-interactions are design decisions, made with the `frontend-design`
workflow, that must not expand scope or change contracts.

## 3. Availability

The chat surface is continuously available, including before any model is loaded and after a model
load fails: catalog and general questions must remain answerable. It never blocks on viewer state.

## 4. Answer rendering

### 4.1 Prose

Render sanitized Markdown supporting ordinary paragraphs, lists, emphasis, code snippets, and small
tables. Raw HTML and unsafe URL protocols are disabled. All API strings and model names are untrusted
display data.

### 4.2 Result summary

An answer displays the concise prose answer, the exact total, and a compact class summary derived from
the backend's `result_summary` (`spec_v006` §9.4) — for example `880 walls`, with wall subtypes merged
under one label.

The exact total, the viewer highlight count, and the bounded LLM evidence list are three independent
numbers and must be presented as such; a truncated highlight set is disclosed rather than implied
away. Chat never dumps the component list behind a count.

### 4.3 Evidence disclosure

Each answer may carry a compact evidence disclosure, **collapsed by default**, containing:

- route and answer basis;
- SQL/RAG/relationship counts where present;
- primary entities;
- relationship-context entities;
- relationships;
- warnings and notes.

Evidence lists stay bounded by the backend contract; the frontend never expands them with additional
requests.

Never display raw prompts, raw SQL, vectors, credentials, unrestricted canonical JSON, internal
identifiers of the query pipeline, or stack traces.

### 4.4 Clarification and catalog candidates

Backend clarification questions appear as ordinary assistant messages. Catalog candidates appear as
compact selectable controls inside the conversation — never a separate catalog page or card grid.
Selecting a candidate only *proposes* a model; loading still requires the explicit confirmation step
in `spec_v006` §8.2.

### 4.5 Per-object detail

One component's details appear in chat only on the backend's explicit sample-detail intent. General
per-object inspection belongs to the component panel (`spec_v011`).

## 5. Entity citations

Entity references displayed with an answer are clickable. Clicking one:

- verifies the entity belongs to the active model;
- selects and highlights the rendered object;
- centers it and enlarges it only moderately, through the viewer's shared fit policy
  (`spec_v008` §4.3, §4.4);
- does not submit a query, call the LLM, or create a chat turn.

A citation whose GlobalId is not renderable produces a bounded, non-blocking notice; the answer and
the viewer stay intact.

## 6. Selected-object chips

Objects selected in the viewer (`spec_v008` §5.1) appear as compact removable chips near the composer,
capped at five. The chips are the accessible non-canvas representation of the current selection: they
carry entity names/identity as text, not color alone.

At the cap, explain the limit instead of silently replacing a chip. Removing a chip removes the
selection. Chips are supplied with the next question as `selected_global_ids` (`spec_v006` §9.3) and
survive Clear Chat (`spec_v006` §10.1).

## 7. Request lifecycle

The backend is non-streaming. Show honest staged/busy feedback rather than simulated token streaming.

- Cancellation is frontend-initiated through `AbortController`; server cancellation is best-effort.
- Ignore late responses whose request, session, or active model is no longer current. A stale response
  may never render a message, change viewer roles, or open a panel.
- For a retryable connection or provider failure, offer exactly one user-triggered Retry action. Never
  retry an LLM query automatically. This is an MVP convenience, expected to be reconsidered later.
- A pending request is cancelled/retired by Clear Chat, Reset App, and model switching
  (`spec_v006` §10).

## 8. Chat panel controls

The chat panel hosts the composer, the pending/cancel control, the collapse/expand control, the model
selector entry point, and **Clear Chat**.

Placement rule: Clear Chat stays in the chat panel, **Reset app** stays at the viewer's top-left, and
the viewer Fit control stays at the bottom-left — three distinct actions that are never adjacent.
Their semantics are owned by `spec_v006` §10.

Panel geometry — floating card, resizable width, collapse behavior, and the stacked layout used when
the explanation panel is open — is owned by `spec_v006` §7. Inside the stack the chat drops its inline
width and drag handle; the user's stored width preference is preserved and applies again when the
stack closes.

## 9. Failure behavior

Provide explicit, recoverable chat states for: backend unavailable, LLM unavailable, query timeout or
cancellation, SQL/RAG degraded modes reported by the backend, and stale responses after a model or
reset change. Messages must be bounded and actionable, and must not expose credentials, local paths,
prompts, or provider internals (`spec_v006` §11, §13).
