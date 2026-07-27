# Task 29: Automated Systemic v5 Debugging Loop

## Intent

Automate evaluation, diagnosis, repair, and retesting of the active
`experiment2_v5` pipeline until it reaches a good result or stops improving.

Use:

- `logs/debug_queries_v5.md` as the visible development set;
- `logs/regression_gate_v5.md` as the aggregate-only regression gate;
- `backend/app/evaluation/query_trace.jsonl` as the detailed pipeline trace.

The loop must improve general pipeline contracts. It must never optimize around an
individual question, IFC model, expected count, or recorded answer.

## Fixed evaluation sets

### Development set

Run all 15 development messages in their specified sessions and model contexts.
Claude may inspect their complete outputs and trace records.

Before changing pipeline code:

- independently audit and freeze the expected intent for every development query;
- obtain authoritative structured ground truth from the database, semantic manifest,
  spatial memberships, and relationship tables where available;
- define acceptable partial, unavailable, and clarification behavior where exact
  structured ground truth is not available;
- freeze the PASS/PARTIAL/FAIL rubric and query wording.

Do not derive expected behavior from the current v5 response, and do not change an
expectation during the loop to make a candidate pass.

### Compact regression gate

Run the eight opaque original cases selected in
`logs/regression_gate_v5.md` with the same frozen evaluator on every scored
candidate.

Claude receives only the aggregate PASS, PARTIAL, and FAIL counts. It must not inspect
the gate's new per-query answers, outcomes, traces, failure reasons, or viewer sets.
The evaluator must tag regression trace records so they are excluded from development
diagnosis.

Do not run the complete original benchmark during the debugging loop.

## Evaluation score

For a fixed query set, calculate:

```text
error_score = (2 * FAIL) + PARTIAL
```

Lower is better. Compare candidate results in this order:

1. lower combined error score across the 15 development messages and eight compact
   regression cases;
2. fewer combined FAIL results;
3. more combined PASS results.

A new candidate is accepted only when it establishes a new best combined result and
does not worsen the compact regression gate's own error score relative to the current
best checkpoint.

Maintain one best-known code checkpoint and its exact evaluation summary. A rejected
or worse candidate must not become the final version. Restore only files changed by
this task and do not use destructive repository-wide Git operations.

## Automated loop

### 1. Establish the baseline

1. Run relevant deterministic backend tests.
2. Run the complete development set and retain full detailed results.
3. Run the compact regression gate and expose only its aggregate counts.
4. Record the combined baseline score, model-call totals, provider cost, and best
   checkpoint.

Do not run the full original benchmark for this baseline.

### 2. Diagnose the first systemic loss

For every development `PARTIAL` and `FAIL`, locate the first stage where correct
information changes, disappears, or becomes unsupported:

```text
conversation and semantic intent
    -> retrieval requirements and recommendations
    -> grounded typed plan
    -> validation and gate
    -> compiler and execution
    -> evidence/result packet
    -> final text and viewer filter
```

Cluster failures by shared violated contract. Select the highest-impact root cause
that explains multiple failures or reveals a general information-transfer invariant.
Do not begin from surface wording or from the final answer alone.

### 3. Make one bounded systemic repair

Repair the stage that owns the incorrect state. A repair may update multiple files
when they implement one shared contract, but it must have one explicit systemic
hypothesis.

For every repair:

- state the invariant being repaired;
- identify the first failing stage;
- explain which downstream stages receive corrected information;
- add or update neutral synthetic contract tests;
- run focused deterministic tests before billed evaluation;
- preserve all unrelated behavior and existing user changes.

### 4. Prohibit evaluation overfitting

Never:

- compare exact query strings in application code;
- add failure wording to prompts, aliases, parsers, recommendations, or fallbacks;
- hardcode model IDs, IFC filenames, semantic IDs, values, counts, floors, or expected
  results;
- add prompt examples or demonstrations;
- create a special compiler or viewer path for one evaluation case;
- broaden or weaken validation to turn a failure into a pass;
- use final-answer prose to hide an upstream planning or execution defect;
- inspect detailed compact-regression outcomes during the loop.

Every change must be defensible as a pipeline rule without referring to an evaluation
question.

### 5. Score the candidate

After focused tests pass:

1. run all 15 development messages with their required session boundaries;
2. grade them using the frozen rubric and inspect their detailed traces;
3. run the eight-case compact regression gate;
4. expose only the regression PASS/PARTIAL/FAIL totals;
5. calculate the combined result and compare it with the best checkpoint;
6. accept and checkpoint a new best candidate, or reject it and restore the previous
   best;
7. record whether the iteration improved and why the systemic hypothesis succeeded
   or failed.

An infrastructure failure does not count as a non-improving pipeline iteration.
Resolve or retry the infrastructure stage without changing pipeline semantics.

### 6. Continue or stop

Stop successfully when:

```text
Development FAIL < 5
AND
Compact regression FAIL <= 1
```

Both thresholds must be satisfied in the same fully scored iteration. Do not stop
successfully when only one set meets its threshold. Otherwise continue from the best
checkpoint.

Stop for plateau when three consecutive fully scored candidate iterations fail to
establish an accepted new best result. Reset the plateau counter to zero whenever a
new best candidate is accepted.

Compare against the best checkpoint, not only the immediately preceding iteration.
This prevents oscillating results from appearing to improve.

At either stop condition, leave the repository at the best accepted checkpoint.

## Prompt and model constraints

- Preserve the v5 two-call cheap semantic planning design and existing grounded answer
  call.
- Keep configured model roles and reasoning settings fixed during the loop so results
  remain comparable.
- Do not add a runtime LLM judge, model router, advanced replacement model, agent loop,
  or model-written SQL.
- All active application LLM prompts remain rule-only and contain no examples.
- Claude may grade the offline development artifacts using the frozen rubric; this
  does not add an evaluator call to the application pipeline.

## Per-iteration debugging records

Create one new Markdown file in `logs/` for every fully scored debugging iteration,
including the baseline:

```text
logs/debug_v5_iteration_000.md
logs/debug_v5_iteration_001.md
logs/debug_v5_iteration_002.md
...
```

Use zero-padded sequential numbers and never overwrite, renumber, or reuse a previous
iteration file. Each file is a brief human-readable record containing:

- iteration and candidate ID;
- the systemic hypothesis and first owning stage;
- a short summary of what was changed and why;
- focused tests run and their outcome;
- development PASS/PARTIAL/FAIL;
- compact regression PASS/PARTIAL/FAIL only;
- combined error score;
- accepted or rejected status;
- plateau counter;
- LLM calls, tokens, provider cost, and latency for the iteration;
- the best checkpoint after the decision;
- the next action: continue debugging, stop successfully, or stop for plateau.

Do not include full prompts, manifests, result packets, query-by-query regression
outcomes, or detailed regression traces in these files. The permanent query trace
remains the detailed source for development queries.

## Final frozen benchmark

After either stopping condition:

1. freeze the best accepted v5 candidate;
2. run the relevant full deterministic backend suite;
3. run every original benchmark query and session sequence once;
4. generate `logs/test_query_v5.md`;
5. compare the final complete v5 result with both existing v4 reports;
6. include query-level PASS/PARTIAL/FAIL, first failing stage, authoritative result,
   final text, viewer agreement, calls, tokens, cost, and latency;
7. report the stop condition and the best development/compact-gate score.

The full benchmark is an owner-facing final comparison. Do not feed its detailed
outcomes back into Task 29 debugging. If further work is requested from those
outcomes, treat it as a later development task with a newly declared evaluation
boundary.

Do not rewrite `logs/test_query_v4.md` or
`logs/test_query_v4_revised.md`.

## Completion condition

Task 29 is complete when:

- the development and compact regression definitions remain frozen;
- the automated loop stops under one of the two stated conditions;
- every retained change repairs a systemic pipeline contract and has neutral tests;
- no evaluation question or expected result is encoded in application behavior;
- detailed compact-regression outcomes remained outside the debugging process;
- the repository is left at the best accepted checkpoint;
- the relevant deterministic suite passes at that checkpoint;
- the complete final original benchmark is recorded in
  `logs/test_query_v5.md`;
- the completion report records the stop reason, full iteration history, final
  comparison, and total provider cost.

After implementation, evaluation, and final reporting, rename `tasks/task29.md` to
`tasks/task29_done.md`.

## Owner-directed closure

The owner closed Task 29 after candidate iteration 004 because the loop still did
not demonstrate an overall improvement over the revised v4 pipeline. This is an
administrative completion, not a claim that the original success or plateau
condition was reached.

Task 29's reports and raw evaluation artifacts are archived under
`logs/task29_v5_archive/`. Candidate `v5-c004` was accepted as Task 29's final
best-known checkpoint and remains the starting code state for Task 30.

The main unresolved defect is transferred to Task 30: v5 understands conversation
context in its first LLM call, but compresses that understanding into shallow prose
fields, reinterprets the prose through lexical ledger rules, and asks the grounding
LLM to reconstruct the lost logical structure. Task 30 replaces the symptom-level
debugging approach while preserving the overall v5 architecture.
