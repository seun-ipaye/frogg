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


def normalize_term(term: str | None) -> str | None:
    """Canonical spelling of a term ("Spring 2027" -> "Winter 2027"); anything
    unparseable (e.g. "Unspecified") is returned unchanged."""
    parsed = parse_term(term)
    return _format(*parsed) if parsed else term


def earliest_term(terms: Iterable[str]) -> str | None:
    """Earliest parseable term of several (a listing open to Fall 2026 and
    Winter 2027 is filed under Fall 2026). Entries like "N/A" are ignored."""
    parsed = [p for p in (parse_term(t) for t in terms) if p]
    return _format(*min(parsed)) if parsed else None


def term_from_title(title: str | None) -> str | None:
    parsed = parse_term(title)
    return _format(*parsed) if parsed else None


_SEASON_START_MONTH = {0: 1, 1: 5, 2: 9}  # Winter Jan, Summer May, Fall Sep
TERM_LENGTH_MONTHS = 4


def term_window(term: str | None) -> tuple[date, date] | None:
    """(start, end) of a term, e.g. "Fall 2026" -> (2026-09-01, 2027-01-01).
    Approximate - only used to rank terms by how soon they are."""
    parsed = parse_term(term)
    if not parsed:
        return None
    year, season = parsed
    month = _SEASON_START_MONTH[season]
    end_month = month + TERM_LENGTH_MONTHS
    return date(year, month, 1), date(year + (end_month - 1) // 12, (end_month - 1) % 12 + 1, 1)
