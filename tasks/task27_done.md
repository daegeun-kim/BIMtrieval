# Task 27: Repair v4 Stage Boundaries and User-Facing Answers

## Intent

Improve the PASS/PARTIAL/FAIL ratio of the existing `experiment2_v4` query pipeline by
repairing errors at the stage that owns them. Preserve the current architecture, typed
logical plans, deterministic execution, and LLM roster.

Accuracy is the priority. Do not make a downstream stage compensate for incorrect
upstream state or weaken validation merely to allow more plans through.

## Current problem

Before changing code, read these files in full:

- `logs/test_query_v4.md`
- `backend/app/evaluation/query_trace.jsonl`

Use the v4 terminal records to identify the first failing stage for every benchmark
FAIL or PARTIAL. The benchmark report gives the user-visible outcome; the trace is the
authority for the ledger, recommendations, binder/correction output, validation,
physical plan, results, answer packet, final answer, and viewer set.

The observed failures are not all binder-model failures. They include incorrect ledger
roles, target-incompatible recommendations, malformed IDs, disposition/node-reference
errors, missing compiler operations, duplicate unresolved requirements, and unsupported
or overly technical final prose.

Do not patch exact benchmark wording, model IDs, expected counts, or IFC filenames.
Implement reusable stage invariants and test them with unrelated paraphrases.

## Requirements

### 1. Preserve the current operating contract

- Keep binder `gpt-5.4-nano` at medium reasoning, correction `gpt-5.4-nano` at high
  reasoning, and answerer `gpt-5.4-mini` at low reasoning.
- Do not add an LLM call, agent loop, router, judge, model-written SQL, retrieval store,
  or new framework.
- Normal answered queries remain two LLM calls; one correction remains the maximum.
- Keep the compact complete binder projection and current USD request budget.
- Do not change benchmark expectations or verdicts merely to improve the ratio. Report
  separately when an existing expectation conflicts with the adopted occupiable-floor
  semantics or audited database evidence.

### 2. Repair ledger construction and recall

Keep ledger construction deterministic and fix the general parsing rules that caused
the recorded failures:

- coordinated peer subjects requested as one total must remain peer targets in one
  union, not a target plus a filter;
- coordinated independent counts must receive separate part hints and targets;
- a qualifier phrase already represented by a resolved field/value filter must not
  also become an unavailable duplicate requirement;
- sample-detail language must produce one sample operation, one occurrence target,
  limit one, and requested report fields; verbs such as “pick” and nouns such as
  “details” must not become occurrence targets;
- building-wide topic language must remain context rather than a filter;
- common non-English count, building-context, and IFC-object terms must be normalized
  through the existing recall design so lexical token checks do not invalidate a
  correctly linked concept.

Rank filter recommendations jointly with the likely target. A field applicable to the
likely target must rank ahead of same-named fields for incompatible classes. Investigate
why v4 traces report `dense_available=false` and restore the existing intended dense
channel if it is a wiring/configuration defect; do not introduce a new embedding model
or retrieval system.

For model facts represented through authoritative names, categories, materials, or
classifications rather than a dedicated IFC class, allow the existing value-linking
stage to propose a typed target-plus-filter plan. Do not hardcode a benchmark noun.

### 3. Make binder output easy for the current LLM to produce correctly

Keep the binder prompt concise and explicit. It must clearly distinguish:

- `semantic_id`: an exact ID copied from the projection or recommendation;
- `node_id`: a short local handle such as `t1`, `f1`, `s1`, `g1`, or `a1`;
- disposition `node_ids`: exact references to those local handles;
- `part_id`: the ledger-provided part identity, unique per independent result.

The binder must never use a label, request phrase, invented alias, or truncated semantic
ID as a `semantic_id`. Bare occurrence targets must not receive an invented property
presence filter. OR conditions, unions, samples, grouped extrema, and compound counts
must use the existing algebra.

Prefer removing fragile LLM bookkeeping over adding prompt prose. Generate local node
IDs deterministically after binding, or deterministically normalize them before
validation, where this can be done without guessing semantic intent. If the LLM still
supplies node IDs, make their short-handle rule and disposition linkage unmistakable.

The binder prompt may use a small number of schema-generic structural examples, but
must not copy benchmark questions, model facts, or expected answers. End the prompt
with a short mechanical self-check for exact semantic IDs, unique part IDs, valid local
node references, and complete required dispositions.

The correction stage must preserve valid parts and repair only the named defect. Supply
the exact invalid fragment and bounded valid replacements. Perform uniquely determined
bookkeeping repairs in code instead of spending the correction call on them.

### 4. Repair validation without weakening it

Validation must accept a semantically valid plan when provenance is mechanically clear,
while continuing to reject a dropped requested condition, invented narrowing filter,
incompatible field, or silently broadened target.

- Union members contribute to the requirements they represent.
- A disposition referencing a valid logical node must not fail lexical coverage merely
  because the user used an inflection, synonym, or another supported language.
- A resolved field/value filter must discharge the complete qualifier phrase it
  represents; do not retain a duplicate unavailable fragment.
- All filter provenance checks must use actual normalized local node IDs.
- Duplicate part IDs and harmless local-ID mistakes may be normalized only when the
  intended one-to-one mapping is unique. Ambiguous repairs must still fail safely.
- Do not turn unresolved constraints into exact zero or execute a broader base set as
  though it answered the requested condition.

### 5. Fill only the demonstrated execution and evidence gaps

Implement the smallest reusable fixes required by the v4 traces:

- support a material-name distribution over the existing material array accessor,
  including correct coverage and viewer semantics;
- expose or execute a derived occupiable-floor count directly instead of making the
  binder enumerate floor-band IDs in a union;
- make thematic profile evidence retrieve relevant structured subjects and bounded
  text for themes such as circulation, rather than returning only the generic building
  profile with an empty evidence scope;
- fix the catalog query to use the actual `ifc_source_models` schema instead of assuming
  a nonexistent display-name column.

Do not add a general ontology, new database, or special compiler path for one question.

### 6. Make final answers grounded and understandable

Update `grounded_answerer_v002` using rules only. The final answerer prompt must contain
no examples.

By default, answers must:

- lead with the direct result in ordinary language;
- use “this model” rather than “the packet” or internal pipeline terminology;
- avoid `target class`, `targeted class`, `match`, `matches`, `zero match`,
  `predicate`, `coverage`, `semantic ID`, and internal exact/partial status labels;
- humanize property names such as `FireRating` unless the user explicitly asks for the
  IFC property;
- describe exact absence as no such objects being present in the model;
- describe incomplete property data as what is recorded for some objects and what
  remains unknown for the others;
- distinguish “no value is recorded” from proof that the real-world property is false;
- use technical BIM terms only when the user used them or they are necessary to avoid
  ambiguity;
- omit limitations and caveats when an exact result has no recorded limitation.

Strengthen deterministic answer validation so every factual or limitation-bearing
sentence is supported by the cited packet item. Reject an answer that adds uncertainty
to an exact result, sets `disclosed_limitation` without a packet limitation, or says
information was not provided when the packet contains the answer. The deterministic
fallback must follow the same plain-language rules.

## Non-goals

- Changing any configured LLM, reasoning effort, or model role.
- Replacing the v4 architecture or typed logical algebra.
- Enlarging the binder projection or restoring the duplicated v3 candidate universe.
- Weakening correctness gates to increase the apparent pass rate.
- Adding exact-query fallbacks, expected-count rules, or model-specific behavior.
- Rewriting `logs/test_query_v4.md` or the permanent trace as part of the implementation.
- Adding examples to the final answerer prompt.

## Fundamental tests

Add focused tests for the repaired invariants:

1. coordinated peer targets, independent compound counts, merged qualifier/value
   requirements, sample-detail parsing, and non-English normalization;
2. target-compatible recall ranking and the configured dense-channel availability;
3. short local node IDs, exact semantic-ID copying, union/OR/sample plan shapes, unique
   part IDs, and deterministic disposition linkage;
4. validation accepting a valid target/filter/scope and union contribution while still
   rejecting dropped qualifiers, invented filters, and ambiguous repairs;
5. material distribution compilation, direct occupiable-floor counting, thematic
   evidence with non-empty relevant scope, and the catalog query against the real schema;
6. answer validation rejecting unsupported caveats and technical internal wording, with
   plain-language deterministic fallbacks for exact, zero, partial, and unavailable
   results.

Use paraphrased or synthetic fixtures rather than exact benchmark questions. Run the
targeted unit/integration tests and one basic no-provider pipeline smoke test. Do not run
the full billed 42-query evaluation without the user’s explicit approval.

## Completion condition

The task is complete when the targeted tests pass, the existing relevant backend suite
remains green, and the completion report maps each repaired behavior to its owning stage
and identifies any remaining benchmark failures without hiding them behind broader
answers. Merge the durable behavior into the appropriate query-pipeline specification
and rename this file to `task27_done.md` only after implementation and verification.
