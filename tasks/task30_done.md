# Task 30: Separate the Frontend Specifications

## Goal

Reorganize the oversized frontend specification into smaller authoritative files without
changing product behavior.

This is documentation-only work. Do not modify code, tests, configuration, generated
files, task files, or any other non-spec file.

## Required structure

Rewrite and split the current frontend requirements into:

- `specs/spec_v006_frontend_application.md` — concise application hub covering shared
  layout, model lifecycle, state/clearing, accessibility, security, shared contracts, and
  cross-feature integration;
- `specs/spec_v008_3d_viewer.md` — viewer assets, camera/navigation, selection,
  highlighting, rendering/performance, and floor-plan mode;
- `specs/spec_v009_chat_panel.md` — conversation UI, answer rendering, request lifecycle,
  citations, and chat controls;
- `specs/spec_v010_explanation_panel.md` — eligibility, tables, charts, grouped
  relationship diagrams, viewer synchronization, and panel lifecycle;
- `specs/spec_v011_component_panel.md` — component details, preview, selection, and Same
  type/Same family behavior.

## Rules

- Preserve every current authoritative requirement and accepted decision.
- Give each rule one clear owning spec; use links for cross-feature dependencies instead of
  duplicating normative text.
- Rewrite the files as current-state specifications, not chronological implementation
  logs.
- Remove delivered-task chronology from the active frontend specs; completed task files
  remain the historical record and must not be edited.
- Keep query interpretation and backend pipeline semantics owned by the existing backend
  specifications; frontend specs should reference them rather than restate them.
- Do not create additional spec categories beyond the five files above.
- Do not rename, delete, or edit any other existing specification.
- Preserve and do not revert unrelated pre-existing workspace changes.

## Validation

Confirm that the five resulting specs collectively retain the current frontend behavior,
contain no conflicting ownership or duplicate normative rules, and that the files changed
by this task are limited to:

- the rewritten `spec_v006_frontend_application.md`;
- the four new `spec_v008`–`spec_v011` files.
