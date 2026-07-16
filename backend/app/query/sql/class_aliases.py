"""Explicit IFC entity-class expansion (tasks/task13.md §2).

IFC models a plain wall as either `IfcWall` or `IfcWallStandardCase`, so a
planner that emits the natural generic class (`IfcWall`) silently misses every
standard-case instance. This module maps a requested class to the full set of
stored classes that satisfy it.

Design rules (task13 §2):

- **Explicit and testable.** A hand-written table, never fuzzy/prefix/substring
  matching on class names — an unsafe match here would silently widen a query.
- **Unknown classes pass through untouched**, so this can never invent a class
  the planner did not ask for.
- **A specific subtype is honoured as-is.** Asking for `IfcWallStandardCase`
  returns only standard-case walls; only the generic `IfcWall` (or the
  natural-language `wall`/`walls`) widens to both. Widening an explicit subtype
  request would be wrong.

Applied centrally in `app.llm.translate` when the planner's `SqlPlan` becomes a
typed execution plan, so every entity operation (count, list, filter, aggregate,
group, missing-values) inherits it.
"""

from __future__ import annotations

from typing import Sequence

_WALL_CLASSES: tuple[str, ...] = ("IfcWall", "IfcWallStandardCase")

# Keys are normalized (lower-cased); values are the exact stored IFC class names.
# The planner is prompted to emit IFC class names, but the natural-language keys
# are accepted defensively so a plain "walls" can never silently match nothing.
_CLASS_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "ifcwall": _WALL_CLASSES,
    "wall": _WALL_CLASSES,
    "walls": _WALL_CLASSES,
}


def expand_entity_class(entity_class: str) -> tuple[str, ...]:
    """Expand one requested class to the stored classes that satisfy it.

    Unknown classes are returned unchanged (as a 1-tuple).
    """
    return _CLASS_EXPANSIONS.get(entity_class.strip().lower(), (entity_class,))


def expand_entity_classes(entity_classes: Sequence[str]) -> list[str]:
    """Expand a list of requested classes, preserving order and de-duplicating.

    An empty list means "no class filter" and is returned unchanged.
    """
    expanded: list[str] = []
    seen: set[str] = set()
    for cls in entity_classes:
        for target in expand_entity_class(cls):
            if target not in seen:
                seen.add(target)
                expanded.append(target)
    return expanded
