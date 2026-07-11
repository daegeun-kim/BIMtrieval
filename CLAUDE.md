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

Commands:
- Activate env: conda activate bim_rag
- Install package: pip install -e or conda install depending on reliability
- Test: pytest
- Format: ruff format .
- Lint: ruff check .