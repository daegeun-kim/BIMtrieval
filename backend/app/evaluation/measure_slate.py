"""Candidate-slate size and build-time measurement (Task 24 §10.2, §10.5).

Reports, per question: slate build time, serialized slate size, an estimated
prompt-token count, and the per-type candidate counts against their caps.

Read-only against the database. **Makes no OpenAI call and incurs no billed
spend** — the slate is built entirely from cached ontology/vocabulary/field
resources, which is the property §10.3 requires ("no per-question full
canonical-JSON scan", "avoid rebuilding or embedding the model vocabulary per
question").

Run from `backend/`:

    python -m app.evaluation.measure_slate
    python -m app.evaluation.measure_slate --models 2 --json

The question set deliberately mixes two groups:

- **acceptance** — questions drawn from `specs/test_query.md`, so slate sizes
  can be compared against the runs recorded there;
- **paraphrase** — unrelated rewordings written for this harness, so a slate
  that only behaves for the recorded wording is visible as a size/recall
  divergence between the two groups (§13.6).

Neither group is used to produce a production rule; this module is measurement
only and nothing in the request path imports it.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass

from app.db.session import session_scope
from app.query.binding.schemas import SlateCaps
from app.query.binding.slate import SlateInputs, build_slate

#: (group, question). Kept small and representative rather than exhaustive: the
#: full live suite belongs to a later checkpoint, this is a size/latency probe.
QUESTIONS: tuple[tuple[str, str], ...] = (
    # -- simple exact counts -------------------------------------------------
    ("acceptance", "how many doors are in this building?"),
    ("paraphrase", "what is the total number of doorways in the model?"),
    ("acceptance", "how many walls are in this building?"),
    ("paraphrase", "give me a wall count for the whole project"),
    # -- filtered ------------------------------------------------------------
    ("acceptance", "show me all the doors in the second floor"),
    ("paraphrase", "list the columns on level 4"),
    ("acceptance", "which walls have a fire rating of EI60?"),
    ("paraphrase", "do any partitions carry a fire rating value"),
    ("acceptance", "how many walls are not load bearing?"),
    ("paraphrase", "count the non load-bearing partitions"),
    ("acceptance", "how many external windows does the building have?"),
    ("paraphrase", "anything marked external on this level"),
    # -- value-named subjects ------------------------------------------------
    ("acceptance", "how many rooms are there in this building?"),
    ("paraphrase", "how many toilets are in this building?"),
    # -- absent concepts -----------------------------------------------------
    ("acceptance", "how many escalators are in this building?"),
    ("acceptance", "how many parking spaces are there?"),
    ("paraphrase", "are there any bicycle racks in the model?"),
    # -- quantities / unavailable -------------------------------------------
    ("acceptance", "show me all doors wider than 1 metre"),
    ("acceptance", "what is the u-value of the external walls?"),
    # -- spatial abstractions ------------------------------------------------
    ("acceptance", "how many floors does this building have?"),
    ("paraphrase", "how many storey entities are recorded?"),
    # -- compound ------------------------------------------------------------
    (
        "acceptance",
        "how many doors, windows and stairs are there, and which floor has the most doors?",
    ),
    ("paraphrase", "give me counts of slabs and beams, and the largest space"),
    # -- relationship --------------------------------------------------------
    ("acceptance", "which spaces are connected to the stairs?"),
    ("paraphrase", "what is contained in each storey?"),
    # -- qualitative / summary ----------------------------------------------
    ("acceptance", "describe the circulation of this building."),
    ("acceptance", "give me a summary of this building."),
    # -- degenerate ----------------------------------------------------------
    ("acceptance", "asdkfj qwerty ??? ###"),
)

#: A crude but stable characters-per-token estimate for compact JSON. Reported
#: as an ESTIMATE; actual prompt tokens are recorded per role at request time
#: once the binder is wired in (§10.2 "log serialized prompt sizes and actual
#: prompt/completion tokens by role").
_CHARS_PER_TOKEN = 4.0


@dataclass
class Measurement:
    source_model_id: int
    group: str
    question: str
    build_ms: float
    payload_bytes: int
    estimated_tokens: int
    counts: dict[str, int]
    degraded: bool

    def as_dict(self) -> dict:
        return {
            "source_model_id": self.source_model_id,
            "group": self.group,
            "question": self.question,
            "build_ms": self.build_ms,
            "payload_bytes": self.payload_bytes,
            "estimated_tokens": self.estimated_tokens,
            "degraded": self.degraded,
            **{f"n_{k}": v for k, v in self.counts.items()},
        }


def measure(
    source_model_id: int, caps: SlateCaps | None = None, semantic: bool = False
) -> list[Measurement]:
    """Measure slate size/latency for every question against one model.

    `semantic=True` enables the §1.2 embedding supplement, which loads the
    BGE-M3 query encoder. That is a real cost and a real recall gain; measuring
    both ways is how the trade-off gets decided with evidence rather than
    assumption.
    """
    getter = None
    if semantic:
        from app.query.rag.embedding_service import get_embedding_service

        getter = get_embedding_service

    results: list[Measurement] = []
    with session_scope() as session:
        for group, question in QUESTIONS:
            started = time.perf_counter()
            slate = build_slate(
                session,
                SlateInputs(question=question, source_model_id=source_model_id),
                caps=caps,
                embedding_service_getter=getter,
            )
            build_ms = round((time.perf_counter() - started) * 1000.0, 1)
            payload = json.dumps(
                slate.to_prompt_payload(), ensure_ascii=False, separators=(",", ":")
            )
            results.append(
                Measurement(
                    source_model_id=source_model_id,
                    group=group,
                    question=question,
                    build_ms=build_ms,
                    payload_bytes=len(payload.encode("utf-8")),
                    estimated_tokens=int(len(payload) / _CHARS_PER_TOKEN),
                    counts=slate.size_report(),
                    degraded=slate.degraded,
                )
            )
    return results


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def summarize(results: list[Measurement], caps: SlateCaps) -> dict:
    by_group: dict[str, list[Measurement]] = {}
    for row in results:
        by_group.setdefault(row.group, []).append(row)

    def _stats(rows: list[Measurement]) -> dict:
        return {
            "n": len(rows),
            "median_bytes": int(_percentile([r.payload_bytes for r in rows], 0.5)),
            "max_bytes": max((r.payload_bytes for r in rows), default=0),
            "median_est_tokens": int(_percentile([r.estimated_tokens for r in rows], 0.5)),
            "max_est_tokens": max((r.estimated_tokens for r in rows), default=0),
            "median_build_ms": round(_percentile([r.build_ms for r in rows], 0.5), 1),
            "max_build_ms": max((r.build_ms for r in rows), default=0.0),
        }

    over_cap = [
        {"question": r.question, "counts": r.counts}
        for r in results
        if r.counts["subjects"] > caps.subjects
        or r.counts["fields"] > caps.fields
        or r.counts["values"] > caps.values
        or r.counts["spatial"] > caps.spatial
        or r.counts["relationships"] > caps.relationships
    ]
    return {
        "overall": _stats(results),
        "by_group": {group: _stats(rows) for group, rows in sorted(by_group.items())},
        "over_cap": over_cap,
        "degraded": [r.question for r in results if r.degraded],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models", type=int, nargs="+", default=[1, 2], help="source model ids to measure"
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="enable the embedding supplement (loads BGE-M3; still no OpenAI call)",
    )
    args = parser.parse_args()

    caps = SlateCaps()
    all_results: list[Measurement] = []
    for source_model_id in args.models:
        all_results.extend(measure(source_model_id, semantic=args.semantic))

    if args.json:
        print(
            json.dumps(
                {
                    "rows": [r.as_dict() for r in all_results],
                    "summary": summarize(all_results, caps),
                },
                indent=2,
            )
        )
        return 0

    header = (
        f"{'model':>5} {'group':>10} {'bytes':>7} {'~tok':>6} {'ms':>7}  "
        f"{'sub':>3} {'fld':>3} {'val':>3} {'spa':>3} {'rel':>3}  question"
    )
    print(header)
    print("-" * len(header))
    for row in all_results:
        c = row.counts
        print(
            f"{row.source_model_id:>5} {row.group:>10} {row.payload_bytes:>7} "
            f"{row.estimated_tokens:>6} {row.build_ms:>7.1f}  "
            f"{c['subjects']:>3} {c['fields']:>3} {c['values']:>3} "
            f"{c['spatial']:>3} {c['relationships']:>3}  {row.question[:56]}"
        )
    print()
    print(json.dumps(summarize(all_results, caps), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
