# Task 30: Repair v5 Semantic Transfer and Resume Systemic Debugging

## Intent

Continue from the accepted Task 29 `experiment2_v5` code state. Preserve the overall
pipeline structure, but repair the contract that transfers user meaning from the
conversation-aware resolver into retrieval, grounding, validation, execution, final
text, and the viewer.

This task must produce a real systemic change. Do not continue Task 29's pattern of
normalizing one phrase shape, expanding one lexical detector, or weakening one
validation check. Find where correct information first becomes weaker, changes role,
loses an association, or disappears, and repair that owning boundary across all
affected modules.

Use the two-call cheap planning design. The first call understands the conversation;
the second grounds a preserved semantic plan against the active model. The grounded
answer call remains unchanged in responsibility. No application prompt may contain
benchmark examples.

## Required historical understanding

Before coding, read the current query blueprint in
`specs/spec_v005_hybrid_query_orchestration.md`, the intent, architecture, and
completion/limitation sections of `tasks/task25_done.md` through
`tasks/task29_done.md`, and the human-readable Task 29 iteration reports in
`logs/task29_v5_archive/`. Do not inspect archived `_gate_detail_*.json` or
`_gate_trace_*.jsonl`.

Carry these lessons forward:

- **v3 / Task 25:** introduced complete model-specific semantic manifests and
  high-recall constraint-guided retrieval because small candidate slates omitted
  valid model concepts. Preserve complete semantic coverage; never make a narrow
  recommendation list the only selectable universe.
- **v4 / Tasks 26-27:** added a continuous semantic access contract, phrase-level
  ledger, typed logical algebra, deterministic validation and execution, continuous
  tracing, result states, and answer/viewer agreement. Preserve these safety
  properties. Its remaining weakness was that lexical planning still interpreted
  intent before sufficient conversation-level semantic understanding.
- **v5 / Task 28:** added a full-history semantic resolver followed by a cheap
  grounding call so user intention would be decided before backend binding. Preserve
  this direction. The implementation failed because the resolver output is too
  shallow and prose-heavy, so downstream stages reinterpret its words and lose the
  resolver's meaning.
- **Task 29:** showed that phrase cleanup can move scores but cannot remove the
  architectural ceiling. Relaxing token coverage allowed unsafe qualifier
  substitution, while expanding lexical recognition helped some language and hurt
  other cases. Its final accepted `v5-c004` checkpoint removed one false preservation
  check but still scored 0 PASS / 3 PARTIAL / 12 FAIL on development. Do not mistake
  a valid local validation repair for the missing semantic-transfer repair.

The full conversation reaching the resolver is not the main current defect. The loss
occurs after resolution. Do not solve it by sending raw history to every later stage,
where it could be interpreted differently again.

## Current core problem

The current resolver mainly transfers an operation plus natural-language target,
output, and constraint strings. `build_ledger_from_intent` then converts those strings
into `source_text` requirements. The same text is used as:

1. the record of what the user requires;
2. the retrieval key for model capabilities; and
3. the basis of lexical coverage validation.

Some typed resolver decisions are also reclassified by lexical span detection. The
grounding LLM must therefore reconstruct logical structure from a damaged ledger
while searching a capability projection that can exceed tens of thousands of tokens.
Validation catches much of the damage, so most failed development requests stop
before authoritative execution.

The core invariant is:

> Every material decision established from the conversation must retain its type,
> associations, Boolean structure, provenance, requiredness, and viewer intent until
> it is either satisfied by executed evidence or explicitly classified as ambiguous
> or unsupported.

## Requirements

### 1. Establish a stage-by-stage loss map before changing code

Create the new Task 30 iteration `000` from the current code without semantic changes.
For every development PARTIAL or FAIL, compare adjacent stages and record the first
incorrect state:

```text
conversation
  -> resolved semantic obligations
  -> retrieval obligations and candidates
  -> grounded logical plan
  -> validation disposition
  -> compiled and executed evidence
  -> result facts and entity identities
  -> final text and viewer identities
```

Do not diagnose from final prose alone. At every boundary ask:

- Did the downstream stage receive every decision it needs?
- Did a target, constraint, relationship, grouping, ordering, or output change type?
- Did independent targets become one phrase, or did one qualified target split into
  unrelated requirements?
- Did required information become advisory or disappear?
- Is the downstream stage being asked to infer something the previous stage already
  knew?

Cluster failures by their first violated contract. The iteration `000` report must
contain the loss map totals and identify the highest-impact boundary before any repair
is implemented.

### 2. Make resolved intent a typed, model-neutral semantic contract

Extend the v5 resolved-intent schema only as far as needed to preserve:

- independent and coordinated target sets;
- operation and requested outputs;
- scopes and typed property/value/comparison constraints;
- relationship endpoints, direction, and required traversal meaning;
- Boolean grouping and negation;
- grouping, ordering, and limits;
- exact, qualitative, relationship, or mixed evidence requirements without choosing
  backend IDs or writing a physical route;
- which result parts are requested for visualization;
- acceptable partial behavior; and
- turn provenance for every material decision.

The resolver must remain model-neutral. It may not invent semantic IDs, fields,
values, IFC facts, SQL, access paths, or model-specific assumptions.

### 3. Transfer typed obligations without reinterpreting prose

Build the ledger and logical plan skeleton deterministically from typed intent.
Preserve stable intent handles through every stage.

Separate these concepts in the runtime contract:

- **semantic obligation:** what must be answered or explicitly disposed;
- **retrieval hints:** text or concepts used only to discover backend candidates;
- **satisfaction proof:** the selected capability/node, executed evidence, or explicit
  unsupported/ambiguous disposition that discharges the obligation.

Natural-language text may remain for provenance, recall, and user-facing explanation,
but it must not determine a role already supplied by typed intent. Do not call
`detect_spans`, token coverage, or phrase-shape logic to reclassify a typed slot.

Every required intent handle must map one-to-one to an obligation or to an explicit,
auditable typed decomposition. No output or condition may silently become advisory.

### 4. Narrow the grounding LLM's responsibility

Construct answer parts, Boolean structure, relationship shape, grouping, ordering,
limits, and viewer-part membership before the grounding call. The grounding LLM
should select valid backend semantic IDs and authorized access capabilities for those
slots, or explicitly report that a slot cannot be grounded.

Give each slot deterministic high-recall candidates while retaining a compact
complete escape path so v3's candidate-omission problem does not return. Do not send
duplicated full projections when a smaller lossless representation is available.

Keep the configured cheap model initially. A larger model may not be used to hide an
ambiguous or lossy contract. Evaluate model capacity only after the typed transfer is
proven and the remaining task is mechanical backend binding.

### 5. Validate semantic obligations, not wording

Validation must prove that every required intent handle is represented by a valid
plan contribution or an honest explicit disposition. Lexical coverage may remain a
diagnostic signal, but it may not be the authority for whether typed meaning survived.

Do not weaken applicability, value ownership, unit, Boolean, scope, relationship,
source-model, evidence-coverage, or absence-proof validation. Task 29 iteration 002
demonstrated that ignoring an ungrounded qualifier creates confident wrong answers.

Detect genuinely unsupported logical operations before asking the grounding model to
improvise. Extend the existing typed algebra/compiler only when the missing operation
is general, deterministic, and supported by authoritative backend evidence.

### 6. Preserve result, answer, and viewer identity

Each result part must carry stable intent provenance, structured fact identifiers,
status/limitations, and its complete viewer-eligible entity set. Final text and viewer
filters must be derived from the same accepted result parts. Multi-part visualization
means the union of every requested highlightable part, subject to the existing viewer
limit and explicit truncation disclosure.

### 7. Make the debugging method enforce the architecture

One candidate may update several modules when they implement one continuous transfer
contract. Do not artificially limit a systemic repair to one function.

Reject a proposed repair before implementation when its justification depends on:

- wording from an evaluation query;
- adding a synonym, regex, phrase normalizer, or prompt wording for one semantic
  category;
- weakening validation so an invalid plan executes;
- making final prose conceal an earlier failure; or
- asking a downstream LLM to reinterpret information that should be typed upstream.

For every candidate, state the invariant, first failing boundary, information added or
preserved, downstream consumers, and neutral contract tests.

## Fundamental tests

Add compact model-neutral tests for:

- lossless handle/provenance transfer from resolved intent through obligations and
  the deterministic plan skeleton;
- coordinated targets versus qualified single targets;
- relationship endpoints and direction;
- Boolean constraints, grouping, ordering, and limits;
- mixed structured/semantic evidence requirements;
- explicit unsupported and partial dispositions without dropped constraints;
- paraphrase-invariant roles without benchmark wording;
- agreement among executed result parts, grounded facts, and viewer unions; and
- grounding context size and schema adherence using the configured cheap model.

Run focused deterministic tests before every billed evaluation. Preserve the existing
v4 contract, compiler, safety, source isolation, and regression suites.

## Restarted debugging loop

Use the replaced top-level files:

- `logs/debug_queries_v5.md` — visible 15-message development set;
- `logs/debug_v5_expectations.md` — frozen authoritative expectations;
- `logs/regression_gate_v5.md` — eight-case aggregate-only gate.

Restart reports and raw artifacts at iteration `000`; Task 29 files remain archived.
For each fully scored iteration create `logs/debug_v5_iteration_NNN.md` with the loss
hypothesis, changed contract, tests, development and aggregate gate counts, combined
score, cost/tokens/latency, accepted state, plateau counter, and next action.

Claude may inspect complete development results and traces. It may see only aggregate
PASS/PARTIAL/FAIL totals for the compact gate and must never inspect archived or new
gate detail files.

Use Task 29's score and checkpoint rules. A candidate is accepted only when it creates
a new best combined result without worsening the best gate error score. If a candidate
would be accepted or rejected solely because of one new gate run, repeat the blind
gate once with identical code/settings and use the worse aggregate result. This
confirmation is only for checkpoint decisions, not every iteration.

Stop successfully only when:

```text
Development FAIL < 5
AND
Compact regression FAIL <= 1
```

Otherwise stop after three consecutive fully scored candidates fail to establish an
accepted new best. Leave the repository at the best accepted checkpoint.

After stopping, run the relevant deterministic suite and the full frozen original
benchmark once, generating `logs/test_query_v5.md`. Do not use that final benchmark to
continue Task 30 debugging.

## Non-goals

- Rebuilding ingestion, the semantic manifest, database schemas, or the frontend.
- Returning to broad evidence collection followed by final-LLM selection.
- Model-written SQL, a runtime judge, an agent/tool loop, a new retrieval store, or a
  third planning call.
- Replacing the cheap planning model before fixing the transfer contract.
- Encoding development or regression questions, facts, or expected values in code,
  prompts, aliases, or tests.
- Adding examples to any active LLM prompt.

## Completion condition

Task 30 is complete when:

- traces prove typed intent decisions survive into obligations, plan nodes, results,
  and viewer parts without lexical reclassification;
- the grounding LLM performs backend binding rather than reconstructing user logic;
- validation is obligation/provenance based and remains strict;
- neutral tests cover the repaired transfer contract;
- the restarted loop reaches the success or plateau condition;
- the repository is left at the best accepted checkpoint;
- every Task 30 iteration is recorded without exposing compact-gate details; and
- the final original benchmark and v3/v4/v5 comparison are recorded.

After completion, merge the durable architecture into the appropriate specification
and rename this file to `tasks/task30_done.md`.
