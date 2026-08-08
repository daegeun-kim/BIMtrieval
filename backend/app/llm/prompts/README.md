# Versioned LLM prompts

Prompt text lives directly beside this file. `__init__.py` selects the active
versions and loads `<version>.md` by filename. The current pipeline uses:

- `binder_v003.md` for semantic binding and decomposition;
- `correction_v001.md` for the conditional corrective binding call; and
- `grounded_answerer_v002.md` for grounded answer expression.

Older prompt files remain immutable so recorded query metadata can be traced to
the exact instructions that produced it. A prompt change adds a new `vNNN`
file and updates the corresponding version constant in `__init__.py`; it does
not overwrite an existing version.
