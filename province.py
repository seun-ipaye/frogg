import re

# (display name, code) - used to build the !setup dropdown options.
PROVINCES = [
    ("Ontario", "ON"),
    ("British Columbia", "BC"),
    ("Alberta", "AB"),
    ("Quebec", "QC"),
    ("Manitoba", "MB"),
    ("Saskatchewan", "SK"),
    ("Nova Scotia", "NS"),
    ("New Brunswick", "NB"),
    ("Newfoundland and Labrador", "NL"),
    ("Prince Edward Island", "PE"),
    ("Yukon", "YT"),
    ("Northwest Territories", "NT"),
    ("Nunavut", "NU"),
]

_PROVINCE_ALIASES: dict[str, tuple[str, ...]] = {
    "ON": ("on", "ontario"),
    "BC": ("bc", "british columbia"),
    "AB": ("ab", "alberta"),
    "MB": ("mb", "manitoba"),
    "SK": ("sk", "saskatchewan"),
    "QC": ("qc", "quebec", "québec"),
    "NS": ("ns", "nova scotia"),
    "NB": ("nb", "new brunswick"),
    "NL": ("nl", "newfoundland", "newfoundland and labrador"),
    "PE": ("pe", "prince edward island"),
    "YT": ("yt", "yukon"),
    "NT": ("nt", "northwest territories"),
    "NU": ("nu", "nunavut"),
}


def province_name(code: str) -> str:
    """Full display name for a province code, e.g. "ON" -> "Ontario"."""
    return next((name for name, c in PROVINCES if c == code), code)


def detect_province(location: str | None) -> str | None:
    """Return the single province/territory code a location string clearly
    indicates, or None if there isn't exactly one match - no match at all
    (e.g. "Remote in Canada"), or the listing spans multiple provinces
    (treated as ambiguous rather than guessed)."""
    if not location:
        return None
    segments = [seg.strip().lower() for seg in re.split(r"[,;]", location) if seg.strip()]
    matched = {code for seg in segments for code, aliases in _PROVINCE_ALIASES.items() if seg in aliases}
    return matched.pop() if len(matched) == 1 else None
