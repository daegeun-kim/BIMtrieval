# Task 37: Measured reliability and performance hardening

## Goal

Address the production-readiness gaps named in `update_plan.md` using the standardized evaluation and existing architecture, with measurable changes rather than unsupported claims.

Shared session context and constraints are defined in Task 32.

## Work

- Evaluate what already exists for retry boundaries, timeouts, degraded modes, result/query limits, read-only enforcement, structured logging, request tracing, prompt versioning, and cost/latency measurement.
- Fill only material gaps and preserve the project's defensive read-only design.
- Define realistic correctness, latency, and cost budgets in the evaluation documentation. Do not hide failures that miss them.
- Reduce clearly unnecessary prompt, model-loading, API, database, or frontend bundle overhead when it can be done without changing query meaning or weakening the viewer.
- Keep failure messages actionable and keep secrets, full prompts, and sensitive connection details out of logs.
- Add regression coverage for each behavior changed.

## Validation

Run the offline quality gates and production build. Update benchmark documentation only from valid recorded evidence; any live comparison requiring the user's key must remain an explicit owner-run step.

