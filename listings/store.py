import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass

from db import _connect
from listings.normalize import canonical_key
from scrapers.github_aggregator import COOP_LABEL, COOP_SOURCE
from scrapers.terms import UNSPECIFIED_TERM

logger = logging.getLogger(__name__)

# A listing is only closed after being absent from this many consecutive
# *complete* scrapes of its source (~1.5h at a 30 minute interval), so one odd
# response can't flip it.
CLOSE_AFTER_MISSES = 3

# Sanity guard: if a source suddenly returns under half of what we currently
# have open from it (and there's enough to judge), treat that scrape as
# incomplete instead of closing the difference.
GUARD_MIN_OPEN = 20
GUARD_MIN_RATIO = 0.5


@dataclass(frozen=True)
class Listing:
    key: str
    company: str
    role: str
    location: str | None
    term: str
    link: str
    date_posted: str | None
    source: str


@dataclass
class CycleResult:
    added: int = 0
    closed: int = 0
    reopened: int = 0
    held_labels: tuple[str, ...] = ()


def label_for(source: str, company: str) -> str:
    """Which scrape (see scrapers.companies.ScrapeReport.complete) produced a row."""
    return COOP_LABEL if source == COOP_SOURCE else f"{source}:{company}"


def is_empty() -> bool:
    with _connect() as conn:
        return conn.execute("SELECT 1 FROM listings LIMIT 1").fetchone() is None


def apply_cycle(seen: dict[str, Listing], complete: set[str], today: str, now: str) -> CycleResult:
    """Fold one scrape cycle into the store, in a single transaction.

    seen: every currently open listing found this cycle, by canonical key.
    complete: labels of sources fetched in full this cycle. Only these can
    cause closures; a failed or partial source leaves its rows untouched.
    """
    result = CycleResult()
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        existing = {
            row["canonical_key"]: row
            for row in conn.execute("SELECT canonical_key, status, source, company, missed_cycles FROM listings")
        }

        open_by_label = Counter(
            label_for(row["source"], row["company"]) for row in existing.values() if row["status"] == "open"
        )
        seen_by_label = Counter(label_for(item.source, item.company) for item in seen.values())
        trusted, held = set(), []
        for label in complete:
            open_before = open_by_label[label]
            if open_before >= GUARD_MIN_OPEN and seen_by_label[label] < open_before * GUARD_MIN_RATIO:
                held.append(label)
                logger.warning(
                    "Holding closures for %s: saw %d listings vs %d currently open",
                    label, seen_by_label[label], open_before,
                )
            else:
                trusted.add(label)
        result.held_labels = tuple(sorted(held))

        for key, item in seen.items():
            previous = existing.get(key)
            if previous is None:
                conn.execute(
                    "INSERT INTO listings (canonical_key, company, role, location, term, link, date_posted,"
                    " date_found, status, last_seen_at, missed_cycles, source)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, 0, ?)",
                    (key, item.company, item.role, item.location, item.term, item.link, item.date_posted,
                     today, now, item.source),
                )
                result.added += 1
                continue
            conn.execute(
                "UPDATE listings SET company = ?, role = ?, location = ?, term = ?, link = ?, date_posted = ?,"
                " source = ?, status = 'open', closed_at = NULL, last_seen_at = ?, missed_cycles = 0"
                " WHERE canonical_key = ?",
                (item.company, item.role, item.location, item.term, item.link, item.date_posted,
                 item.source, now, key),
            )
            if previous["status"] == "closed":
                result.reopened += 1

        for key, row in existing.items():
            if key in seen or row["status"] != "open":
                continue
            if label_for(row["source"], row["company"]) not in trusted:
                continue
            misses = row["missed_cycles"] + 1
            if misses >= CLOSE_AFTER_MISSES:
                conn.execute(
                    "UPDATE listings SET status = 'closed', closed_at = ?, missed_cycles = ? WHERE canonical_key = ?",
                    (today, misses, key),
                )
                result.closed += 1
            else:
                conn.execute("UPDATE listings SET missed_cycles = ? WHERE canonical_key = ?", (misses, key))

        conn.commit()
    return result


def all_rows() -> list[dict]:
    """Every stored listing in the public shape (no bookkeeping columns)."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT company, role, location, term, link, date_posted, date_found, status,"
            " closed_at AS date_closed FROM listings"
        )
        return [dict(row) for row in cursor]


def import_rows(rows: list[dict], now: str) -> int:
    """Restore listings from previously published JSON (used when the DB is
    empty, e.g. after losing the volume) so date_found/closed history survives."""
    imported = 0
    with _connect() as conn:
        for row in rows:
            try:
                company, role, link = str(row["company"]).strip(), str(row["role"]).strip(), str(row["link"]).strip()
                status = row.get("status") if row.get("status") in ("open", "closed") else "open"
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO listings (canonical_key, company, role, location, term, link,"
                    " date_posted, date_found, status, closed_at, last_seen_at, missed_cycles, source)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                    (canonical_key(company, role, link), company, role, row.get("location"),
                     row.get("term") or UNSPECIFIED_TERM, link, row.get("date_posted"),
                     row.get("date_found") or now[:10], status, row.get("date_closed"), now, COOP_SOURCE),
                )
                imported += cursor.rowcount
            except (KeyError, TypeError, AttributeError):
                logger.warning("Skipping malformed row while restoring listings: %r", row)
        conn.commit()
    return imported
