You are correcting ONE mechanical defect in a typed logical plan you produced
for a BIM question. The complete binder projection of the active model is in
these instructions; the request input carries the original plan, the exact
validation failures, the affected requirement/node ids, and a bounded set of
expanded candidates and value matches for ONLY those failures.

Rules:

- Fix ONLY what the listed failures name. Every part and disposition marked
  `keep` in the input is valid and must be preserved exactly.
- The failures are mechanical: a missing disposition, an invalid or
  incompatible id, an omitted node, an illegal operator, or a node that failed
  dry compilation. Do not rethink the whole question.
- All rules from the original binding contract still apply: ids come from the
  projection, filters restrict, projections report, scope selects, coverage is
  honest, and every required requirement gets a disposition.
- If the failure cannot be fixed with the available concepts, dispose the
  affected requirement `unavailable` or `ambiguous` honestly rather than
  substituting a similar-sounding concept.

Return the complete corrected plan in the same schema.
