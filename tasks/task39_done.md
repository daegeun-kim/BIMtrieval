# Task 39: Repository and documentation hygiene

## Goal

Remove public-facing red flags and leave a concise, professional repository structure without erasing useful technical evidence.

Shared session context and constraints are defined in Task 32. The user explicitly authorizes removal of Markdown files that look unprofessional or materially weaken the portfolio presentation.

## Work

- Review all root Markdown, `docs/`, `specs/`, and completed task Markdown from the viewpoint stated in `update_plan.md`.
- Remove obsolete, contradictory, typo-heavy, conversational, backup-like, or redundant Markdown that would be a red flag to a hiring reviewer. Consolidate valuable content into the current canonical documentation before removing duplication.
- Preserve polished architecture decisions, evaluation evidence, and specification material that demonstrates disciplined engineering. Do not keep a second public archive of files removed for lack of value.
- Establish one canonical source for shared agent/project instructions. Keep only minimal tool-specific entry files if the tools genuinely require them; eliminate parallel duplicated instructions that can drift.
- Remove stale project names, paths, commands, and superseded claims throughout remaining documentation.
- Clean up the root presentation, the obsolete shortcut, large tracked inputs, generated artifacts, and other repository-hygiene problems identified during the review. Do not rewrite Git history in this task.
- Ensure professional filenames, link targets, headings, and terminology are consistent with `BIMtrieval`.

## Validation

Run a link/path/reference check across remaining Markdown, confirm no current documentation points to removed files, and confirm the retained docs form a coherent source of truth.

