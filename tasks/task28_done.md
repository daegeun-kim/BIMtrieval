# Task 28: v5 Semantic Intent and Reliable Pipeline Transfer

## Intent

Update the active v4 query pipeline to `experiment2_v5` with a small, focused
architecture change that prevents user meaning from being misinterpreted or lost
between stages.

This is a systemic repair. Do not fix individual failed questions, add special cases
for particular IFC models, or tune rules around benchmark wording.

The v5 pipeline must satisfy three end-to-end responsibilities:

1. the initial planning engine understands the user's current intention in the
   context of the complete conversation;
2. deterministic execution queries the database using the correct concepts,
   operations, relationships, scopes, and filters;
3. final interpretation produces text and visualization filters from the same
   authoritative execution results.

Preserve the existing typed plan, semantic access contracts, deterministic
compilation/execution, result states, and grounded answer design.

## Diagnostic evidence

Before implementation, read these files in full:

- `logs/test_query_v4.md`
- `logs/test_query_v4_revised.md`
- `backend/app/evaluation/query_trace.jsonl`

Use them to locate recurring losses of meaning and information at stage boundaries.
The reports and traces are diagnostic evidence, not a list of cases to patch.

Identify the first stage where the user's intended topic, target, constraint,
operation, requested output, authoritative result, or viewer identity changes or
disappears. Repair the owning contract rather than compensating downstream.

Do not copy benchmark questions, dialogue, model facts, IFC names, expected values,
or failure-specific wording into code or prompts.

## Settled v5 design

### 1. Use one semantic planning boundary implemented by two cheap LLM calls

The logical planning boundary remains one responsibility, but implement it internally
as two narrowly scoped calls:

```text
complete conversation
    -> semantic intent resolver
    -> normalized standalone request
    -> deterministic backend recommendation
    -> grounding planner
    -> validated typed plan
    -> deterministic execution
    -> grounded answer and viewer filter
```

Reuse the current cheap planning-model configuration for both planning calls. Do not
introduce an advanced planning model, model router, runtime judge, agent loop, or new
provider.

The first call resolves language and conversation state. The second call grounds the
resolved meaning against backend capabilities. Neither call writes SQL.

Keep both calls compact with small typed outputs. Record actual calls, input/output
tokens, cache use, latency, and cost so cost is evaluated per successfully answered
request, including correction or fallback work.

### 2. First call: semantic intent resolver

Move semantic interpretation before the current lexical ledger and recommendation
logic. The resolver receives:

- the current user message;
- the complete available conversation in original order;
- the active model identity and only the minimal session metadata needed to resolve
  the request;
- any pending clarification state from the preceding pipeline response.

For normal conversations, do not impose the current 20-turn selection or
400-character-per-message truncation. Pass every available turn intact. Do not add a
summarization or memory subsystem in this task. A provider hard limit must be handled
explicitly and recorded; history must never be silently dropped.

The resolver produces a compact, model-neutral semantic object containing:

- the normalized standalone request;
- the active topic and intended targets;
- requested operations and outputs;
- active scopes, filters, comparisons, groupings, and relationships;
- output and visualization intent;
- assumptions or earlier constraints that the user superseded;
- unresolved required information, if any;
- whether the current message resolves a pending clarification;
- turn provenance for the active decisions.

This object describes user meaning, not database implementation. It must not contain
invented semantic IDs, SQL, IFC facts, or backend fields that were not supplied to the
resolver.

The resolved intent becomes the authoritative interpretation for the rest of the
request. Preserve it in the query trace.

### 3. Conversation handling is stateful, not standalone reparsing

Treat the conversation and the resolved semantic object as complementary:

- the resolver uses the complete raw conversation to understand the current turn;
- it materializes the result into one authoritative standalone request;
- downstream stages use that resolved request instead of independently
  reinterpreting the transcript;
- pending clarification state and the last resolved intent must remain available to
  the next turn through the current session mechanism;
- a clarification answer updates or completes the pending intent instead of being
  parsed as an unrelated new request.

Keep this state minimal and typed. Extend the current session and trace payloads as
needed; do not add a separate memory service or database.

### 4. Ledger and recommendation become subordinate to resolved intent

The existing word-based ledger may remain as a deterministic retrieval aid and audit
artifact, but it is no longer authoritative for topic, target, or grammatical role.
It must not override the resolver by splitting a coherent concept into independent
word requirements or by converting context into filters.

Build retrieval requirements from the normalized semantic object. Recommendations
must be:

- phrase- and intent-level rather than isolated word matches;
- aware of the intended target and operation;
- compatible with backend applicability and access contracts;
- sufficiently diverse to expose materially plausible backend concepts without
  broadening the user's request.

Deterministic retrieval still owns candidate discovery. The semantic resolver does
not receive the full manifest and does not choose backend identifiers.

### 5. Second call: grounding planner

Refactor the current binder into the grounding call. It receives:

- the immutable normalized semantic request;
- its structured requirements and conversation provenance;
- the bounded backend recommendations;
- the existing compact executable capability projection.

Its only responsibility is to select supported semantic IDs and assemble the existing
typed logical plan. It must map every requested target, operation, constraint, scope,
output, and visualization request to a plan contribution or to an explicit
unsupported/ambiguous disposition.

The grounding planner must not:

- reinterpret the conversation;
- replace the requested topic with a nearby backend concept;
- silently add or remove constraints;
- treat a backend limitation as uncertainty about an otherwise clear request;
- invent fields, values, relationships, local references, or semantic IDs.

Keep the current deterministic normalization for uniquely repairable bookkeeping.
Any correction call remains limited to a proven mechanical grounding defect. It may
repair the typed plan but cannot change the resolved user intent. Do not add another
general reasoning loop.

### 6. Clarification must be justified and persistent

Ask the user only when information required to construct the intended query remains
unresolved, or when the backend exposes materially different plausible
interpretations that cannot safely be selected.

Clarification must be represented as structured unresolved slots with provenance.
The gate must verify those slots rather than trusting an unconstrained model-written
question.

Do not ask merely because:

- the request uses ordinary natural language rather than IFC terminology;
- a broad concept requires multiple backend classes or access paths;
- the backend does not record the requested fact;
- a safe supported part can already be returned;
- an earlier clarification was answered in the conversation.

When the source cannot answer a clear request, return the correct unavailable or
partial result and explain the source limitation. Do not convert source
unavailability into a clarification.

Ask only for the smallest missing decision. Persist the pending intent so the next
turn completes the same plan, and prevent repeated requests for information the user
already supplied.

### 7. Validate semantic preservation before execution

Add a deterministic boundary check between resolved intent and the grounded logical
plan. Validation must establish that:

- every required semantic component is represented by a valid plan node or explicit
  disposition;
- every selected concept is applicable to the intended target and operation;
- no requested filter, scope, relationship, grouping, output, or independent part was
  dropped;
- no narrowing filter or broader substitute was invented;
- plan-wide issues affect the relevant executable parts and cannot coexist with a
  misleading ready result;
- every compiler operation required by the plan has a supported access method.

Keep semantic meaning separate from mechanical IDs. Deterministically repair only
unique bookkeeping mistakes; never infer a different intent to make a plan
executable.

### 8. Preserve information through deterministic execution

Execution remains backend-authoritative and deterministic:

- the LLM selects only typed semantic operations;
- the compiler chooses parameterized SQL, graph, profile, RAG, or derived access
  methods already authorized by the semantic contract;
- target applicability, field coverage, relationship direction, model isolation, and
  completeness determine exact, zero, partial, ambiguous, or unavailable status;
- an exact result is never produced from an unresolved or silently broadened plan;
- an unsupported optional enrichment does not erase an otherwise valid core result;
  preserve the supported result and mark only the unsupported field as unknown;
- independent valid result parts survive failure of another part.

The execution result packet must retain stable identities and provenance for known
facts, unknown fields, limitations, result parts, and viewer-eligible entities. Do not
force the final LLM to reconstruct these relationships from prose.

### 9. Generate text and visualization from one result contract

The final answerer receives the normalized user request and authoritative execution
packet. It may explain and organize those results, but it cannot change counts,
identities, result status, relationships, or limitations.

Deterministic answer validation must reject:

- claims that contradict an authoritative result;
- statements that say a recorded answer is unavailable;
- unsupported numbers or limitations;
- unsupported certainty or absence;
- internal pipeline terminology presented to the user.

Use stable fact/result identities rather than fragile phrase matching to validate
claims. The deterministic fallback must use the same authoritative facts and
limitations.

Viewer hydration must be derived from the same requested and successfully executed
result parts used by the answer. Replace the assumption that exactly one result part
is always the visualization authority. When the user requests multiple highlightable
sets, preserve and combine all of their exact entity identities subject to the
existing viewer limit and truncation disclosure. Zero, unavailable, or
non-highlightable results must not cause an unrelated broader set to be shown.

The delivered text, result summary, viewer class counts, highlighted IDs, and
per-part trace must therefore agree.

### 10. Prompts contain rules only

All active v5 LLM prompt templates must contain declarative rules, field definitions,
and output-schema instructions only.

Do not include examples, demonstrations, sample conversations, sample queries,
sample plans, benchmark wording, expected outputs, or model-specific facts in any
resolver, grounding, correction, or answer prompt.

Prefer typed schemas and deterministic validation over longer prompt prose.

## Implementation boundary

Modify the current pipeline in place and label new traces `experiment2_v5`. Preserve
the public query API unless an additive field is required for typed conversation or
multi-part viewer provenance.

This is a focused v4 evolution:

- add one semantic resolver call before ledger/recommendation;
- reuse and narrow the current binder as the grounding planner;
- carry one typed resolved-intent object through the existing stages;
- extend the existing session, validation, trace, result, and viewer contracts only
  where required to prevent information loss.

Do not rebuild ingestion, replace the semantic manifest, create another query
endpoint, add a new database, introduce an ontology framework, or duplicate the
pipeline behind a feature flag.

## Validation

Add or update focused contract-level tests for:

- complete ordered history serialization without the existing silent truncation;
- structured resolved-intent parsing and provenance;
- pending clarification completion across turns;
- ledger/recommendation subordination to resolved intent;
- immutable intent transfer into grounding and correction;
- semantic preservation validation before compilation;
- supported core results surviving unsupported optional fields or independent parts;
- authoritative fact transfer into answer validation;
- agreement between multi-part answer results and viewer identities;
- rule-only active prompt templates.

Use neutral synthetic fixtures. Do not copy the benchmark questions or their expected
answers into tests.

Run the focused unit/integration tests and the relevant existing non-billed backend
suite. Do not create, rewrite, or run a benchmark-query evaluation or generate a
`logs/test_query_v5.md` report as part of this task.

## Non-goals

- Patching any individual failure in the diagnostic files.
- Hardcoding query strings, synonyms, model IDs, IFC filenames, semantic IDs, counts,
  or expected answers.
- Sending the full database or full manifest to the semantic resolver.
- Feeding raw conversation history to every stage after it has been resolved.
- Adding a conversation summarizer, external memory system, runtime evaluator, or
  general agent architecture.
- Allowing an LLM to generate SQL or override deterministic execution evidence.
- Changing benchmark expectations or running billed benchmark queries.
- Increasing apparent success by weakening validation or hiding unavailable data.

## Completion condition

Task 28 is complete when:

- the active pipeline is labeled `experiment2_v5`;
- complete conversation history is used by the semantic resolver without the current
  normal-path truncation;
- one typed resolved intent is preserved from interpretation through answer and
  viewer selection;
- recommendation and grounding operate on that intent rather than isolated keyword
  roles;
- clarification is backend-justified, persisted, and not repeated after resolution;
- deterministic validation proves semantic preservation before execution;
- execution preserves supported facts, unknowns, limitations, and independent parts;
- final text and visualization filters are derived from the same authoritative result
  identities;
- every active v5 LLM prompt contains rules only and no examples;
- focused non-benchmark tests pass;
- the completion report records the v5 call count and measured cost per successful
  request and maps each change to its owning pipeline boundary.

After implementation and verification, rename `tasks/task28.md` to
`tasks/task28_done.md`.
