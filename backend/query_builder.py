from __future__ import annotations

import re

from .config import KEYWORD_VARIATIONS


_SPLIT_PATTERN = re.compile(r"[,;\n]+")


def parse_keywords(raw_keywords: str) -> list[str]:
    keywords = [
        _clean_keyword(part)
        for part in _SPLIT_PATTERN.split(raw_keywords or "")
    ]
    return [keyword for keyword in dict.fromkeys(keywords) if keyword]


def expand_keyword_variations(keyword: str) -> list[str]:
    cleaned = _clean_keyword(keyword)
    if not cleaned:
        return []

    canonical = _canonical_keyword(cleaned)
    variations = [cleaned]

    singular_form = _swap_last_word(cleaned, _singularize_word)
    plural_form = _swap_last_word(cleaned, _pluralize_word)

    if singular_form and singular_form != cleaned:
        variations.append(singular_form)
    if plural_form and plural_form != cleaned:
        variations.append(plural_form)

    variations.extend(KEYWORD_VARIATIONS.get(canonical, []))
    return [value for value in dict.fromkeys(_clean_keyword(item) for item in variations) if value]


def build_search_queries(raw_keywords: str, locations: list[str]) -> list[str]:
    queries: list[str] = []
    keywords = parse_keywords(raw_keywords)

    for keyword in keywords:
        for variation in expand_keyword_variations(keyword):
            if locations:
                for location in locations:
                    queries.append(f"{variation} in {location}")
            else:
                queries.append(variation)

    return [query for query in dict.fromkeys(_clean_keyword(item) for item in queries) if query]


def _canonical_keyword(keyword: str) -> str:
    cleaned = _clean_keyword(keyword)
    if cleaned in KEYWORD_VARIATIONS:
        return cleaned

    singular_phrase = _swap_last_word(cleaned, _singularize_word)
    if singular_phrase in KEYWORD_VARIATIONS:
        return singular_phrase

    return cleaned


def _swap_last_word(phrase: str, transform) -> str:
    words = _clean_keyword(phrase).split()
    if not words:
        return ""

    words[-1] = transform(words[-1])
    return _clean_keyword(" ".join(words))


def _pluralize_word(word: str) -> str:
    if len(word) < 2 or word.endswith("s"):
        return word
    if word.endswith("y") and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("sh", "ch", "x", "z")):
        return word + "es"
    return word + "s"


def _singularize_word(word: str) -> str:
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("sses") and len(word) > 4:
        return word[:-2]
    if word.endswith(("shes", "ches", "xes", "zes")) and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 1:
        return word[:-1]
    return word


def _clean_keyword(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()
