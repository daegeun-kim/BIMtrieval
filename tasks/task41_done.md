# Task 41: Final A-range audit and release preparation

## Goal

Finish the ten-task session with evidence that the public repository addresses every modifiable BIMtrieval weakness and applicable portfolio-wide weakness extracted in `update_plan.md`.

Shared session context and constraints are defined in Task 32.

## Work

- Re-read `update_plan.md` and audit the final repository against each BIMtrieval-specific strength, weakness, prescribed fix, AI-usage finding, and applicable 30-day action.
- Test the documented clean setup, Compose workflow, local IFC import, database initialization, read-only backend, frontend, and all required offline quality gates.
- Confirm CI configuration is green by construction, benchmark evidence is traceable, README visuals and instructions are complete, and no obsolete/unprofessional documentation remains.
- Run repository hygiene and secret checks. Confirm `.env`, API keys, database credentials, large local IFC files, caches, generated artifacts, and private run outputs are not tracked.
- Add only lightweight maintenance files that materially improve a public repository, such as a concise changelog, contribution guidance, security policy, and release notes. Avoid boilerplate that adds no value.
- Prepare a clear versioned release and GitHub profile checklist: repository description, topics, website/demo media, release tag, branch protection, required CI, and pinned-project presentation.
- Do not perform GitHub-side actions. Present the exact manual owner steps after all repository work and validation are complete.

## Final evidence

Record final test/build totals, Compose smoke results, benchmark version/headline results, remaining honest limitations, changed documentation structure, and the manual GitHub actions still required. Do not assign an A grade by assertion; demonstrate the evidence intended to earn it.
