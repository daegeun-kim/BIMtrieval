"""Frozen evaluation sets for the Task 29 v5 debugging loop.

Two independent sets, both immutable for the duration of the loop:

- `DEV_CASES` — the 15 visible development messages of
  `logs/debug_queries_v5.md`, in their specified sessions and model contexts.
  Their full outputs and traces may be inspected during debugging.
- `GATE_CASES` — the eight opaque original cases named in
  `logs/regression_gate_v5.md`, resolved from the original benchmark
  definitions in `run_test_query_suite`. Only aggregate counts of their results
  may ever leave the gate runner.

Nothing here is read by the request path; this module exists only for the
offline evaluators.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["DevCase", "DEV_CASES", "GATE_CASE_IDS", "gate_cases"]


@dataclass(frozen=True)
class DevCase:
    case_id: str
    session: str
    model_id: int
    query: str
    #: What the frozen rubric expects, for the report header only. Never used to
    #: steer the pipeline and never sent to a model.
    expected: str
    intended_path: str = ""
    #: Case ids in the same session that must run before this one.
    follows: tuple[str, ...] = field(default_factory=tuple)


#: Verbatim from logs/debug_queries_v5.md. Wording is frozen.
DEV_CASES: list[DevCase] = [
    DevCase(
        "D01", "S01", 1,
        "Group the building elements by whether they are recorded as new or existing, "
        "and give me the count for each group.",
        "New 3168 / Existing 60",
        "SQL grouping and count",
    ),
    DevCase(
        "D02", "S02", 1,
        "For walls and slabs, compare the most common recorded building material or "
        "composite descriptions.",
        "walls IFC_baksteen_roodbruin_100mm_liggend (200 of 878); "
        "slabs IFC_breedplaat_schil_60mm (52 of 275)",
        "SQL comparison and distribution",
    ),
    DevCase(
        "D03", "S03", 1,
        "Which five construction tasks are linked to the most physical building elements, "
        "and what kinds of elements are linked to each task?",
        "Afbouw 3505, Metselwerk 825, Plaatsen scharnierkap 398, Plaatsen kozijnen 361, "
        "Stelwerk buitengevel 336, with element kinds",
        "Graph, SQL, grouping, and ranking",
    ),
    DevCase(
        "D04", "S04", 1,
        "Based only on the recorded task names, element descriptions, materials, and "
        "renovation status, explain the main renovation work represented in this model.",
        "grounded account: 60 existing vs 3168 new; Dutch trade tasks",
        "RAG with structured evidence",
    ),
    DevCase(
        "D05", "S05", 2,
        "On the first occupiable floor, show the external doors and the non-load-bearing "
        "columns, with a separate count for each.",
        "14 external doors + 48 non-load-bearing columns, both highlighted",
        "SQL compound filtering and multi-part viewer set",
    ),
    DevCase(
        "D06", "S06", 2,
        "Choose one external window on the first occupiable floor and show the opening it "
        "fills and the wall containing that opening.",
        "1 of 16 external windows + its opening + containing wall",
        "SQL sample with graph traversal",
    ),
    DevCase(
        "D07", "S07", 2,
        "Explain how fire protection is recorded for doors, windows, walls, and curtain "
        "walls, distinguishing recorded ratings from missing information.",
        "walls 720/1981 EI60; doors, windows, curtain walls record none",
        "Structured coverage with qualitative explanation",
    ),
    DevCase(
        "D08", "S08", 2,
        "Which doors are designated as emergency exits, and on which floors are they located?",
        "no emergency-exit designation is recorded",
        "SQL/RAG value evidence or accurate unavailability",
    ),
    DevCase(
        "D09", "S09", 3,
        "What type of facility does this model appear to represent? Base your conclusion "
        "only on recorded spaces, equipment, names, and descriptions.",
        "healthcare/care facility, from equipment names; spaces unnamed",
        "RAG with structured evidence and cautious inference",
    ),
    DevCase(
        "D10", "S09", 3,
        "Show me the spaces and equipment that provided the strongest evidence for that "
        "conclusion.",
        "those evidence spaces + equipment, both highlighted",
        "Conversation follow-up, evidence selection, and multi-part viewer set",
        follows=("D09",),
    ),
    DevCase(
        "D11", "S10", 3,
        "Compare the coverage and recorded thermal-transmittance values of external walls "
        "and windows.",
        "walls 1173/1578 record U-value (262 external); windows 0/131",
        "SQL comparison with partial field coverage",
    ),
    DevCase(
        "D12", "S11", 3,
        "For the doors on Level 2, identify the opening each door fills and the wall "
        "containing that opening.",
        "57 doors on Level 2; 56 fill a recorded opening",
        "Floor-scoped SQL with graph traversal",
    ),
    DevCase(
        "D13", "S12", 4,
        "Which flow terminals are connected to distribution ports, and what type or "
        "reference is recorded for each connected terminal?",
        "no flow terminal is port-connected; 7 ports attach to proxies",
        "Graph traversal with structured reporting",
    ),
    DevCase(
        "D14", "S13", 4,
        "How many doors are on the highest usable floor?",
        "clarification: First floor vs uncertain Roof floor",
        "Material floor ambiguity and clarification",
    ),
    DevCase(
        "D15", "S13", 4,
        "For this question, include the level named 'Roof floor' as usable, but exclude "
        "the separate level named 'Roof'.",
        "13 doors",
        "Conversation resolution and SQL floor scope",
        follows=("D14",),
    ),
]


#: The eight opaque cases frozen in logs/regression_gate_v5.md. Resolved from the
#: original benchmark definitions; the selection is immutable during Task 29.
GATE_CASE_IDS: tuple[str, ...] = (
    "Q8",
    "B4",
    "B7",
    "B12",
    "B19",
    "C2-followup",
    "C4",
    "C8",
)


def gate_cases():
    """The eight original `Case` objects, in the frozen order, with prerequisites.

    `C2-followup` is a second turn, so its session predecessor `C1-setup` runs
    with it; the predecessor is context, not a scored case.
    """
    from app.evaluation.run_test_query_suite import SECTIONS

    by_id = {c.case_id: c for section in SECTIONS for c in section.cases}
    scored = [by_id[case_id] for case_id in GATE_CASE_IDS]
    prerequisites = {
        case_id: [
            c
            for section in SECTIONS
            for c in section.cases
            if c.session
            and c.session == by_id[case_id].session
            and c.case_id != case_id
        ]
        for case_id in GATE_CASE_IDS
        if by_id[case_id].session
    }
    return scored, prerequisites
