"""Non-English normalization for the existing lexical/ledger stages (task27 §2).

A question asked in Swedish, Dutch, German, or Norwegian/Danish reaches the same
manifest as its English equivalent, because everything downstream matches on
English concept labels derived from IFC class and property names. Without a
normalization step the whole question becomes one unmatched content phrase: the
recorded defect was `Hur manga fonster finns det` producing a single ledger
TARGET with no candidate at all.

Two small, general lexicons do the work:

- `FUNCTION_WORDS` — interrogatives, determiners, copulas, and prepositions that
  shape a request in these languages but are never things to bind. They join the
  ledger's structural-word set exactly as the English ones do.
- `CONCEPT_EQUIVALENTS` — everyday nouns for the modelled artefacts (window,
  door, wall, floor, room, stair, building, material) mapped onto their English
  token. They are applied as extra *query* tokens in the recall channels and in
  validation's coverage check, so a correctly linked concept is never
  invalidated by a lexical token check in another language.

This is general vocabulary for four languages, not a per-question rule: no model
name, stored value, benchmark noun, or expected answer appears here. Diacritics
are folded before lookup, so both `fönster` and `fonster` normalize.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "CONCEPT_EQUIVALENTS",
    "FUNCTION_WORDS",
    "SCOPE_NOUNS",
    "english_equivalents",
    "expand_tokens",
    "fold",
]


def fold(value: str) -> str:
    """Diacritic-folded, case-folded form used for every lookup here."""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


#: Function words of the supported non-English languages. Same role as the
#: ledger's English structural vocabulary: they shape a request, never bind.
FUNCTION_WORDS: frozenset[str] = frozenset(
    fold(word)
    for word in """
    hur manga many mange hvor mycket vad vilka vilken vilket finns det den de dem
    ar er en ett och eller inte inga ingen nagra alla varje som har hade med utan
    pa i av till fran for over under mellan visa ge lista antal antalet totalt
    summa minst mest storst minsta hoeveel veel wat welke welk zijn is er de het
    een en of niet geen alle elke die dat met zonder op in van naar uit voor
    boven onder tussen toon geef lijst aantal totaal meest grootste kleinste
    wie viele wieviele was welche welcher welches sind ist es der die das ein
    eine und oder nicht kein keine alle jede mit ohne auf im von nach aus fuer
    ueber unter zwischen zeige gib liste anzahl gesamt insgesamt meisten
    groesste kleinste hvilke hvilken hvor mange finnes eller ikke ingen alle
    hver med uten paa fra til antall totalt vis
    """.split()
)

#: Everyday nouns for modelled artefacts -> the English token every manifest
#: label is derived from. Plural and singular surface forms are both listed
#: because these languages inflect differently from English.
_RAW_CONCEPT_EQUIVALENTS: dict[str, str] = {
    # windows
    "fonster": "window",
    "fonstret": "window",
    "fonstren": "window",
    "raam": "window",
    "ramen": "window",
    "fenster": "window",
    "vindu": "window",
    "vinduer": "window",
    # doors
    "dorr": "door",
    "dorrar": "door",
    "dorren": "door",
    "deur": "door",
    "deuren": "door",
    "tur": "door",
    "turen": "door",
    "dor": "door",
    # walls
    "vagg": "wall",
    "vaggar": "wall",
    "vaggen": "wall",
    "muur": "wall",
    "muren": "wall",
    "wand": "wall",
    "wande": "wall",
    "vegg": "wall",
    "vegger": "wall",
    # floors / storeys
    "vaning": "floor",
    "vaningar": "floor",
    "vaningen": "floor",
    "plan": "floor",
    "verdieping": "floor",
    "verdiepingen": "floor",
    "etage": "floor",
    "geschoss": "floor",
    "stockwerk": "floor",
    "etasje": "floor",
    # rooms / spaces
    "rum": "room",
    "rummet": "room",
    "rummen": "room",
    "kamer": "room",
    "kamers": "room",
    "ruimte": "room",
    "ruimten": "room",
    "raum": "room",
    "raume": "room",
    "zimmer": "room",
    "rom": "room",
    # stairs / ramps / railings
    "trappa": "stair",
    "trappor": "stair",
    "trap": "stair",
    "trappen": "stair",
    "treppe": "stair",
    "trapp": "stair",
    "ramp": "ramp",
    "rampe": "ramp",
    "rampen": "ramp",
    "racke": "railing",
    "racken": "railing",
    "rackena": "railing",
    "leuning": "railing",
    "leuningen": "railing",
    "gelander": "railing",
    # slabs / roofs / columns / beams
    "bjalklag": "slab",
    "vloer": "slab",
    "decke": "slab",
    "tak": "roof",
    "taket": "roof",
    "dak": "roof",
    "dach": "roof",
    "pelare": "column",
    "kolom": "column",
    "kolommen": "column",
    "saule": "column",
    "balk": "beam",
    "balkar": "beam",
    "balken": "beam",
    # buildings / models / materials
    "byggnad": "building",
    "byggnaden": "building",
    "byggnader": "building",
    "gebouw": "building",
    "gebouwen": "building",
    "gebaude": "building",
    "bygningen": "building",
    "bygning": "building",
    "modell": "model",
    "modellen": "model",
    "material": "material",
    "materialet": "material",
    "materialen": "material",
    "materialien": "material",
    "brandklass": "fire rating",
    "brandkrav": "fire rating",
    "brandschutz": "fire rating",
    "barande": "load bearing",
    "tragend": "load bearing",
}

CONCEPT_EQUIVALENTS: dict[str, str] = {fold(k): v for k, v in _RAW_CONCEPT_EQUIVALENTS.items()}

#: Non-English nouns naming the modelled artefact as a WHOLE. `spans.py` adds
#: these to its scope-reference vocabulary so building-wide topic language stays
#: context rather than becoming a filter, in any supported language.
SCOPE_NOUNS: tuple[str, ...] = (
    "byggnaden",
    "byggnad",
    "byggnader",
    "gebouw",
    "gebouwen",
    "gebaude",
    "gebäude",
    "bygningen",
    "bygning",
    "modellen",
    "modell",
)

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def english_equivalents(text: str) -> set[str]:
    """English tokens equivalent to the non-English words of `text`.

    Multi-word equivalents ("fire rating") contribute each of their tokens, so
    the result is always a flat token set the existing matchers can consume.
    """
    out: set[str] = set()
    for match in _WORD_RE.finditer(text or ""):
        english = CONCEPT_EQUIVALENTS.get(fold(match.group(0)))
        if english:
            out.update(english.split())
    return out


def expand_tokens(text: str, tokens: set[str]) -> set[str]:
    """`tokens` plus the English equivalents of any non-English word in `text`."""
    return set(tokens) | english_equivalents(text)
