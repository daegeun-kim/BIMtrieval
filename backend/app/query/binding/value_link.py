"""Request-time authoritative value linking (task26 §7.4).

Resolves a user-named value against what the model actually stores, without
enumerating high-cardinality vocabularies in advance:

1. in-memory match against the manifest's enumerated/example values (covers
   frequent values with zero database work);
2. bounded authoritative SQL lookup over property sets, fixed attribute paths,
   materials, and classifications for exact / case-normalized / contains
   matches;
3. fuzzy alternatives by trigram similarity over the bounded candidates.

Every match keeps per-field provenance — a value found in one field can never
bind another (§7.4).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.query.semantic.manifest_v002.schema import Capability, ManifestV002

__all__ = ["ValueLink", "link_values"]

#: Maximum stored-value matches returned per lookup text.
MAX_MATCHES = 12
#: Maximum rows fetched per authoritative SQL probe.
SQL_ROW_CAP = 40


@dataclass(frozen=True)
class ValueLink:
    """One authoritative match between user text and a stored value."""

    capability_id: str
    stored_value: str
    occurrence_count: int
    match_kind: str  # exact | normalized | contains | fuzzy
    score: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "capability": self.capability_id,
            "stored_value": self.stored_value,
            "count": self.occurrence_count,
            "match": self.match_kind,
        }


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().casefold()


def _trigrams(value: str) -> set[str]:
    padded = f"  {_normalize(value)} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def _trigram_similarity(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# ---------------------------------------------------------------------------
# In-memory channel over manifest values
# ---------------------------------------------------------------------------


def _manifest_matches(text: str, manifest: ManifestV002) -> list[ValueLink]:
    normalized = _normalize(text)
    out: list[ValueLink] = []
    for capability in manifest.capabilities.values():
        if not capability.executable or not capability.values:
            continue
        for stored, count in capability.values:
            stored_norm = _normalize(stored)
            if stored == text:
                kind, score = "exact", 1.0
            elif stored_norm == normalized:
                kind, score = "normalized", 0.95
            elif normalized and normalized in stored_norm:
                kind, score = "contains", 0.7
            else:
                similarity = _trigram_similarity(text, stored)
                if similarity < 0.55:
                    continue
                kind, score = "fuzzy", similarity * 0.8
            out.append(
                ValueLink(
                    capability_id=capability.semantic_id,
                    stored_value=stored,
                    occurrence_count=count,
                    match_kind=kind,
                    score=score,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Bounded authoritative SQL channel
# ---------------------------------------------------------------------------

_ATTRIBUTE_EXPRS = {
    "attr:name": "canonical_json->'identity'->>'name'",
    "attr:object_type": "canonical_json->'identity'->>'object_type'",
    "attr:tag": "canonical_json->'identity'->>'tag'",
    "attr:long_name": "canonical_json->'identity'->>'long_name'",
    "attr:type_name": "canonical_json->'type'->>'name'",
    "attr:predefined_type": "canonical_json->'meta'->>'predefined_type'",
}

_WRAPPER_KEY_RE = re.compile(r"^\[(?P<ns>.*)\](?P<field>.+)$")


def _property_capability_id(container: str, field: str, manifest: ManifestV002) -> str | None:
    """Map a physical (container, field key) onto its manifest capability."""
    for candidate in (f"prop:{container}.{field}", f"qty:{container}.{field}"):
        if candidate in manifest.capabilities:
            return candidate
    match = _WRAPPER_KEY_RE.match(field)
    if match:
        wrapped = f"prop:{container}[{match.group('ns')}].{match.group('field')}"
        if wrapped in manifest.capabilities:
            return wrapped
    return None


def _sql_matches(
    session: Session, source_model_id: int, text: str, manifest: ManifestV002
) -> list[ValueLink]:
    normalized = _normalize(text)
    if len(normalized) < 2:
        return []
    out: list[ValueLink] = []

    rows = session.execute(
        sql_text(
            "SELECT ps.key, pr.key, pr.value->>'value' AS v, count(*) AS n "
            "FROM ifc_entities e, "
            "jsonb_each(e.canonical_json->'property_sets') ps, "
            "jsonb_each(ps.value) pr "
            "WHERE e.source_model_id = :sid "
            "AND jsonb_typeof(ps.value) = 'object' "
            "AND lower(pr.value->>'value') LIKE :pattern "
            "GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT :cap"
        ),
        {"sid": source_model_id, "pattern": f"%{normalized}%", "cap": SQL_ROW_CAP},
    ).fetchall()
    for container, field, value, count in rows:
        capability_id = _property_capability_id(container, field, manifest)
        if capability_id is None or value is None:
            continue
        out.append(_classified(capability_id, value, int(count), text, normalized))

    for capability_id, expr in _ATTRIBUTE_EXPRS.items():
        if capability_id not in manifest.capabilities:
            continue
        rows = session.execute(
            sql_text(
                f"SELECT {expr} AS v, count(*) AS n FROM ifc_entities "  # noqa: S608
                f"WHERE source_model_id = :sid AND lower({expr}) LIKE :pattern "  # noqa: S608
                "GROUP BY 1 ORDER BY 2 DESC LIMIT :cap"
            ),
            {"sid": source_model_id, "pattern": f"%{normalized}%", "cap": SQL_ROW_CAP},
        ).fetchall()
        for value, count in rows:
            if value is not None:
                out.append(_classified(capability_id, value, int(count), text, normalized))

    if "mat:material.name" in manifest.capabilities:
        rows = session.execute(
            sql_text(
                "SELECT m->>'name' AS v, count(*) AS n FROM ifc_entities e, "
                "jsonb_array_elements(e.canonical_json->'materials') m "
                "WHERE e.source_model_id = :sid AND lower(m->>'name') LIKE :pattern "
                "GROUP BY 1 ORDER BY 2 DESC LIMIT :cap"
            ),
            {"sid": source_model_id, "pattern": f"%{normalized}%", "cap": SQL_ROW_CAP},
        ).fetchall()
        for value, count in rows:
            if value is not None:
                out.append(_classified("mat:material.name", value, int(count), text, normalized))

    return out


def _classified(
    capability_id: str, stored: str, count: int, original: str, normalized: str
) -> ValueLink:
    stored_norm = _normalize(stored)
    if stored == original:
        kind, score = "exact", 1.0
    elif stored_norm == normalized:
        kind, score = "normalized", 0.95
    else:
        kind, score = "contains", 0.7
    return ValueLink(
        capability_id=capability_id,
        stored_value=stored,
        occurrence_count=count,
        match_kind=kind,
        score=score,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def link_values(
    session: Session | None,
    source_model_id: int,
    text: str,
    manifest: ManifestV002,
    *,
    allow_sql: bool = True,
) -> list[ValueLink]:
    """Ranked authoritative value matches for one requirement text."""
    matches = _manifest_matches(text, manifest)
    has_strong = any(m.match_kind in ("exact", "normalized") for m in matches)
    if allow_sql and session is not None and not has_strong:
        matches.extend(_sql_matches(session, source_model_id, text, manifest))

    deduped: dict[tuple[str, str], ValueLink] = {}
    for match in matches:
        key = (match.capability_id, match.stored_value)
        existing = deduped.get(key)
        if existing is None or match.score > existing.score:
            deduped[key] = match
    ranked = sorted(deduped.values(), key=lambda m: (-m.score, -m.occurrence_count, m.stored_value))
    return ranked[:MAX_MATCHES]
