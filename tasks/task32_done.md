# Task 32: A-range upgrade baseline and green test contract

## Shared context for Tasks 32-41

This begins one continuous ten-task upgrade session. Read `update_plan.md` before making changes and use it to evaluate the repository from the perspective of the portfolio reviewer. The goal of Tasks 32-41 is to move BIMtrieval from its recorded **B+** into the **A range** by closing the relevant evidence gaps in that document, not by adding unrelated product features.

The shared decisions below apply to every task in this session and do not need to be repeated in Tasks 33-41:

- Preserve the established ingestion, read-only backend, SQL/graph/RAG/hybrid query, and frontend architecture unless an upgrade explicitly requires a narrow change.
- Do not overengineer or expand the product beyond the portfolio-hardening goal.
- Never open, read, print, copy, or inspect the repository's `.env` file. Claude does not have permission to access it.
- Work only from documented configuration names and `.env.example` placeholders. Never place a real credential in a file, image, log, test, container layer, or command output.
- Every user supplies their own `OPENAI_API_KEY` through a local `.env`. Do not create a public shared-key demo and do not ask users to enter API keys into the browser.
- IFC import remains a local workflow because IFC files can be large. Do not add browser or public API upload.
- Default automated validation must not call OpenAI. Keep database/model/live evaluation clearly separated from fast offline checks.
- Do not push, publish, change GitHub settings, create releases, or perform other GitHub-side actions. Prepare repository files and document any final manual owner action.
- Keep documentation professional, current, and concise. Do not preserve obsolete or contradictory material merely because it already exists.
- Execute the tasks in numeric order. After completing each task, follow the repository's established task/spec integration and `_done` naming process.

## Goal

Create a trustworthy green local baseline before CI, packaging, evaluation, or presentation work is added.

## Work

- Reproduce the current ingestion, backend, frontend, and critical browser-test baselines using their intended environments.
- Resolve deterministic failures instead of accepting a known-red baseline. Determine whether each failure represents stale expectations or incorrect behavior, and preserve the intended product contract when correcting it.
- Make ingestion install and test correctly from the current `BIMtrieval` repository path without relying on an editable install that points to the former `BIM_RAG` location.
- Establish explicit fast offline commands for ingestion, backend, and frontend. Database-dependent, embedding-model, browser, and live-LLM checks must be separately named and must not silently enter the default unit-test path.
- Keep the frontend production build, typecheck, and lint clean. Keep the critical Playwright path green rather than recording a tolerated failure.
- Remove stale absolute-path assumptions from project-owned configuration or documentation when encountered. Do not alter the user's global environments beyond what is required to install this repository normally.

## Validation

Record the exact commands and final totals for:

- ingestion offline tests and Ruff;
- backend offline tests and Ruff;
- frontend unit tests, typecheck, lint, and production build;
- the repository's critical Playwright path.

Do not run a live OpenAI benchmark in this task.

