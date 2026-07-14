"""Benchmark case schema (spec_v002 Section 21).

Reusable failure cases are stored as JSONL, one case per line, in a
versioned file (see `benchmark_v001_cases.jsonl` in this directory).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from shared.types import QueryRoute, QueryScope


class BenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    expected_scope: QueryScope
    expected_route: QueryRoute
    expected_answer_type: str
    relevant_canonical_ids: list[int] = Field(default_factory=list)
    expected_exact_count: int | None = None
    required_relationship_classes: list[str] = Field(default_factory=list)
    notes: str | None = None


def load_cases(path: Path) -> list[BenchmarkCase]:
    """Load benchmark cases from a JSONL file. Returns [] if the file is empty."""
    if not path.exists():
        raise FileNotFoundError(f"Benchmark case file not found: {path}")
    cases: list[BenchmarkCase] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(BenchmarkCase.model_validate(json.loads(line)))
    return cases
