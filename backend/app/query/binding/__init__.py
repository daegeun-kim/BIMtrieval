"""Task 24 model-aware semantic binding.

Deterministic machinery that runs *around* the two principal LLM calls:

    slate      -> the bounded, query-specific candidate slate (LLM call 1 input)
    schemas    -> typed candidate + binding records
    lexical    -> text/identifier normalization and token matching
    values     -> value normalization against a field's own value vocabulary
    spans      -> detected modifier spans and scope-vs-condition typing
    closure    -> IFC semantic closure of a bound subject
    validate   -> binding validation before any authoritative query runs

Nothing in this package calls an LLM or executes a retrieval; it decides *what*
is executable and hands that decision to the execution layer.
"""
