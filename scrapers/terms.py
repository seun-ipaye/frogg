import re
from datetime import date
from typing import Iterable

UNSPECIFIED_TERM = "Unspecified"

# Only Winter / Summer / Fall exist here. The trackers also say "Spring" (the
# US January-to-May term, i.e. Canada's Winter) and "Autumn", so fold those in.
_SEASON_ORDER = {"winter": 0, "spring": 0, "summer": 1, "fall": 2, "autumn": 2}
_SEASON_NAMES = {0: "Winter", 1: "Summer", 2: "Fall"}
_SEASON_YEAR = re.compile(r"\b(winter|spring|summer|fall|autumn)\s+(20\d{2})\b", re.IGNORECASE)
_YEAR_SEASON = re.compile(r"\b(20\d{2})\s+(winter|spring|summer|fall|autumn)\b", re.IGNORECASE)
# Last month of each term: Winter is Jan-Apr, Summer May-Aug, Fall Sep-Dec.
_SEASON_LAST_MONTH = {0: 4, 1: 8, 2: 12}


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


def _has_ended(parsed: tuple[int, int], today: date | None) -> bool:
    if today is None:
        return False
    year, season = parsed
    return (today.year, today.month) > (year, _SEASON_LAST_MONTH[season])


def current_term(term: str | None, today: date | None) -> str | None:
    """The term, unless it has already ended (a posting from October tagged
    "Winter 2026" is a stale tag, not a real Winter 2026 role)."""
    parsed = parse_term(term)
    return _format(*parsed) if parsed and not _has_ended(parsed, today) else None


def normalize_term(term: str | None) -> str | None:
    """Canonical spelling of a term ("Spring 2027" -> "Winter 2027"); anything
    unparseable (e.g. "Unspecified") is returned unchanged."""
    parsed = parse_term(term)
    return _format(*parsed) if parsed else term


def earliest_term(terms: Iterable[str], today: date | None = None) -> str | None:
    """Earliest parseable term of several (a listing open to Fall 2026 and
    Winter 2027 is filed under Fall 2026). Entries like "N/A" are ignored, and
    so are terms that ended before `today`, so a stale tag never wins."""
    parsed = [p for p in (parse_term(t) for t in terms) if p and not _has_ended(p, today)]
    return _format(*min(parsed)) if parsed else None


def term_from_title(title: str | None, today: date | None = None) -> str | None:
    return current_term(title, today)
