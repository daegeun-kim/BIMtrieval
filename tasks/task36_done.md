# Task 36: Standardized evaluation and benchmark publication

## Goal

Turn the existing query specs, evaluation code, and recorded results into a standardized, organized benchmark that repository viewers can understand and reproduce.

Shared session context and constraints are defined in Task 32.

## Work

- Establish one canonical evaluation structure for versioned cases, runner/configuration, machine-readable results, and a human-readable report.
- Clearly identify dataset/model, benchmark version, query categories, scoring rules, route/mode, run date, and LLM model for every published result.
- Report accuracy by query type and make SQL, graph, RAG, and hybrid behavior easy to compare where the existing evaluation supports those routes.
- Include grounding/hallucination results, honest failure cases, latency distribution, token usage, and cost when those measurements exist.
- Do not invent, backfill, or silently reinterpret metrics. Preserve historical results with their original context and distinguish them from the current benchmark.
- Keep the README summary concise and clear. Create a separate professional benchmark Markdown report when the detailed tables and failure analysis are too large for the README.
- Provide reproducible offline and owner-run live commands. Claude must not access `.env` or call OpenAI during this task.

## Validation

Confirm that published tables can be traced to versioned machine-readable results, calculations are reproducible, links are valid, and the README states the final headline results without overstating them.

