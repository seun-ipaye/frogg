import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlsplit

# Query params that only identify where a click came from. Everything else is
# kept: params like gh_jid / icims can be the ONLY thing distinguishing two
# different jobs that share a URL path.
_TRACKING_PARAMS = {
    "ref", "ref_src", "referrer", "source", "src", "gh_src", "gclid", "fbclid", "msclkid",
    "mc_cid", "mc_eid", "trk", "trkid", "_hsenc", "_hsmi", "lever-source", "lever-origin",
}


def normalize_text(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(r"[^\w]+", " ", value).strip()


def normalize_link(url: str | None) -> str:
    """Comparison form of a link: no scheme/www/fragment/trailing slash, lowercase,
    tracking params dropped, remaining params sorted. Never shown to users."""
    parts = urlsplit((url or "").strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/").lower()
    params = sorted(
        (key.lower(), value.lower())
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not (key.lower().startswith("utm_") or key.lower().removesuffix("[]") in _TRACKING_PARAMS)
    )
    query = "&".join(f"{key}={value}" for key, value in params)
    return f"{host}{path}" + (f"?{query}" if query else "")


def canonical_key(company: str, role: str, link: str) -> str:
    """Stable identity of a listing across runs and sources."""
    raw = "|".join((normalize_text(company), normalize_text(role), normalize_link(link)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


_SHOUTING_WORD = re.compile(r"\b[A-ZÀ-ÖØ-ÞŒ]{4,}\b")


def tidy_location(location: str | None) -> str | None:
    """"TORONTO, Ontario, Canada" -> "Toronto, Ontario, Canada". Only all-caps
    words of 4+ letters are touched, so province codes and short acronyms
    (ON, BC, NYC, SF, USA) stay as they are."""
    if not location:
        return location
    return _SHOUTING_WORD.sub(lambda match: match.group(0).capitalize(), location)
