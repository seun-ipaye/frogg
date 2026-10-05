import json
from datetime import date

from scrapers.terms import UNSPECIFIED_TERM, normalize_term, parse_term

# Closed listings stay visible (marked 🔒) this long, then move to archive.json.
ARCHIVE_AFTER_DAYS = 30

# Public schema of listings.json / archive.json. Keep it small and stable -
# a landing page will read this. Bookkeeping (last_seen, source, ...) stays in
# SQLite so a cycle that changes nothing visible produces no commit.
JSON_FIELDS = (
    "company", "role", "location", "term", "link", "date_posted", "date_found", "status", "date_closed",
)

MAX_LOCATIONS_SHOWN = 3


def is_archived(row: dict, today: date) -> bool:
    if row["status"] != "closed" or not row.get("date_closed"):
        return False
    return (today - date.fromisoformat(row["date_closed"])).days > ARCHIVE_AFTER_DAYS


def sort_rows(rows: list[dict]) -> list[dict]:
    """Newest posting first; closed listings (🔒) at the bottom, most recently
    closed first. Term is just a column. Fully deterministic."""
    ordered = sorted(rows, key=lambda r: (r["company"].lower(), r["role"].lower(), r["link"]))
    ordered.sort(key=lambda r: (r["date_closed"] if r["status"] == "closed" else r["date_posted"]) or "", reverse=True)
    ordered.sort(key=lambda r: 0 if r["status"] == "open" else 1)
    return ordered


def _public(row: dict) -> dict:
    public = {field: row.get(field) for field in JSON_FIELDS}
    public["term"] = normalize_term(public["term"])  # also fixes rows stored before Spring was folded into Winter
    return public


def dump_json(rows: list[dict]) -> str:
    return json.dumps([_public(r) for r in rows], indent=2, ensure_ascii=False) + "\n"


def _cell(text: str | None) -> str:
    text = " ".join((text or "").split())
    return text.replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def _short_location(location: str | None) -> str:
    parts = [p.strip() for p in (location or "").split(";") if p.strip()]
    if not parts:
        return "–"
    shown = ", ".join(parts[:MAX_LOCATIONS_SHOWN])
    extra = len(parts) - MAX_LOCATIONS_SHOWN
    return _cell(shown + (f" +{extra} more" if extra > 0 else ""))


def _link(url: str) -> str:
    return url.replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _table_row(row: dict) -> str:
    closed = row["status"] == "closed"
    role = ("🔒 " if closed else "") + _cell(row["role"])
    apply = "🔒 Closed" if closed else f"[Apply]({_link(row['link'])})"
    term = "–" if row["term"] == UNSPECIFIED_TERM else _cell(normalize_term(row["term"]))
    return (
        f"| {_cell(row['company'])} | {role} | {_short_location(row['location'])} | {apply} "
        f"| {row['date_posted'] or '–'} | {term} |"
    )


def _years_phrase(rows: list[dict]) -> str:
    """e.g. "2026, 2027 and 2028", taken from the terms of open listings so the
    intro never goes stale."""
    years = sorted({parsed[0] for r in rows if r["status"] == "open" and (parsed := parse_term(r["term"]))})
    if len(years) <= 1:
        return str(years[0]) if years else ""
    return ", ".join(map(str, years[:-1])) + f" and {years[-1]}"


def _creator_line(name: str | None, github_url: str | None, linkedin_url: str | None) -> str | None:
    if not name:
        return None
    links = [f"[GitHub]({github_url})" if github_url else None, f"[LinkedIn]({linkedin_url})" if linkedin_url else None]
    links = " · ".join(link for link in links if link)
    credit = f"Built and maintained by **{name}**" + (f" ({links})" if links else "") + "."
    return credit + " ⭐ Star or 👀 watch this repo to keep up with new postings."


def build_readme(
    rows: list[dict], *, tracker_repo: str, interval_minutes: int, invite_url: str | None,
    creator_name: str | None = None, creator_github_url: str | None = None, creator_linkedin_url: str | None = None,
) -> str:
    """rows: non-archived rows, already sorted by sort_rows()."""
    open_count = sum(1 for r in rows if r["status"] == "open")
    closed_count = len(rows) - open_count
    years = _years_phrase(rows)
    bot = f" — [add Frogg to your server]({invite_url})" if invite_url else ""
    creator = _creator_line(creator_name, creator_github_url, creator_linkedin_url)

    lines = [
        "# 🐸 Canadian Tech Internships & Co-ops",
        "",
        f"Open tech internships and co-ops in Canada for Winter, Summer and Fall{' ' + years if years else ''}. "
        "Roles span software engineering (backend, frontend, full-stack), data science, AI/ML, DevOps, IT, "
        "product and hardware engineering, in Toronto, Montreal, Vancouver, Ottawa, Waterloo, Calgary and other "
        "Canadian cities, plus remote roles open to applicants in Canada.",
        "",
        f"Updated automatically every {interval_minutes} minutes by **Frogg**, a Discord bot that delivers "
        f"new postings to student servers{bot}.",
        "",
        f"**{open_count} open** · {closed_count} closed in the last {ARCHIVE_AFTER_DAYS} days · "
        "Data: [`listings.json`](listings.json) · [`archive.json`](archive.json)",
        "",
        f"Listings come from [SimplifyJobs' community-maintained internship tracker](https://github.com/SimplifyJobs/{tracker_repo}) "
        "and companies' own career pages (Greenhouse, Lever, Workday). This project isn't affiliated with SimplifyJobs.",
    ]
    if creator:
        lines += ["", creator]
    lines += [
        "",
        "<details>",
        "<summary><b>How this list works</b></summary>",
        "",
        "- **Sorted by newest posting**, so the most recently posted roles are at the top.",
        "- **Term** is the work term (Winter, Summer or Fall) when the posting states one, otherwise `–`.",
        "- **🔒 means closed**: the posting disappeared from its source. Closed listings stay visible for "
        f"{ARCHIVE_AFTER_DAYS} days, then move to [`archive.json`](archive.json).",
        "- **Remote roles** are included only if they're open to applicants in Canada.",
        f"- **Updated every {interval_minutes} minutes** automatically; `listings.json` has the same data in a "
        "machine-readable format.",
        "- Always confirm details on the employer's site before applying.",
        "",
        "</details>",
        "",
        "| Company | Role | Location | Apply | Date Posted | Term |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines += [_table_row(row) for row in rows]
    lines.append("")
    return "\n".join(lines)


def render_files(
    rows: list[dict], today: date, *, tracker_repo: str, interval_minutes: int, invite_url: str | None,
    creator_name: str | None = None, creator_github_url: str | None = None, creator_linkedin_url: str | None = None,
) -> dict[str, str]:
    """All published files, as {path: text}. Pure and deterministic: the same
    rows on the same day always render byte-identical output."""
    archived = sort_rows([r for r in rows if is_archived(r, today)])
    current = sort_rows([r for r in rows if not is_archived(r, today)])
    return {
        "listings.json": dump_json(current),
        "archive.json": dump_json(archived),
        "README.md": build_readme(
            current, tracker_repo=tracker_repo, interval_minutes=interval_minutes, invite_url=invite_url,
            creator_name=creator_name, creator_github_url=creator_github_url,
            creator_linkedin_url=creator_linkedin_url,
        ),
    }
