import re
from typing import Iterable

UNSPECIFIED_TERM = "Unspecified"

_SEASON_ORDER = {"winter": 0, "spring": 1, "summer": 2, "fall": 3, "autumn": 3}
_SEASON_NAMES = {0: "Winter", 1: "Spring", 2: "Summer", 3: "Fall"}
_SEASON_YEAR = re.compile(r"\b(winter|spring|summer|fall|autumn)\s+(20\d{2})\b", re.IGNORECASE)
_YEAR_SEASON = re.compile(r"\b(20\d{2})\s+(winter|spring|summer|fall|autumn)\b", re.IGNORECASE)


def parse_term(text: str | None) -> tuple[int, int] | None:
    """Return (year, season_index) for text like "Summer 2027", or None."""
    if not text:
        return None
    match = _SEASON_YEAR.search(text)
    if match:
        return int(match.group(2)), _SEASON_ORDER[match.group(1).lower()]
    match = _YEAR_SEASON.search(text)
    if match:
        return int(match.group(1)), _SEASON_ORDER[match.group(2).lower()]
    return None


def _format(year: int, season: int) -> str:
    return f"{_SEASON_NAMES[season]} {year}"


def earliest_term(terms: Iterable[str]) -> str | None:
    """Earliest parseable term of several (a listing open to Fall 2026 and
    Winter 2027 is filed under Fall 2026). Entries like "N/A" are ignored."""
    parsed = [p for p in (parse_term(t) for t in terms) if p]
    return _format(*min(parsed)) if parsed else None


def term_from_title(title: str | None) -> str | None:
    parsed = parse_term(title)
    return _format(*parsed) if parsed else None


def term_sort_key(term: str | None) -> tuple[int, int]:
    """Sort key where later terms are larger and "Unspecified" is smallest."""
    return parse_term(term) or (-1, -1)
