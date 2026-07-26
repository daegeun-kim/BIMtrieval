You are correcting ONE mechanical defect in a typed logical plan you produced
for a BIM question. The complete binder projection of the active model is in
these instructions; the request input carries the original plan, the exact
validation failures, the affected requirement/node ids, the exact rejected
strings with valid replacements, and a bounded set of expanded candidates and
value matches for ONLY those failures.

Rules:

- Fix ONLY what the listed failures name. Every part and disposition marked
  `keep` in the input is valid and must be preserved exactly, unchanged.
- `invalid_fragments` names each rejected `semantic_id` and lists valid ids of
  the same node kind. Replace the rejected string with one of those ids, copied
  character for character. Re-emitting the rejected string, or inventing another
  one, fails again.
- Local `node_id` handles and disposition links are repaired for you before
  validation; you never need to fix bookkeeping. Keep handles short (`t1`, `f1`,
  `s1`, `g1`, `a1`) and never put a semantic ID in a `node_id`.
- The failures are mechanical: a missing disposition, an invalid or
  incompatible id, an omitted node, an illegal operator, an invented filter, or
  a node that failed dry compilation. Do not rethink the whole question.
- All rules from the original binding contract still apply: ids come from the
  projection, filters restrict, projections report, scope selects, coverage is
  honest, and every required requirement gets a disposition.
- If the failure cannot be fixed with the available concepts, dispose the
  affected requirement `unavailable` or `ambiguous` honestly rather than
  substituting a similar-sounding concept, and keep every other part answerable.

Return the complete corrected plan in the same schema.
