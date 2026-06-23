"""Relevance matching: keep only listings that really are the target model.

Two problems this solves:
  * accessories ("battery grip", "charger", "strap" ...) showing up for a body;
  * wrong models ("Sony A7 II" / "Canon EOS 1300D" leaking into "A7 III" /
    "EOS R6" results).

Matching is done on a normalised (alphanumeric + spaces, lowercased) version of
the title using *word-boundary* regexes, so roman numerals behave correctly
(e.g. ``\\bii\\b`` does NOT match "iii", and ``\\ba7\\b`` does NOT match "a7r").
"""

from __future__ import annotations

import re

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# Accessory / parts keywords excluded for *every* target. Kept deliberately
# conservative (grips/batteries/chargers are the usual noise) to avoid
# discarding genuine bodies that merely "come with a strap".
DEFAULT_EXCLUDE = [
    "grip",
    "battery grip",
    "battery",
    "batteries",
    "baterie",
    "baterii",
    "acumulator",
    "charger",
    "incarcator",
    "cargador",
    "ladegerat",
    "ladegeraet",
    "strap",
    "curea",
    "correa",
    "hood",
    "parasolar",
    "lens hood",
    "adapter ring",
    "screen protector",
    "folie",
    "tempered glass",
    "remote",
    "telecomanda",
    "only box",
    "box only",
    "doar cutie",
    "for parts",
    "piese",
    "spare parts",
]


def normalize(text: str | None) -> str:
    """Lowercase and reduce to alphanumeric tokens separated by single spaces."""
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def _term_present(norm_title: str, term: str) -> bool:
    t = normalize(term)
    if not t:
        return False
    return re.search(r"\b" + re.escape(t) + r"\b", norm_title) is not None


def term_matches(norm_title: str, term: str) -> bool:
    """A term may list alternatives separated by ``|`` (any-of semantics)."""
    return any(_term_present(norm_title, alt) for alt in str(term).split("|"))


# Generic tokens that carry no model-distinguishing information.
_STOPWORDS = {
    "the", "and", "for", "with", "body", "only", "kit", "camera", "aparat",
    "foto", "mirrorless", "dslr", "gehause", "gehaeuse", "nou", "noua",
    "como", "nuevo", "como nuevo", "ca", "noi", "stare",
}


def auto_include_terms(query: str, min_len: int = 2) -> list[str]:
    """Derive required tokens from a free-text query (all must be present).

    Tokens shorter than ``min_len`` and common stopwords are dropped so that
    distinctive parts (brand + model number) drive the match.
    """
    tokens = [
        t for t in normalize(query).split()
        if len(t) >= min_len and t not in _STOPWORDS
    ]
    # De-duplicate while preserving order.
    return list(dict.fromkeys(tokens))


def is_relevant(
    title: str,
    include_terms: list[str] | None,
    exclude_terms: list[str] | None = None,
    *,
    use_default_excludes: bool = True,
) -> bool:
    """True iff *all* include terms match and *no* exclude term matches."""
    norm = normalize(title)
    if not norm:
        return False

    for term in include_terms or []:
        if not term_matches(norm, term):
            return False

    excludes = list(exclude_terms or [])
    if use_default_excludes:
        excludes += DEFAULT_EXCLUDE
    for term in excludes:
        if term_matches(norm, term):
            return False

    return True
