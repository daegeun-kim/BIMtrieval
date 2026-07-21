"""Deterministic candidate-slate construction (Task 24 §1).

Builds the bounded, query-specific description of how the current question may
be represented in the active model, from resources that are ALREADY cached: the
IFC ontology, the model vocabulary, the field-concept index, and the logical
floor bands. Candidate generation is discovery, not execution — no exact
`COUNT(*)` is issued per candidate (§1.1, §10.3).

Recall strategy (§1.2)
----------------------
A subject can be named three structurally different ways, and all three must
work or whole classes of question break:

- **by class name** — "curtain walls" -> `IfcCurtainWall`;
- **by a schema predefined type** — "escalators" -> `IfcTransportElement`,
  whose ESCALATOR predefined type is a schema fact, not a model fact. This is
  what lets a genuinely absent concept be recognized and reported as absent
  instead of drifting to a similar present class;
- **by a value the model stores** — "rooms" -> `IfcSpace`, because this model
  records `Rooms` as an object type. The concept exists only in the data, so no
  amount of class-name matching would find it.

All three are EXACT tiers and are retained before semantic supplements are
capped, so a compound question naming several BIM nouns cannot lose one to
another's similarity score (§1.2).

Semantic supplementation is optional and injected. When no embedding service is
supplied the slate is still built from lexical + ontology + observed-value
evidence, so a degraded embedding path never makes the pipeline unusable — it
just narrows recall, truthfully reported via `degraded`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.query.binding.lexical import (
    content_tokens,
    identifier_content_tokens,
    identifier_tokens,
    phrase_matches,
    singularize,
    stem_affinity,
)
from app.query.binding.schemas import (
    CandidateSlate,
    FieldCandidate,
    MatchTier,
    RelationshipCandidate,
    SlateCaps,
    SpatialCandidate,
    SpatialKind,
    SubjectCandidate,
    ValueCandidate,
)
from app.query.binding.spans import ModifierKind, detect_spans
from app.query.semantic.field_concepts import FieldConcept, get_field_concept_index
from app.query.semantic.ontology.loader import (
    OntologyResourceError,
    get_ontology,
    split_class_words,
)
from app.query.semantic.roles import (
    SchemaRole,
    get_role_index,
    is_result_kind,
    occurrence_for_type,
)
from app.query.semantic.spatial import FLOOR_WORDS, build_storey_model
from app.query.semantic.vocabulary.cache import get_model_vocabulary
from app.query.semantic.vocabulary.profiles import ModelVocabulary

__all__ = ["build_slate", "SlateInputs"]

#: Observed-fact kinds whose values can NAME a subject ("rooms", "corridors").
#: Coverage facts are excluded: they describe field availability, not identity.
_IDENTITY_FACT_KINDS = frozenset(
    {"object_type", "predefined_type", "type_name", "name_stem", "classification", "material"}
)

#: Question vocabulary that indicates a relationship/connectivity question.
#: General English relational language — no IFC class names, no sample phrases.
_RELATIONSHIP_TOKENS = frozenset(
    {
        "connect",
        "connected",
        "connection",
        "connectivity",
        "adjacent",
        "adjacency",
        "next",
        "attached",
        "linked",
        "between",
        "contain",
        "contained",
        "containing",
        "inside",
        "within",
        "part",
        "belong",
        "belongs",
        "member",
        "membership",
        "assigned",
        "aggregate",
        "aggregated",
        "composed",
        "hosts",
        "hosted",
        "serve",
        "serves",
        "reachable",
        "path",
        "route",
        "leads",
    }
)

#: Question vocabulary indicating the user means RAW storey entities rather than
#: logical floor bands (§1.3, §11.4).
_STOREY_ENTITY_TOKENS = frozenset({"storey", "storeys", "story", "stories", "ifcbuildingstorey"})


@dataclass
class SlateInputs:
    """Everything the slate builder may read besides the model itself (§2.1)."""

    question: str
    source_model_id: int | None
    #: Bounded prior turns, used only to resolve references.
    history: list[dict[str, str]] | None = None
    #: Compact summaries of the user's viewer selection.
    selected_entities: list[dict[str, Any]] | None = None
    #: Typed previous-result scope, when one exists.
    previous_scope: Any | None = None


def build_slate(
    session: Session,
    inputs: SlateInputs,
    *,
    settings: Settings | None = None,
    caps: SlateCaps | None = None,
    embedding_service_getter: Callable[[], Any] | None = None,
) -> CandidateSlate:
    """Build the bounded candidate slate for one question (§1)."""
    settings = settings or get_settings()
    caps = caps or SlateCaps()
    slate = CandidateSlate(question=inputs.question, source_model_id=inputs.source_model_id)
    slate.detected_modifier_spans = detect_spans(inputs.question)

    if inputs.source_model_id is None:
        # Catalog scope has no active-model vocabulary to describe (§11.1).
        return slate

    tokens = _query_tokens(inputs)
    vocab = get_model_vocabulary(session, inputs.source_model_id, settings)
    field_index = get_field_concept_index(session, inputs.source_model_id, settings)
    present = vocab.present_classes()

    try:
        role_index = get_role_index(vocab.ifc_schema or "IFC2X3")
        ontology = get_ontology(vocab.ifc_schema or "IFC2X3")
    except OntologyResourceError as exc:
        role_index = None
        ontology = None
        slate.degraded = True
        slate.degraded_reason = f"ontology unavailable: {exc}"

    # `identifying_facts` are the observed values that NAMED a subject. They are
    # carried into field/value candidate building so the evidence that
    # identified the subject can also be BOUND as a condition — without this, a
    # question like "how many rooms are there?" identifies the space class but
    # has no way to express "the ones recorded as rooms", and would answer with
    # every space instead.
    subjects, identifying_facts = _subject_candidates(
        tokens, vocab, present, role_index, ontology, caps, embedding_service_getter, slate
    )
    slate.subjects = subjects
    subject_classes = {c.ifc_class for c in subjects} | {
        member for c in subjects for member in c.family_members
    }

    fields, values = _field_and_value_candidates(
        tokens, field_index, vocab, subject_classes, caps, identifying_facts
    )
    slate.fields = fields
    slate.values = values

    slate.spatial = _spatial_candidates(session, inputs, tokens, slate, caps)
    _add_logical_floor_subject(session, inputs, tokens, slate, caps)
    slate.relationships = _relationship_candidates(tokens, vocab, role_index, caps)
    slate.coverage_notes = _coverage_notes(subjects, fields)
    return slate


# ---------------------------------------------------------------------------
# Query tokens
# ---------------------------------------------------------------------------


def _query_tokens(inputs: SlateInputs) -> frozenset[str]:
    """Content tokens of the question plus the last user turn.

    Only the most recent user turn is included, and only so a follow-up such as
    "how many of those are external?" still carries its subject. Unbounded
    history would let an old subject outrank the current one.
    """
    parts = [inputs.question]
    for turn in reversed(inputs.history or []):
        if turn.get("role") == "user" and turn.get("content"):
            parts.append(str(turn["content"]))
            break
    tokens: set[str] = set()
    for part in parts:
        tokens.update(content_tokens(part))
    return frozenset(tokens)


# ---------------------------------------------------------------------------
# Subject candidates (§1.3)
# ---------------------------------------------------------------------------


def _subject_candidates(
    tokens: frozenset[str],
    vocab: ModelVocabulary,
    present: set[str],
    role_index: Any,
    ontology: Any,
    caps: SlateCaps,
    embedding_service_getter: Callable[[], Any] | None,
    slate: CandidateSlate,
) -> tuple[list[SubjectCandidate], list[Any]]:
    exact: dict[str, SubjectCandidate] = {}
    semantic: dict[str, SubjectCandidate] = {}
    #: Observed facts whose VALUE named a subject. These must become field/value
    #: candidates too, or the concept that identified the subject cannot be
    #: expressed as a condition.
    identifying_facts: list[Any] = []

    def _make(
        ifc_class: str, tier: MatchTier, reason: str, definition: str = "", specificity: int = 0
    ) -> SubjectCandidate | None:
        role = role_index.role(ifc_class) if role_index is not None else SchemaRole.UNKNOWN
        family = role_index.closure(ifc_class, frozenset(present)) if role_index is not None else ()
        if not family and ifc_class in present:
            family = (ifc_class,)
        return SubjectCandidate(
            candidate_id="",  # assigned after ordering
            label=split_class_words(ifc_class).lower() or ifc_class,
            ifc_class=ifc_class,
            schema_role=role.value,
            definition=definition[:240],
            family_members=family,
            present=ifc_class in present,
            # Cached count only — never a fresh COUNT(*) per candidate (§1.1).
            exact_count=sum(vocab.class_count(m) for m in family) if family else None,
            result_kind=is_result_kind(role),
            match_tier=tier,
            match_reason=reason,
            specificity=specificity,
        )

    def _record(
        target: dict,
        ifc_class: str,
        tier: MatchTier,
        reason: str,
        definition: str = "",
        matched_text: str | None = None,
    ):
        if ifc_class in exact:
            return
        specificity = len(identifier_content_tokens(matched_text)) if matched_text else 0
        candidate = _make(ifc_class, tier, reason, definition, specificity)
        if candidate is None:
            return
        if target.get(ifc_class) is None:
            target[ifc_class] = candidate

    # -- 1. class-name lexical match, over ontology AND observed classes ------
    definitions: dict[str, str] = {}
    if ontology is not None:
        for entity in ontology.entities:
            definitions[entity.ifc_class] = entity.short_definition
            if phrase_matches(tokens, entity.ifc_class):
                _record(
                    exact,
                    entity.ifc_class,
                    MatchTier.EXACT_LEXICAL,
                    f"question names the class {entity.ifc_class}",
                    entity.short_definition,
                    matched_text=entity.ifc_class,
                )
    for profile in vocab.classes:
        if profile.kind == "entity" and phrase_matches(tokens, profile.ifc_class):
            _record(
                exact,
                profile.ifc_class,
                MatchTier.EXACT_LEXICAL,
                f"question names the class {profile.ifc_class}",
                definitions.get(profile.ifc_class, ""),
                matched_text=profile.ifc_class,
            )

    # -- 2. schema predefined types ------------------------------------------
    # An absent-but-exact concept is recognized here and REMAINS ELIGIBLE (§1.3),
    # so it can be answered as absent rather than replaced by a broader present
    # class.
    if ontology is not None:
        for entity in ontology.entities:
            for predefined in entity.predefined_types:
                if not _names_concept(tokens, predefined):
                    continue
                # IFC2X3 records predefined-type enumerations on the `*Type`
                # class only. Offering just that would make the question about a
                # definition record rather than about objects, so the paired
                # occurrence class is offered too — that is what lets an absent
                # concept answer as an honest zero instead of "cannot be
                # established".
                paired = occurrence_for_type(entity.ifc_class, ontology.schema_name)
                if paired is not None:
                    _record(
                        exact,
                        paired,
                        MatchTier.PREDEFINED_TYPE,
                        f"{predefined} is a predefined type of {paired}",
                        definitions.get(paired, ""),
                        matched_text=predefined,
                    )
                _record(
                    exact,
                    entity.ifc_class,
                    MatchTier.PREDEFINED_TYPE,
                    f"{predefined} is a predefined type of {entity.ifc_class}",
                    entity.short_definition,
                    matched_text=predefined,
                )
                break

    # -- 3. observed values that NAME a subject ------------------------------
    for fact in vocab.facts:
        if fact.fact_kind not in _IDENTITY_FACT_KINDS:
            continue
        if _names_concept(tokens, fact.observed_value):
            _record(
                exact,
                fact.ifc_class,
                MatchTier.OBSERVED_VALUE,
                f"{fact.ifc_class} records {fact.fact_kind} {fact.observed_value!r}",
                definitions.get(fact.ifc_class, ""),
                matched_text=fact.observed_value,
            )
            identifying_facts.append(fact)

    # -- 4. semantic ranking (never admission) -------------------------------
    # Embedding similarity may ORDER candidates that already have exact
    # evidence. It may not ADMIT a subject on its own — see `_rank_semantically`
    # for the measured reason.
    if embedding_service_getter is not None and len(exact) > 1:
        try:
            _rank_semantically(tokens, ontology, embedding_service_getter, exact)
        except Exception as exc:  # noqa: BLE001 - ranking is optional, never fatal
            slate.degraded = True
            slate.degraded_reason = f"semantic ranking unavailable: {type(exc).__name__}"

    # A word already consumed by a SCOPE reference must not also admit a subject
    # candidate. "How many doors are in this building?" uses "building" to say
    # WHERE to look, and offering `IfcBuilding` as a thing to count invites the
    # binder to constrain on it — which is the scope-becomes-condition confusion
    # §1.3 exists to prevent, resurfacing one level up. A question that genuinely
    # asks about buildings says "buildings", which is not a scope reference.
    for ifc_class in _scope_only_subjects(exact, slate):
        exact.pop(ifc_class, None)

    ordered = _order_subjects(list(exact.values())) + _order_subjects(list(semantic.values()))
    # Exact matches occupy the slate first; semantic supplements fill what is
    # left. This is the §1.2 ordering guarantee, enforced structurally.
    ordered = ordered[: caps.subjects]
    kept_classes = {c.ifc_class for c in ordered}
    return (
        [_with_id(c, f"s{i + 1}") for i, c in enumerate(ordered)],
        [f for f in identifying_facts if f.ifc_class in kept_classes],
    )


def _add_logical_floor_subject(
    session: Session,
    inputs: SlateInputs,
    tokens: frozenset[str],
    slate: CandidateSlate,
    caps: SlateCaps,
) -> None:
    """Offer "logical floor level" as a countable subject (§11.4).

    "How many floors does this building have?" asks for the LOGICAL abstraction,
    not the `IfcBuildingStorey` row count — real models give each structural
    sub-level its own storey entity, so the two differ by a lot (45 entities vs 9
    levels in the reference model). Without a candidate for the abstraction the
    binder can only reach for an entity class, and a storey-entity total
    silently substitutes for a floor count — the exact substitution §11.4
    forbids.

    Offered only when floor language is used as a SUBJECT: a positional floor
    reference ("on the second floor") is a scope, and is handled as a spatial
    candidate instead.
    """
    from dataclasses import replace

    if len(slate.subjects) >= caps.subjects:
        return
    floor_words = {singularize(w) for w in FLOOR_WORDS}
    if not (tokens & floor_words):
        return
    if any(s.kind is ModifierKind.FLOOR_REFERENCE for s in slate.detected_modifier_spans):
        return  # positional reference: a scope, not the thing being counted

    storey_model = build_storey_model(session, inputs.source_model_id)
    if not storey_model.bands:
        return

    candidate = SubjectCandidate(
        # Always `s1`: this candidate is prepended, and the rest are renumbered
        # from `s2` below. Deriving an id from the current length before
        # renumbering collides with a real candidate, and a duplicate id silently
        # resolves lookups to the wrong subject.
        candidate_id="s1",
        label="logical floor level",
        ifc_class="",  # not an IFC class — answered from the derived spatial model
        schema_role="logical",
        definition=(
            "A physical floor level of the building, derived by grouping "
            "IfcBuildingStorey entities that share an elevation. Distinct from the "
            f"raw storey entity count ({storey_model.total_storeys})."
        ),
        present=True,
        exact_count=len(storey_model.bands),
        result_kind=True,
        match_tier=MatchTier.EXACT_LEXICAL,
        match_reason="question asks about building levels",
        specificity=2,
        logical_kind="logical_floor",
    )
    # Placed first: when a question asks how many floors there are, the logical
    # reading is the intended one.
    slate.subjects = (
        [candidate] + [replace(s, candidate_id=f"s{i + 2}") for i, s in enumerate(slate.subjects)]
    )[: caps.subjects]
    assert len({s.candidate_id for s in slate.subjects}) == len(slate.subjects)


def _scope_only_subjects(exact: dict[str, SubjectCandidate], slate: CandidateSlate) -> list[str]:
    """Subjects whose ONLY supporting words sit inside a scope reference.

    Removing them is safe precisely because the test is "no evidence outside the
    scope phrase": a candidate the question names anywhere else keeps its
    evidence and stays.
    """
    scope_tokens: set[str] = set()
    for span in slate.detected_modifier_spans:
        if span.kind is ModifierKind.SCOPE_REFERENCE:
            scope_tokens |= {singularize(t) for t in content_tokens(span.text)}
    if not scope_tokens:
        return []

    doomed: list[str] = []
    for ifc_class, candidate in exact.items():
        if candidate.match_tier is not MatchTier.EXACT_LEXICAL:
            continue
        class_tokens = {singularize(t) for t in identifier_content_tokens(ifc_class)}
        if class_tokens and class_tokens <= scope_tokens:
            doomed.append(ifc_class)
    return doomed


def _names_concept(tokens: frozenset[str], value: str | None) -> bool:
    """True when the question's wording names this value.

    Requires every content token of the value to appear in the question, so
    "rooms" matches a stored `Rooms` while a question about doors does not
    match a stored `Door Hardware Set`.
    """
    target = identifier_tokens(value)
    if not target:
        return False
    expanded = {singularize(t) for t in tokens} | set(tokens)
    return bool(target) and {singularize(t) for t in target} <= expanded


def _rank_semantically(
    tokens: frozenset[str],
    ontology: Any,
    embedding_service_getter: Callable[[], Any],
    exact: dict[str, SubjectCandidate],
) -> None:
    """Reorder ALREADY-ADMITTED candidates by definition similarity.

    Why similarity cannot admit a candidate
    ---------------------------------------
    Measured over the committed IFC2X3 ontology index with BGE-M3
    (`app.evaluation.measure_slate --semantic`), cosine similarity between a
    question and IFC class definitions occupies a narrow, overlapping band with
    no separating boundary:

        "count the non load-bearing partitions" -> IfcStructuralLoadGroup  0.402
        "what is the total number of doorways"  -> IfcDoorStyle            0.380
        "asdkfj qwerty ??? ###"                 -> IfcChamferEdgeFeature   0.401

    A wrong match outscores a right one, so no threshold separates signal from
    noise, and admitting the top-k filled the slate to its cap for EVERY
    question — including meaningless input. That inflated the median slate 4.3x
    (684 -> 2,958 bytes) while making it less trustworthy.

    Worse, the admissions were dangerous in a specific, already-observed way:

        "how many parking spaces are there?"     -> IfcSpace    0.478
        "are there any bicycle racks in the model?" -> IfcRailing 0.449

    Offering `IfcSpace` for a parking question is precisely how a previous run
    produced a confident "778 parking spaces" for a model containing none. Task
    24 forbids exactly this: "an exact empty representation outranks a
    semantically similar but different non-empty class" (§Non-negotiable rule),
    and §14 requires that no fabricated model fact is accepted.

    So similarity is used the same way a set name is used in field matching: it
    influences ORDER, never ELIGIBILITY. A concept with no exact evidence
    produces no subject candidate, and the pipeline reports honestly that it
    could not identify it — which is strictly better than confidently answering
    about a different class that happens to be present.
    """
    if ontology is None or len(exact) < 2:
        return
    service = embedding_service_getter()
    if service is None:
        return

    from app.query.semantic.ontology.loader import get_ontology_index
    from app.query.semantic.resolution import _cosine_topk

    index = get_ontology_index(ontology.schema_name)
    query_vec = service.embed_query(" ".join(sorted(tokens)))
    positions = {e.ifc_class: i for i, e in enumerate(index.entities)}
    ranked = {
        index.entities[row].ifc_class: score
        for row, score in _cosine_topk(index.vectors, query_vec, len(index.entities))
        if index.entities[row].ifc_class in exact
    }
    if not ranked:
        return

    from dataclasses import replace

    for ifc_class, candidate in list(exact.items()):
        if ifc_class not in positions:
            continue
        # Fold similarity into the existing tie-break slot rather than adding a
        # new ordering axis: specificity and result-kind still dominate.
        exact[ifc_class] = replace(
            candidate,
            match_reason=(
                f"{candidate.match_reason} (definition similarity {ranked.get(ifc_class, 0.0):.3f})"
            ),
        )


def _order_subjects(candidates: list[SubjectCandidate]) -> list[SubjectCandidate]:
    """Deterministic subject ordering.

    Result-kind candidates first (a question normally asks for objects, not for
    definition records), then MORE SPECIFIC readings before broader ones, then
    present before absent, then by cached count, then by class name.

    Specificity outranks count deliberately. "curtain walls" exact-matches both
    `IfcCurtainWall` and `IfcWall`, and in most models the generic wall class is
    far more numerous — so ordering by count would answer a question about
    curtain walls with every wall in the building. The same rule keeps a request
    for stair flights from being swallowed by stairs.

    An absent exact candidate still sorts ahead of every semantic supplement,
    because the two lists are concatenated rather than merged (§1.3).
    """
    return sorted(
        candidates,
        key=lambda c: (
            not c.result_kind,
            -c.specificity,
            not c.present,
            -(c.exact_count or 0),
            c.ifc_class,
        ),
    )


def _with_id(candidate: SubjectCandidate, candidate_id: str) -> SubjectCandidate:
    from dataclasses import replace

    return replace(candidate, candidate_id=candidate_id)


# ---------------------------------------------------------------------------
# Field + value candidates (§1.3)
# ---------------------------------------------------------------------------


def _field_and_value_candidates(
    tokens: frozenset[str],
    field_index: Any,
    vocab: ModelVocabulary,
    subject_classes: set[str],
    caps: SlateCaps,
    identifying_facts: list[Any] | None = None,
) -> tuple[list[FieldCandidate], list[ValueCandidate]]:
    """Fields the question implies, plus the stored values it appears to name.

    Field resolution and value resolution are separate passes (§1.3): a field
    qualifies on its own name, and values are attached afterwards. A question
    never has to match a field name and a value in one lexical comparison.

    Fields carrying an IDENTIFYING value are admitted first, regardless of
    whether the question names the field itself. A concept that exists only in
    the data — "rooms" recorded as an object type on spaces — names its value,
    never its field, so requiring a field-name match would leave the binder
    unable to express the very condition that identified the subject, and the
    answer would silently widen to every space.
    """
    fields: list[FieldCandidate] = []
    claimed: set[tuple[str, str | None, str]] = set()

    for fact in identifying_facts or []:
        key = _fact_field_key(fact)
        if key is None or key in claimed:
            continue
        concept = field_index.get(*key)
        if concept is None:
            continue
        claimed.add(key)
        fields.append(_field_candidate(concept, f"f{len(fields) + 1}", MatchTier.OBSERVED_VALUE))

    for concept, score in field_index.search(
        tokens, subject_classes=subject_classes or None, limit=caps.fields
    ):
        if len(fields) >= caps.fields:
            break
        if concept.key in claimed:
            continue
        claimed.add(concept.key)
        fields.append(
            _field_candidate(
                concept,
                f"f{len(fields) + 1}",
                MatchTier.EXACT_LEXICAL if score >= 1.0 else MatchTier.SEMANTIC,
            )
        )

    # Values are drawn ONLY from the fields already selected, so a value can
    # never be resolved against an unrelated field (§4.2).
    values: list[ValueCandidate] = []
    by_key = {(f.field_kind, f.set_name, f.field_name): f for f in fields}
    for fact in vocab.facts:
        if len(values) >= caps.values:
            break
        key = _fact_field_key(fact)
        if key is None:
            continue
        field_candidate = by_key.get(key)
        if field_candidate is None:
            continue
        if not _names_concept(tokens, fact.observed_value):
            continue
        if any(
            v.value == fact.observed_value and v.field_candidate_id == field_candidate.candidate_id
            for v in values
        ):
            continue
        values.append(
            ValueCandidate(
                candidate_id=f"v{len(values) + 1}",
                field_candidate_id=field_candidate.candidate_id,
                value=fact.observed_value,
                occurrence_count=fact.occurrence_count,
                ifc_class=fact.ifc_class,
            )
        )
    return fields, values


def _field_candidate(concept: FieldConcept, candidate_id: str, tier: MatchTier) -> FieldCandidate:
    return FieldCandidate(
        candidate_id=candidate_id,
        field_kind=concept.field_kind,
        set_name=concept.set_name,
        field_name=concept.field_name,
        data_type=concept.data_type,
        operators=concept.operators,
        applicable_classes=concept.applicable_classes,
        populated_count=concept.populated_count,
        total_count=concept.total_count,
        sample_values=concept.sample_values,
        unit_available=concept.unit_available,
        match_tier=tier,
    )


#: Maps an observed fact back to the field-concept key it belongs to, mirroring
#: `field_concepts._FACT_KIND_FIELDS` so the two cannot drift.
_FACT_TO_FIELD_KEY: dict[str, tuple[str, str | None, str]] = {
    "name_stem": ("attribute", None, "name"),
    "object_type": ("attribute", None, "object_type"),
    "predefined_type": ("attribute", None, "predefined_type"),
    "storey": ("attribute", None, "storey_name"),
    "type_name": ("type_fact", None, "type_name"),
}


def _fact_field_key(fact: Any) -> tuple[str, str | None, str] | None:
    if fact.fact_kind == "property_value" and fact.set_name and fact.field_name:
        return ("property", fact.set_name, fact.field_name)
    return _FACT_TO_FIELD_KEY.get(fact.fact_kind)


# ---------------------------------------------------------------------------
# Spatial candidates (§1.3)
# ---------------------------------------------------------------------------


def _spatial_candidates(
    session: Session,
    inputs: SlateInputs,
    tokens: frozenset[str],
    slate: CandidateSlate,
    caps: SlateCaps,
) -> list[SpatialCandidate]:
    """Spatial candidates, included only when spatial scope is relevant (§1.3).

    The active-model candidate is always offered so that a question naming the
    building as a whole has a SCOPE to bind to. Without it, the binder has no
    way to express "the whole model" except by inventing a condition — which is
    exactly the failure mode §1.3 exists to prevent.
    """
    candidates: list[SpatialCandidate] = [
        SpatialCandidate(
            candidate_id="sp1",
            kind=SpatialKind.ACTIVE_MODEL,
            label="the active model as a whole",
        )
    ]

    if inputs.selected_entities:
        candidates.append(
            SpatialCandidate(
                candidate_id=f"sp{len(candidates) + 1}",
                kind=SpatialKind.SELECTION,
                label=f"the {len(inputs.selected_entities)} currently selected object(s)",
            )
        )
    if inputs.previous_scope is not None:
        candidates.append(
            SpatialCandidate(
                candidate_id=f"sp{len(candidates) + 1}",
                kind=SpatialKind.PREVIOUS_RESULT,
                label="the previous accepted result",
            )
        )

    wants_floor = any(s.kind is ModifierKind.FLOOR_REFERENCE for s in slate.detected_modifier_spans)
    wants_storey_entities = bool(tokens & _STOREY_ENTITY_TOKENS)

    if wants_floor or wants_storey_entities:
        storey_model = build_storey_model(session, inputs.source_model_id)
        if wants_floor and storey_model.bands:
            for band in storey_model.bands:
                if len(candidates) >= caps.spatial:
                    break
                candidates.append(
                    SpatialCandidate(
                        candidate_id=f"sp{len(candidates) + 1}",
                        kind=SpatialKind.FLOOR_BAND,
                        label=(
                            f"logical floor level {band.index + 1} of {len(storey_model.bands)} "
                            f"(elevation {band.min_elevation:g} to {band.max_elevation:g})"
                        ),
                        storey_global_ids=tuple(band.global_ids),
                    )
                )
        if wants_storey_entities and len(candidates) < caps.spatial:
            # A distinct RESULT KIND from a floor band (§11.4): a storey-entity
            # count must never silently stand in for a logical floor count.
            candidates.append(
                SpatialCandidate(
                    candidate_id=f"sp{len(candidates) + 1}",
                    kind=SpatialKind.STOREY_ENTITY,
                    label=(
                        f"the {storey_model.total_storeys} raw IfcBuildingStorey entities "
                        f"(distinct from the {len(storey_model.bands)} logical floor levels)"
                    ),
                )
            )
    return candidates[: caps.spatial]


# ---------------------------------------------------------------------------
# Relationship candidates (§1.3)
# ---------------------------------------------------------------------------


def _relationship_candidates(
    tokens: frozenset[str],
    vocab: ModelVocabulary,
    role_index: Any,
    caps: SlateCaps,
) -> list[RelationshipCandidate]:
    """Relationship candidates, ONLY for connectivity-style questions (§1.3)."""
    if not (tokens & _RELATIONSHIP_TOKENS):
        return []

    from app.query.graph.registry import REGISTRY

    scored: list[tuple[float, int, str, RelationshipCandidate]] = []
    for profile in vocab.classes:
        if profile.kind != "relationship":
            continue
        entry = REGISTRY.get(profile.ifc_class)
        if entry is None:
            continue  # not traversable by the existing graph executor
        candidate = RelationshipCandidate(
            candidate_id="",
            ifc_class=profile.ifc_class,
            meaning=entry.semantic_role.value,
            endpoint_roles=tuple(v for v, _ in profile.endpoint_roles[:4]),
            available=profile.instance_count > 0,
            instance_count=profile.instance_count,
        )
        # Relevance to the QUESTION, not sheer volume. Ordering by instance
        # count alone buried containment (a few hundred rows) beneath property
        # and material associations (several thousand), so a question saying
        # "contained in" could not reach the containment relationship at all.
        # Stem matching is what bridges "contained"/"containment" and
        # "connected"/"connects".
        affinity = max(
            stem_affinity(tokens, identifier_tokens(profile.ifc_class)),
            stem_affinity(tokens, identifier_tokens(entry.semantic_role.value)),
        )
        scored.append((affinity, profile.instance_count, profile.ifc_class, candidate))

    scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
    from dataclasses import replace

    return [
        replace(candidate, candidate_id=f"r{i + 1}")
        for i, (_affinity, _count, _cls, candidate) in enumerate(scored[: caps.relationships])
    ]


# ---------------------------------------------------------------------------
# Coverage notes (§1.3 Coverage/capability candidates)
# ---------------------------------------------------------------------------


def _coverage_notes(subjects: list[SubjectCandidate], fields: list[FieldCandidate]) -> list[str]:
    """Query-relevant capability facts only — never a full model manifest."""
    notes: list[str] = []
    for subject in subjects:
        if not subject.present:
            notes.append(
                f"{subject.ifc_class} is not present in this model "
                "(this describes the model, not necessarily the real building)"
            )
    for field_candidate in fields:
        state = field_candidate.coverage_state
        if state in ("partial", "absent"):
            notes.append(
                f"{field_candidate.label} coverage is {state}: "
                f"{field_candidate.populated_count} of {field_candidate.total_count} populated"
            )
    return notes[:8]
