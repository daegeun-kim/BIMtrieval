# Prompt file locations

Versioned prompt text lives under this directory, one subfolder per role:

```text
backend/src/llm/prompts/
├── planner/   # schema-enforced query-plan prompts (spec_v002 Section 7)
└── answer/    # grounded answer-generation prompts (spec_v002 Section 13-14)
```

Convention (to be followed once real prompt text is added, in v003/v004/v005):

```text
prompts/<role>/v001/system.md
prompts/<role>/v001/<use-case>.md
```

`<role>` is `planner` or `answer`. Each version directory is immutable once
in use; a prompt change ships as a new `vNNN` directory, not an edit in
place, so logged plans/answers remain reproducible against the prompt
version that produced them (spec_v002 Section 21).

No prompt text is added by Task 04 — only these versioned locations
(tasks/task04.md item 7: "without prematurely implementing final path
prompts").
