# Safety Constraints (Strict)

Scope:
- Only operate within the current project root directory and postgresql database
- Do NOT read, modify, or access parent directories or external folders.

File Operations:
- Only edit files inside this repository (BIM_RAG)

Environment:
- You anaconda virtual environment 'bim_rag' for all workflow.
- Only install libraries necessary for the current spec.

General:
- Do NOT go beyond the current spec.
- Do NOT introduce additional tools, frameworks, or datasets unless requested.

# Project Instructions

Project:
BIM_RAG

Goal:
A tool development project for LLM integration for BIM information access and visualization.

Rules:
- Follow specs in /specs.
- Work one spec version at a time.
- when running, choose wisely whether the task is cpu friendly or gpu friendly. cpu: intel core ultra 9 285H, gpu: rtx 5080 laptop
- Do not implement beyond the active spec.
- Before coding, create a plan.
- After coding, run tests.
- All github actions should be done manually my the user. You do not have access
- Keep experiment outputs out of Git unless explicitly approved.
- /specs are blueprint of the project, /tasks are smaller updates, fix, and minor changes.
- after each task is performed inside /tasks, merge the content of task md into appropriate spec md file, and convert the name of task md file by adding "done". eg: (task01.md to task01_done.md)

# Writing New Task Files

When asked to create the next file in `/tasks`:

- First inspect the relevant code, current spec, and latest completed task.
- Ask a small number of focused clarification questions before writing. Ask only
  about decisions that materially change the scope or expected behavior; do not ask
  questions that can be answered from the repository.
- Treat a task file as a concise implementation brief, not a complete architecture
  document. Keep it as short as practical and normally under 200 lines unless the
  user explicitly requests a detailed specification.
- Focus on the intended outcome, the code behavior that must change, important
  constraints, and a small set of fundamental tests.
- State owner-decided requirements clearly, but leave minor implementation details
  and local code organization to the agent executing the task.
- Prefer the following sections only: intent, current problem, requirements,
  non-goals, fundamental tests, and completion condition. Omit a section when it
  adds no useful instruction.
- Do not add exhaustive test matrices, per-query acceptance tables, research
  surveys, speculative redesigns, long schemas, extensive pseudocode, or detailed
  observability/performance plans unless they are directly required by the task or
  explicitly requested.
- Do not turn a focused fix into a repository-wide redesign. If broader follow-up
  work is discovered, mention it briefly as a possible later task.
- By default, require only targeted unit/integration tests and one basic smoke test.
  The user will perform broader manual query testing before approving the next
  stage. Do not require a full billed LLM evaluation run unless explicitly asked.
- Before saving, remove duplicated rationale and any instruction that does not help
  the executing agent change or verify the code.

Commands:
- Activate env: conda activate bim_rag
- Install package: pip install -e or conda install depending on reliability
- Test: pytest
- Format: ruff format .
- Lint: ruff check .
