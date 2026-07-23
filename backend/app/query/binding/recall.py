"""High-recall recommendation channels + ledger model resolution (task26 §7).

For every material ledger requirement, ALL applicable channels run as
independent ranked lists — exact/normalized alias matching, identifier and
singular/plural matching, character-trigram typo matching, authoritative
stored-value linking, and dense semantic similarity — then Reciprocal Rank
Fusion combines them and structural compatibility is enforced afterwards
(§7.3). Dense retrieval is never conditional on weak lexical recall, and the
concept-embedding matrix is cached per manifest hash (§7.2).

Recommendations are advisory hints; the binder may select any compatible ID in
the complete projection. They are not retrieved evidence and never proof that
a fact exists on every entity.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.query.binding.concept_vectors import (
    embed_query_texts,
    get_concept_vector_index,
)
from app.query.binding.ledger_v2 import (
    LedgerRequirement,
    LedgerV2,
    RequirementRole,
    ResolutionState,
)
from app.query.binding.lexical import identifier_tokens, singularize
from app.query.binding.value_link import ValueLink, link_values
from app.query.semantic.manifest_v002.schema import (
    Capability,
    FloorBand,
    ManifestV002,
)
from app.query.semantic.spatial import BOTTOM_WORDS, ORDINAL_WORDS, TOP_WORDS

__all__ = ["SlotRecommendation", "RecallResult", "run_recall", "resolve_ledger"]

#: RRF constant (standard k=60 baseline; diagnostics retain raw ranks so a
#: tuned weighted fusion can be compared offline, §7.3).
RRF_K = 60

#: Advisory candidates surfaced per material requirement.
DEFAULT_PER_SLOT = 6
#: Guaranteed allocation per material slot in compound questions before any
#: global trimming (§7.5).
MIN_PER_SLOT = 2
#: Global advisory total for prompt economy only.
DEFAULT_TOTAL = 48


@dataclass(frozen=True)
class SlotRecommendation:
    """One advisory pointer for one ledger requirement (§7.5)."""

    requirement_id: str
    concept_id: str
    label: str
    use_as: str
    supported_operators: tuple[str, ...]
    applicable_subjects: tuple[str, ...]
    coverage: str
    accessor: str
    channels: tuple[str, ...]
    channel_ranks: dict[str, int]
    fused_rank: int
    executable: bool = True

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "for": self.requirement_id,
            "id": self.concept_id,
            "label": self.label,
            "use_as": self.use_as,
        }
        if self.applicable_subjects:
            payload["subjects"] = list(self.applicable_subjects[:6])
        if self.coverage:
            payload["coverage"] = self.coverage
        if not self.executable:
            payload["descriptive_only"] = True
        payload["channels"] = list(self.channels)
        return payload


@dataclass
class RecallResult:
    recommendations: list[SlotRecommendation] = field(default_factory=list)
    value_links: dict[str, list[ValueLink]] = field(default_factory=dict)
    floor_candidates: dict[str, list[str]] = field(default_factory=dict)
    floor_notes: dict[str, str] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def for_requirement(self, requirement_id: str) -> list[SlotRecommendation]:
        return [r for r in self.recommendations if r.requirement_id == requirement_id]


# ---------------------------------------------------------------------------
# Channel implementations
# ---------------------------------------------------------------------------

_MATERIAL_ROLES = frozenset(
    {
        RequirementRole.TARGET,
        RequirementRole.FILTER,
        RequirementRole.GROUP,
        RequirementRole.OUTPUT,
        RequirementRole.TRAVERSAL,
        RequirementRole.EVIDENCE_THEME,
    }
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().casefold()


def _tokens(value: str) -> set[str]:
    return {singularize(t) for t in identifier_tokens(_normalize(value))} - {"ifc", ""}


def _trigrams(value: str) -> set[str]:
    padded = f"  {_normalize(value)} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


@dataclass(frozen=True)
class _Concept:
    semantic_id: str
    label: str
    search_text: str
    kind: str
    uses: tuple[str, ...]
    operators: tuple[str, ...]
    subjects: tuple[str, ...]
    coverage: str
    accessor: str
    executable: bool
    enumerated_values: tuple[str, ...] = ()


def _concept_pool(manifest: ManifestV002) -> list[_Concept]:
    pool: list[_Concept] = []
    for capability in manifest.capabilities.values():
        coverage = ""
        if capability.applicability:
            states = {a.coverage for a in capability.applicability}
            coverage = (
                "present_complete"
                if states == {"present_complete"}
                else next(iter(states))
                if len(states) == 1
                else "mixed"
            )
        pool.append(
            _Concept(
                semantic_id=capability.semantic_id,
                label=capability.label,
                search_text=capability.search_text,
                kind=capability.kind,
                uses=capability.uses,
                operators=capability.operators,
                subjects=capability.subjects(),
                coverage=coverage,
                accessor=capability.accessor,
                executable=capability.executable,
                enumerated_values=tuple(v for v, _ in capability.values),
            )
        )
    for traversal in manifest.traversals.values():
        pool.append(
            _Concept(
                semantic_id=traversal.semantic_id,
                label=traversal.label,
                search_text=traversal.search_text,
                kind="traversal",
                uses=("traverse",),
                operators=(),
                subjects=tuple(f"cls:{c}" for c in traversal.from_classes),
                coverage="present_complete",
                accessor="relationship.member_edge",
                executable=True,
            )
        )
    for profile in manifest.profiles.values():
        pool.append(
            _Concept(
                semantic_id=profile.semantic_id,
                label=profile.label,
                search_text=profile.search_text,
                kind="derived_profile",
                uses=profile.uses,
                operators=(),
                subjects=(),
                coverage="present_complete",
                accessor=profile.accessor,
                executable=True,
            )
        )
    return pool


def _lexical_channel(text: str, pool: list[_Concept]) -> list[tuple[str, float]]:
    """Exact/normalized alias + identifier + singular/plural matching."""
    query_tokens = _tokens(text)
    normalized_query = _normalize(text)
    if not query_tokens:
        return []
    scored: list[tuple[str, float]] = []
    for concept in pool:
        concept_tokens = _tokens(concept.search_text)
        if not concept_tokens:
            continue
        if _normalize(concept.label) == normalized_query:
            scored.append((concept.semantic_id, 20.0))
            continue
        overlap = query_tokens & concept_tokens
        if not overlap:
            continue
        if concept_tokens <= query_tokens:
            # Every word of the concept's name appears in the requirement:
            # specificity (more tokens) outranks nothing else at this tier.
            scored.append((concept.semantic_id, 10.0 + len(concept_tokens)))
        else:
            scored.append(
                (concept.semantic_id, 3.0 + len(overlap) / len(concept_tokens))
            )
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:24]


def _typo_channel(text: str, pool: list[_Concept]) -> list[tuple[str, float]]:
    """Character-trigram tolerance for misspellings and joined words."""
    query_trigrams = _trigrams(text)
    if not query_trigrams:
        return []
    scored: list[tuple[str, float]] = []
    for concept in pool:
        best = 0.0
        for alias in (concept.label, *concept.search_text.split("  ")):
            alias_trigrams = _trigrams(alias)
            if not alias_trigrams:
                continue
            similarity = len(query_trigrams & alias_trigrams) / len(
                query_trigrams | alias_trigrams
            )
            best = max(best, similarity)
        if best >= 0.34:
            scored.append((concept.semantic_id, best))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:12]


def _value_channel(links: list[ValueLink]) -> list[tuple[str, float]]:
    scored: dict[str, float] = {}
    for link in links:
        scored[link.capability_id] = max(scored.get(link.capability_id, 0.0), link.score)
    ranked = sorted(scored.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:12]


def _traversal_structural_channel(
    requirement: LedgerRequirement,
    ledger: LedgerV2,
    manifest: ManifestV002,
) -> list[tuple[str, float]]:
    """Local graph-neighborhood support for relationship slots (§7.1 channel 8).

    A traversal contract is relevant when its endpoint classes lexically match
    the OTHER requirement phrases of the same answer part ("spaces connected to
    stairs" -> paths whose endpoints include space- and stair-family classes).
    """
    sibling_tokens: set[str] = set()
    for sibling in ledger.requirements:
        if (
            sibling.part_hint == requirement.part_hint
            and sibling.requirement_id != requirement.requirement_id
            and sibling.role in (RequirementRole.TARGET, RequirementRole.FILTER)
        ):
            sibling_tokens |= _tokens(sibling.source_text)

    scored: list[tuple[str, float]] = []
    for traversal in manifest.traversals.values():
        endpoint_tokens: set[str] = set()
        for ifc_class in (*traversal.from_classes, *traversal.to_classes):
            endpoint_tokens |= _tokens(ifc_class)
        overlap = len(sibling_tokens & endpoint_tokens)
        score = overlap + min(traversal.relationship_count, 1000) / 1_000_000.0
        if traversal.relationship_count > 0:
            scored.append((traversal.semantic_id, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:12]


def _fuse(channel_lists: dict[str, list[tuple[str, float]]]) -> list[tuple[str, float, dict[str, int]]]:
    """Reciprocal Rank Fusion, keeping per-channel ranks for diagnostics."""
    fused: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    for channel, ranked in channel_lists.items():
        for position, (semantic_id, _score) in enumerate(ranked, start=1):
            fused[semantic_id] = fused.get(semantic_id, 0.0) + 1.0 / (RRF_K + position)
            ranks.setdefault(semantic_id, {})[channel] = position
    ordered = sorted(fused.items(), key=lambda item: (-item[1], item[0]))
    return [(sid, score, ranks[sid]) for sid, score in ordered]


_ROLE_COMPATIBLE_USES: dict[RequirementRole, frozenset[str]] = {
    # A TARGET slot admits filter-capable concepts too: the binder decomposes a
    # phrase like "external walls" into a target node plus a filter node, and
    # the qualifier's concept must be reachable from the phrase's slot (§6.1).
    RequirementRole.TARGET: frozenset({"target", "filter"}),
    RequirementRole.FILTER: frozenset({"filter"}),
    RequirementRole.GROUP: frozenset({"group"}),
    RequirementRole.OUTPUT: frozenset({"report", "aggregate"}),
    RequirementRole.TRAVERSAL: frozenset({"traverse"}),
    RequirementRole.EVIDENCE_THEME: frozenset({"target", "topic_context"}),
}


def _use_for(concept: _Concept, role: RequirementRole) -> str | None:
    compatible = _ROLE_COMPATIBLE_USES.get(role, frozenset())
    for use in concept.uses:
        if use in compatible:
            return use
    return None


# ---------------------------------------------------------------------------
# Floor / spatial resolution (deterministic, §5.5)
# ---------------------------------------------------------------------------

_ORDINAL_SUFFIX_RE = re.compile(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\b")
_RAW_STOREY_RE = re.compile(r"\b(raw|ifc)?\s*store?y?s?\b|\bifcbuildingstorey\b", re.I)


def _extract_ordinal(text: str) -> int | None:
    lowered = text.casefold()
    for word, value in ORDINAL_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            return value
    match = _ORDINAL_SUFFIX_RE.search(lowered)
    if match:
        return int(match.group(1))
    return None


def _floor_candidates(
    requirement: LedgerRequirement, manifest: ManifestV002
) -> tuple[list[str], str, ResolutionState]:
    """Resolve one floor-reference scope against the derived bands."""
    floors = manifest.floors
    text = requirement.source_text.casefold()
    if not floors.bands:
        return [], "this model derives no floor bands", ResolutionState.NOT_REPRESENTABLE

    occupiable = floors.occupiable_bands()

    def _uncertain_neighbor_with_occupancy(band: FloorBand, above: bool) -> FloorBand | None:
        for candidate in floors.bands:
            if candidate.classification != "uncertain":
                continue
            adjacent = (
                candidate.index == band.index + 1 if above else candidate.index == band.index - 1
            )
            if adjacent and (
                candidate.evidence.get("walls", 0) > 0 or candidate.evidence.get("doors", 0) > 0
            ):
                return candidate
        return None

    if any(word in text for word in TOP_WORDS):
        band = floors.top_occupiable()
        if band is None:
            return [], "no band classifies as occupiable", ResolutionState.NOT_REPRESENTABLE
        boundary = _uncertain_neighbor_with_occupancy(band, above=True)
        if boundary is not None:
            return (
                [band.semantic_id, boundary.semantic_id],
                f"the top floor could be {band.describe()} or the uncertain {boundary.describe()}",
                ResolutionState.AMBIGUOUS,
            )
        return [band.semantic_id], f"top occupiable floor: {band.describe()}", ResolutionState.RESOLVABLE

    if any(word in text for word in BOTTOM_WORDS) and _extract_ordinal(text) is None:
        if not occupiable:
            return [], "no band classifies as occupiable", ResolutionState.NOT_REPRESENTABLE
        band = occupiable[0]
        return [band.semantic_id], f"lowest occupiable floor: {band.describe()}", ResolutionState.RESOLVABLE

    ordinal = _extract_ordinal(text)
    if ordinal is None:
        return [], f"could not read a specific floor from {requirement.source_text!r}", (
            ResolutionState.AMBIGUOUS
        )
    band = floors.band_for_ordinal(ordinal)
    if band is None:
        return (
            [],
            f"{requirement.source_text!r} is outside this model's "
            f"{len(occupiable)} occupiable floor(s)",
            ResolutionState.NOT_REPRESENTABLE,
        )
    boundary = _uncertain_neighbor_with_occupancy(band, above=False) if ordinal == 1 else None
    if boundary is not None:
        return (
            [band.semantic_id, boundary.semantic_id],
            f"floor {ordinal} could be {band.describe()} or the uncertain {boundary.describe()}",
            ResolutionState.AMBIGUOUS,
        )
    return (
        [band.semantic_id],
        f"floor {ordinal} (occupiable ordinal): {band.describe()}",
        ResolutionState.RESOLVABLE,
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def run_recall(
    session: Session | None,
    manifest: ManifestV002,
    ledger: LedgerV2,
    *,
    embedding_service_getter: Callable[[], Any] | None = None,
    per_slot: int = DEFAULT_PER_SLOT,
    total: int = DEFAULT_TOTAL,
) -> RecallResult:
    """Run every applicable channel for every material requirement."""
    started = time.perf_counter()
    result = RecallResult()
    pool = _concept_pool(manifest)
    material = [r for r in ledger.requirements if r.role in _MATERIAL_ROLES]

    # Dense channel setup: one cached concept matrix, one embed per distinct span.
    index = None
    query_vectors = None
    if embedding_service_getter is not None:
        try:
            service = embedding_service_getter()
        except Exception:  # noqa: BLE001 - dense recall degrades, never fails
            service = None
        if service is not None:
            index = get_concept_vector_index(manifest, service)
            if index is not None:
                query_vectors = embed_query_texts(
                    service, [r.source_text for r in material]
                )

    per_slot_lists: dict[str, list[SlotRecommendation]] = {}
    for requirement in material:
        channel_lists: dict[str, list[tuple[str, float]]] = {}
        channel_lists["alias"] = _lexical_channel(requirement.source_text, pool)
        channel_lists["typo"] = _typo_channel(requirement.source_text, pool)

        links = link_values(
            session,
            manifest.source_model_id,
            requirement.source_text,
            manifest,
            allow_sql=(
                session is not None
                and (
                    requirement.span_kind == "quoted_value"
                    or not channel_lists["alias"]
                )
            ),
        )
        if links:
            result.value_links[requirement.requirement_id] = links
            channel_lists["value"] = _value_channel(links)

        if index is not None and query_vectors is not None:
            vector = query_vectors.get(requirement.source_text)
            if vector is not None:
                channel_lists["embedding"] = index.rank(vector, top_k=12)

        if requirement.role is RequirementRole.TRAVERSAL:
            channel_lists["structural"] = _traversal_structural_channel(
                requirement, ledger, manifest
            )

        fused = _fuse({k: v for k, v in channel_lists.items() if v})
        per_slot_lists[requirement.requirement_id] = _to_recommendations(
            requirement, fused, pool, per_slot
        )

    result.recommendations = _apply_global_cap(per_slot_lists, total)

    # Deterministic floor/spatial resolution for scope requirements.
    for requirement in ledger.with_role(RequirementRole.SCOPE):
        if requirement.span_kind == "floor_reference":
            candidates, note, _state = _floor_candidates(requirement, manifest)
            result.floor_candidates[requirement.requirement_id] = candidates
            result.floor_notes[requirement.requirement_id] = note

    result.diagnostics = {
        "material_slots": len(material),
        "pool_size": len(pool),
        "dense_available": index is not None,
        "recall_ms": round((time.perf_counter() - started) * 1000.0, 1),
    }
    return result


def _to_recommendations(
    requirement: LedgerRequirement,
    fused: list[tuple[str, float, dict[str, int]]],
    pool: list[_Concept],
    per_slot: int,
) -> list[SlotRecommendation]:
    by_id = {c.semantic_id: c for c in pool}
    compatible: list[SlotRecommendation] = []
    incompatible: list[SlotRecommendation] = []

    for fused_rank, (semantic_id, _score, ranks) in enumerate(fused, start=1):
        concept = by_id.get(semantic_id)
        if concept is None:
            continue
        use_as = _use_for(concept, requirement.role) if concept.executable else None
        record = SlotRecommendation(
            requirement_id=requirement.requirement_id,
            concept_id=concept.semantic_id,
            label=concept.label,
            use_as=use_as or "descriptive_only",
            supported_operators=concept.operators,
            applicable_subjects=concept.subjects,
            coverage=concept.coverage,
            accessor=concept.accessor,
            channels=tuple(sorted(ranks)),
            channel_ranks=dict(ranks),
            fused_rank=fused_rank,
            executable=concept.executable and use_as is not None,
        )
        # §7.3: an executable, role-compatible concept always outranks a
        # merely-similar incompatible one, whatever the embedding said.
        (compatible if record.executable else incompatible).append(record)

    keep = compatible[:per_slot]
    if len(keep) < per_slot:
        keep.extend(incompatible[: per_slot - len(keep)])
    return keep


def _apply_global_cap(
    per_slot_lists: dict[str, list[SlotRecommendation]], total: int
) -> list[SlotRecommendation]:
    """Global prompt cap that trims low-ranked extras only after every slot
    keeps its minimum allocation (§7.5)."""
    guaranteed: list[SlotRecommendation] = []
    extras: list[SlotRecommendation] = []
    for recommendations in per_slot_lists.values():
        guaranteed.extend(recommendations[:MIN_PER_SLOT])
        extras.extend(recommendations[MIN_PER_SLOT:])
    extras.sort(key=lambda r: r.fused_rank)
    room = max(0, total - len(guaranteed))
    return guaranteed + extras[:room]


# ---------------------------------------------------------------------------
# Phase 2: ledger model resolution (§6.2)
# ---------------------------------------------------------------------------


def resolve_ledger(
    ledger: LedgerV2,
    recall: RecallResult,
    manifest: ManifestV002,
) -> None:
    """Attach candidates, resolution states, and partial policies in place."""
    targets_resolvable: dict[str, bool] = {}

    for requirement in ledger.requirements:
        if requirement.resolution is not ResolutionState.UNRESOLVED:
            continue

        if requirement.role is RequirementRole.SCOPE:
            _resolve_scope(requirement, recall)
            continue

        recommendations = [
            r for r in recall.for_requirement(requirement.requirement_id) if r.executable
        ]
        requirement.candidate_ids = [r.concept_id for r in recommendations][:8]

        if requirement.role is RequirementRole.TRAVERSAL:
            _resolve_traversal(requirement, recommendations, manifest)
            continue

        if recommendations:
            requirement.resolution = ResolutionState.RESOLVABLE
        else:
            descriptive = recall.for_requirement(requirement.requirement_id)
            if any(not r.executable for r in descriptive):
                requirement.candidate_ids = [r.concept_id for r in descriptive][:4]
                requirement.resolution = ResolutionState.NOT_REPRESENTABLE
                requirement.resolution_note = (
                    "matching concepts exist but none is executable for this use"
                )
            else:
                requirement.resolution = ResolutionState.NOT_REPRESENTABLE
                requirement.resolution_note = "no matching executable concept in this model"

        if requirement.role is RequirementRole.TARGET:
            targets_resolvable[requirement.part_hint] = (
                targets_resolvable.get(requirement.part_hint, False)
                or requirement.resolution is ResolutionState.RESOLVABLE
            )

    # Partial policies: an unresolvable FILTER on a resolvable target keeps a
    # safe contextual base set; an unresolvable OUTPUT metric has none (§6.5).
    for requirement in ledger.requirements:
        if requirement.resolution is not ResolutionState.NOT_REPRESENTABLE:
            continue
        if requirement.role is RequirementRole.FILTER and targets_resolvable.get(
            requirement.part_hint
        ):
            requirement.partial_policy = "return_base_set_as_context_only"
        elif requirement.role is RequirementRole.OUTPUT:
            requirement.partial_policy = "no_safe_result"


def _resolve_scope(requirement: LedgerRequirement, recall: RecallResult) -> None:
    if requirement.span_kind == "floor_reference":
        candidates = recall.floor_candidates.get(requirement.requirement_id, [])
        note = recall.floor_notes.get(requirement.requirement_id, "")
        requirement.candidate_ids = candidates
        requirement.resolution_note = note
        if not candidates:
            requirement.resolution = (
                ResolutionState.AMBIGUOUS
                if "could not read" in note
                else ResolutionState.NOT_REPRESENTABLE
            )
        elif len(candidates) > 1:
            requirement.resolution = ResolutionState.AMBIGUOUS
        else:
            requirement.resolution = ResolutionState.RESOLVABLE
        return
    # Inherited / selection scopes resolve by construction.
    requirement.resolution = ResolutionState.RESOLVABLE


def _resolve_traversal(
    requirement: LedgerRequirement,
    recommendations: list[SlotRecommendation],
    manifest: ManifestV002,
) -> None:
    relationship_classes = {
        manifest.traversals[r.concept_id].relationship
        for r in recommendations
        if r.concept_id in manifest.traversals
    }
    if not relationship_classes:
        requirement.resolution = ResolutionState.NOT_REPRESENTABLE
        requirement.resolution_note = (
            "no recorded relationship in this model matches this connection language"
        )
        return
    generic = requirement.source_text.casefold().strip() in {
        "connected to",
        "connects to",
        "connect to",
        "adjacent to",
        "next to",
    }
    if generic and len(relationship_classes) > 1:
        requirement.resolution = ResolutionState.AMBIGUOUS
        requirement.resolution_note = (
            "several recorded relationship kinds could mean 'connected': "
            + ", ".join(sorted(relationship_classes)[:4])
        )
        return
    requirement.resolution = ResolutionState.RESOLVABLE
