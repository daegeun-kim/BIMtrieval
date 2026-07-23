"""experiment2_v4 binding: the deterministic machinery around the two LLM calls.

    ledger_v2   -> phrase-level typed requirement ledger (intent skeleton)
    recall      -> always-parallel recommendation channels + value linking
    validate_v2 -> ten-layer deterministic validation with per-part gates
    compile_v2  -> typed relational compiler over the access contract
    execute_v2  -> operation-specific execution + result variants
    packet_v2 / answer_validation_v2 / viewer_v2 -> answer packet, claim
                   validation with deterministic fallback, typed viewer sets

`spans`, `lexical`, `previous_scope`, `concept_vectors`, and `value_link` are the
supporting utilities; the typed logical algebra lives in `app.llm.schemas_v2`.
Nothing here calls an LLM or executes retrieval directly; it decides what is
executable and hands that decision to the execution layer. The Task 24/25
slate/validate/compile/execute stack was retired with the pipeline it served
(task26 §16).
"""
