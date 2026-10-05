import json
from datetime import date

from scrapers.terms import UNSPECIFIED_TERM, term_sort_key

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
    """Newest term first; within a term open listings before closed, newest
    first (closed ones by when they closed). Fully deterministic."""
    ordered = sorted(rows, key=lambda r: (r["company"].lower(), r["role"].lower(), r["link"]))
    ordered.sort(key=lambda r: (r["date_closed"] if r["status"] == "closed" else r["date_posted"]) or "", reverse=True)
    ordered.sort(key=lambda r: 0 if r["status"] == "open" else 1)
    ordered.sort(key=lambda r: term_sort_key(r["term"]), reverse=True)
    return ordered


def _public(row: dict) -> dict:
    return {field: row.get(field) for field in JSON_FIELDS}


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
    return f"| {_cell(row['company'])} | {role} | {_short_location(row['location'])} | {apply} | {row['date_posted'] or '–'} |"


def build_readme(rows: list[dict], *, tracker_repo: str, interval_minutes: int, invite_url: str | None) -> str:
    """rows: non-archived rows, already sorted by sort_rows()."""
    open_count = sum(1 for r in rows if r["status"] == "open")
    closed_count = len(rows) - open_count
    discord = f" — [add Frogg to your server]({invite_url})" if invite_url else ""

    lines = [
        "# 🐸 Canadian Tech Internships & Co-ops",
        "",
        "A live list of open Canadian tech co-op and internship postings, updated automatically "
        f"every {interval_minutes} minutes by **Frogg**, a Discord bot that delivers new postings "
        f"to student servers{discord}.",
        "",
        f"**{open_count} open** · {closed_count} closed in the last {ARCHIVE_AFTER_DAYS} days · "
        "Data: [`listings.json`](listings.json) · [`archive.json`](archive.json)",
        "",
        "🔒 = closed. Newest terms first.",
    ]

    current_term = None
    for row in rows:
        if row["term"] != current_term:
            current_term = row["term"]
            lines += [
                "",
                f"## {_cell(current_term) if current_term != UNSPECIFIED_TERM else 'Term not specified'}",
                "",
                "| Company | Role | Location | Apply | Date Posted |",
                "| --- | --- | --- | --- | --- |",
            ]
        lines.append(_table_row(row))

    lines += [
        "",
        "## About the data",
        "",
        f"Listings come from the community-maintained [SimplifyJobs tracker](https://github.com/SimplifyJobs/{tracker_repo}) "
        "and companies' own career pages (Greenhouse, Lever, Workday). This project isn't affiliated with SimplifyJobs. "
        "A listing is marked closed once it disappears from its source; closed listings stay visible for "
        f"{ARCHIVE_AFTER_DAYS} days, then move to [`archive.json`](archive.json). "
        "Always confirm details on the employer's site before applying.",
        "",
    ]
    return "\n".join(lines)


def render_files(
    rows: list[dict], today: date, *, tracker_repo: str, interval_minutes: int, invite_url: str | None
) -> dict[str, str]:
    """All published files, as {path: text}. Pure and deterministic: the same
    rows on the same day always render byte-identical output."""
    archived = sort_rows([r for r in rows if is_archived(r, today)])
    current = sort_rows([r for r in rows if not is_archived(r, today)])
    return {
        "listings.json": dump_json(current),
        "archive.json": dump_json(archived),
        "README.md": build_readme(
            current, tracker_repo=tracker_repo, interval_minutes=interval_minutes, invite_url=invite_url
        ),
    }
