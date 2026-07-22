"""Lexical + value normalization (Task 24 §4.1, §4.2, §13.3).

Offline: pure text handling, no DB / ontology / embedding / OpenAI.

Per §13.3 the same mechanism is proven on several UNRELATED BIM fields and
classes, and per §13.6 several cases are paraphrases that appear nowhere in
`specs/test_query.md`. No test asserts an expected model count.
"""

from __future__ import annotations

import pytest

from app.query.binding.lexical import (
    STOP_WORDS,
    content_tokens,
    identifier_content_tokens,
    identifier_tokens,
    normalize_text,
    phrase_matches,
    singularize,
    split_identifier,
    token_overlap,
)
from app.query.binding.values import (
    MatchKind,
    is_numeric_value,
    normalize_value,
    parse_boolean,
    parse_number,
    resolve_value,
)

# ---------------------------------------------------------------------------
# Identifier tokenization — the §4.1 "exporter naming to ordinary wording" link
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("IsExternal", ["is", "external"]),
        ("LoadBearing", ["load", "bearing"]),
        ("FireRating", ["fire", "rating"]),
        ("OverallWidth", ["overall", "width"]),
        ("ThermalTransmittance", ["thermal", "transmittance"]),
        ("AcousticRating", ["acoustic", "rating"]),
        ("Pset_WallCommon", ["pset", "wall", "common"]),
        ("Qto_SlabBaseQuantities", ["qto", "slab", "base", "quantities"]),
        ("IfcWallStandardCase", ["wall", "standard", "case"]),
        ("IfcDoor", ["door"]),
        ("snake_case_field", ["snake", "case", "field"]),
        ("kebab-case-field", ["kebab", "case", "field"]),
    ],
)
def test_split_identifier_covers_exporter_naming_styles(identifier, expected):
    assert split_identifier(identifier) == expected


def test_ifc_prefix_is_dropped_so_class_and_plain_noun_share_a_token():
    assert "door" in split_identifier("IfcDoor")
    assert "ifc" not in split_identifier("IfcDoor")


def test_identifier_tokens_include_singular_forms():
    tokens = identifier_tokens("Qto_SlabBaseQuantities")
    assert "quantities" in tokens
    assert "quantity" in tokens


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("IsExternal", ["external"]),
        ("HasCoverings", ["coverings"]),
        ("CanBeOpened", ["opened"]),
        ("LoadBearing", ["load", "bearing"]),
    ],
)
def test_grammatical_boolean_prefixes_are_stripped_for_matching(identifier, expected):
    """Regression guard for a defect this suite caught during implementation.

    Exporters prefix booleans grammatically (`IsExternal`, `HasCoverings`), but
    `is`/`has`/`can`/`be` are function words that a question never contains
    ("how many external windows"). Matching on raw tokens therefore made EVERY
    `Is*`/`Has*` boolean property permanently unreachable. Both sides must be
    compared on content tokens.
    """
    assert identifier_content_tokens(identifier) == expected


def test_identifier_of_only_function_words_does_not_become_an_empty_target():
    """An empty target would match every question. Fall back to raw tokens."""
    assert identifier_content_tokens("IsA") != []
    assert not phrase_matches(frozenset({"door"}), "IsA")


@pytest.mark.parametrize("identifier", ["", None])
def test_split_identifier_handles_empty_input(identifier):
    assert split_identifier(identifier) == []


# ---------------------------------------------------------------------------
# Surface normalization
# ---------------------------------------------------------------------------


def test_normalize_text_folds_case_punctuation_and_whitespace():
    assert normalize_text("  Fire-Rating:  EI60! ") == "fire rating ei60"


def test_normalize_text_folds_diacritics_both_directions():
    """A question typed without diacritics must reach an accented stored value.

    Uses Swedish and Dutch forms, matching the two real corpus models' languages
    without encoding anything about either model.
    """
    assert normalize_text("fönster") == normalize_text("fonster")
    assert normalize_text("Bjälklag") == normalize_text("Bjalklag")
    assert normalize_text("ongewapend béton") == normalize_text("ongewapend beton")


@pytest.mark.parametrize(
    ("plural", "singular"),
    [
        ("doors", "door"),
        ("windows", "window"),
        ("rooms", "room"),
        ("spaces", "space"),
        ("storeys", "storey"),
        ("quantities", "quantity"),
        ("properties", "property"),
        ("boxes", "box"),
        ("classes", "class"),
        ("children", "child"),
    ],
)
def test_singularize_general_morphology(plural, singular):
    assert singularize(plural) == singular


@pytest.mark.parametrize("word", ["glass", "gas", "status", "axis", "is", "class"])
def test_singularize_does_not_corrupt_singular_words_ending_in_s(word):
    """`glass` must not become `glas` — that would break material matching."""
    assert singularize(word) == word


def test_content_tokens_drops_function_words_and_singularizes():
    tokens = content_tokens("How many doors are there in the building?")
    assert "door" in tokens
    assert "building" in tokens
    assert not (set(tokens) & STOP_WORDS)


def test_stop_words_contain_no_domain_nouns():
    """Guards the generalization rule: removing a BIM noun here would be a
    query-specific rule disguised as a stop word (§Non-negotiable rule)."""
    domain_nouns = {
        "door",
        "window",
        "wall",
        "space",
        "room",
        "floor",
        "storey",
        "level",
        "building",
        "column",
        "beam",
        "slab",
        "roof",
        "stair",
        "ramp",
        "material",
        "type",
        "external",
        "internal",
        "bearing",
        "rating",
    }
    assert not (STOP_WORDS & domain_nouns)


# ---------------------------------------------------------------------------
# Token matching
# ---------------------------------------------------------------------------


def test_token_overlap_scores_against_the_target_field_size():
    """A short field name fully named by a long question must score 1.0."""
    query = frozenset(content_tokens("which walls have a fire rating of EI60"))
    assert token_overlap(query, identifier_tokens("FireRating")) == 1.0


def test_token_overlap_is_zero_for_an_unrelated_field():
    query = frozenset(content_tokens("which walls have a fire rating"))
    assert token_overlap(query, identifier_tokens("ThermalTransmittance")) == 0.0


@pytest.mark.parametrize(
    ("question", "identifier"),
    [
        ("how many external windows does the building have", "IsExternal"),
        ("are these walls load bearing", "LoadBearing"),
        ("what is the fire rating", "FireRating"),
        # Paraphrases that appear nowhere in specs/test_query.md (§13.6).
        ("list every load-bearing member", "LoadBearing"),
        ("do any partitions carry a fire rating value", "FireRating"),
        ("anything marked external on this level", "IsExternal"),
    ],
)
def test_phrase_matches_recognizes_ordinary_wording_of_a_field(question, identifier):
    """This is the general mechanism replacing a phrase->field table (§4.1)."""
    assert phrase_matches(frozenset(content_tokens(question)), identifier)


def test_phrase_matches_requires_every_identifier_token():
    """Partial overlap is not an exact lexical match — `FireRating` must not be
    claimed by a question that only says "rating"."""
    assert not phrase_matches(frozenset(content_tokens("what rating is this")), "FireRating")


# ---------------------------------------------------------------------------
# Value resolution (§4.2)
# ---------------------------------------------------------------------------


def test_exact_stored_value_wins():
    m = resolve_value("EI60", ["EI30", "EI60", "EI90"])
    assert m is not None and m.stored_value == "EI60"
    assert m.match_kind is MatchKind.EXACT


def test_case_and_punctuation_insensitive_match():
    m = resolve_value("ei60", ["EI60"])
    assert m is not None and m.stored_value == "EI60"
    assert m.match_kind is MatchKind.NORMALIZED
    assert m.is_exact_identity


@pytest.mark.parametrize(
    ("user", "stored"),
    [
        ("Room", "Rooms"),
        ("rooms", "Room"),
        ("Space", "Spaces"),
        ("corridor", "Corridors"),
    ],
)
def test_singular_plural_stored_values_match_either_direction(user, stored):
    """§4.2 morphology. Proven on several unrelated values so it is a general
    rule and not one stored value's special case."""
    m = resolve_value(user, [stored])
    assert m is not None and m.stored_value == stored
    assert m.match_kind is MatchKind.MORPHOLOGICAL


@pytest.mark.parametrize(
    ("user", "stored"),
    [("yes", "TRUE"), ("true", ".T."), ("1", "true"), ("no", "FALSE"), ("n", ".F.")],
)
def test_boolean_and_ifc_logical_spellings_are_equivalent(user, stored):
    m = resolve_value(user, [stored])
    assert m is not None and m.stored_value == stored
    assert m.match_kind is MatchKind.BOOLEAN


def test_quoted_exactness_refuses_a_merely_similar_value():
    """§4.2: 'exact quoted values preserved when the user requests exactness'."""
    assert resolve_value("D2 ny", ["d2 NY"], exact_required=True) is None
    assert resolve_value("D2 ny", ["D2 ny"], exact_required=True) is not None


def test_contains_is_off_by_default_and_opt_in():
    """Substring matching silently widens a result set, so it must be requested."""
    assert resolve_value("ny", ["D2 ny"]) is None
    m = resolve_value("ny", ["D2 ny"], allow_contains=True)
    assert m is not None and m.match_kind is MatchKind.CONTAINS


def test_unmatched_value_returns_none_rather_than_a_weak_guess():
    """The caller must report it unresolved — never silently drop the condition
    so a broader query can run (§2.4)."""
    assert resolve_value("EI120", ["EI30", "EI60"]) is None


def test_value_is_only_matched_against_the_supplied_vocabulary():
    """§4.2 forbids resolving a value against unrelated fields. The function has
    no access to any other field's values by construction; this pins that."""
    assert resolve_value("EI60", []) is None
    assert resolve_value("EI60", ["Concrete", "Steel"]) is None


def test_stronger_rungs_take_precedence_over_weaker_ones():
    m = resolve_value("Rooms", ["Rooms", "Room"])
    assert m is not None and m.match_kind is MatchKind.EXACT and m.stored_value == "Rooms"


def test_normalize_value_reduces_ifc_logical_literals():
    assert normalize_value(".T.") == "t"
    assert parse_boolean(".TRUE.") is True
    assert parse_boolean(".F.") is False
    assert parse_boolean("maybe") is None


# ---------------------------------------------------------------------------
# Numeric + unit parsing (§4.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "magnitude", "unit"),
    [
        ("1 metre", 1.0, "m"),
        ("1m", 1.0, "m"),
        ("900mm", 900.0, "mm"),
        ("2.5 meters", 2.5, "m"),
        ("2,5 m", 2.5, "m"),
        ("90 degrees", 90.0, "degrees"),
        ("-3 m", -3.0, "m"),
        ("42", 42.0, None),
    ],
)
def test_parse_number_reads_magnitude_and_unit(text, magnitude, unit):
    parsed = parse_number(text)
    assert parsed is not None
    assert parsed == (magnitude, unit)


def test_parse_number_returns_none_for_non_numeric_text():
    assert parse_number("wide") is None
    assert parse_number("") is None
    assert parse_number(None) is None


@pytest.mark.parametrize("value", ["30", "-3", "2.5", "2,5", " 42 "])
def test_is_numeric_value_accepts_whole_numbers_only(value):
    assert is_numeric_value(value)


@pytest.mark.parametrize("value", ["EI30", "M12", "D2 ny", "Type 3", "1 metre", "", None])
def test_is_numeric_value_rejects_values_that_merely_contain_a_number(value):
    """Regression guard for a defect this suite caught during implementation.

    Type inference used the substring parser, so categorical codes like `EI30`
    were typed numeric and offered comparison operators they cannot honour.
    `parse_number` still searches — that is correct for user wording — so the
    two functions must stay distinct.
    """
    assert not is_numeric_value(value)
    if value:
        assert parse_number(value) is not None or not any(ch.isdigit() for ch in value)
