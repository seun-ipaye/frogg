import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from config import COOP_TRACKER_REPO, BOT_INVITE_URL, LISTINGS_SYNC_INTERVAL_MINUTES
from listings import render, store
from listings.normalize import canonical_key
from pipeline import is_canadian, is_internship, is_new_grad
from scrapers.companies import scrape_all_sources
from scrapers.terms import UNSPECIFIED_TERM, term_from_title

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("America/Toronto")


@dataclass
class SyncSummary:
    open_seen: int = 0
    added: int = 0
    closed: int = 0
    reopened: int = 0
    held: tuple[str, ...] = ()
    published: list[str] = field(default_factory=list)
    message: str | None = None

    def describe(self) -> str:
        pushed = f"published {', '.join(self.published)} ({self.message!r})" if self.published else "no repo changes"
        held = f", closures held for {list(self.held)}" if self.held else ""
        return (f"{self.open_seen} open listings seen, +{self.added} new, {self.closed} closed, "
                f"{self.reopened} reopened{held}; {pushed}")


def build_universe(jobs) -> dict[str, store.Listing]:
    """Every currently open Canadian co-op/internship, regardless of age. This is
    deliberately broader than what Discord gets (which is limited to the last
    few days): the public repo is a full list. New grad roles are out of scope."""
    universe: dict[str, store.Listing] = {}
    for job in jobs:
        if is_new_grad(job) or not (is_internship(job) and is_canadian(job)):
            continue
        company, role = job.company.strip(), job.title.strip()
        key = canonical_key(company, role, job.url)
        if key in universe:
            continue
        universe[key] = store.Listing(
            key=key,
            company=company,
            role=role,
            location=job.location,
            term=job.term or term_from_title(role) or UNSPECIFIED_TERM,
            link=job.url,
            date_posted=job.posted_at,
            source=job.source or "unknown",
        )
    return universe


def _statuses(listings_json: str | None) -> dict[str, str]:
    if not listings_json:
        return {}
    try:
        return {canonical_key(r["company"], r["role"], r["link"]): r["status"] for r in json.loads(listings_json)}
    except (ValueError, KeyError, TypeError):
        return {}


def commit_message(previous_json: str | None, new_json: str, day: date) -> str:
    """e.g. "Add 12, close 3 listings (Oct 5)" - counted against what the repo
    actually had, so it stays accurate even after a failed earlier push."""
    old, new = _statuses(previous_json), _statuses(new_json)
    added = sum(1 for k, s in new.items() if s == "open" and k not in old)
    closed = sum(1 for k, s in new.items() if s == "closed" and old.get(k) == "open")
    reopened = sum(1 for k, s in new.items() if s == "open" and old.get(k) == "closed")

    parts = []
    for verb, count in (("add", added), ("close", closed), ("reopen", reopened)):
        if count:
            parts.append(f"{verb.capitalize() if not parts else verb} {count}")
    stamp = f"({day:%b} {day.day})"
    if not parts:
        return f"Update listings {stamp}"
    single = len(parts) == 1 and (added + closed + reopened) == 1
    return f"{', '.join(parts)} listing{'' if single else 's'} {stamp}"


def _restore_history(publisher, now: str) -> None:
    """If the DB is empty (fresh volume), re-import what's already published so
    date_found / closed history isn't reset. A read failure raises, aborting the
    cycle: carrying on would republish everything with today's date_found."""
    rows = []
    for path in ("listings.json", "archive.json"):
        text = publisher.read_file(path)
        if text:
            rows.extend(json.loads(text))
    if rows:
        logger.info("Restored %d listings from the published repo", store.import_rows(rows, now))


def run_sync(publisher, *, now: datetime | None = None, scrape=scrape_all_sources) -> SyncSummary:
    now = now or datetime.now(TIMEZONE)
    today = now.date()
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")

    if store.is_empty():
        _restore_history(publisher, stamp)

    report = scrape(include_new_grad=False)
    universe = build_universe(report.jobs)
    cycle = store.apply_cycle(universe, report.complete, today.isoformat(), stamp)
    summary = SyncSummary(
        open_seen=len(universe), added=cycle.added, closed=cycle.closed,
        reopened=cycle.reopened, held=cycle.held_labels,
    )

    rows = store.all_rows()
    if not rows:  # nothing known yet (e.g. every source failed on first run): never publish an empty list
        return summary

    files = render.render_files(
        rows, today, tracker_repo=COOP_TRACKER_REPO,
        interval_minutes=LISTINGS_SYNC_INTERVAL_MINUTES, invite_url=BOT_INVITE_URL,
    )
    outcome = publisher.sync(files, lambda previous: commit_message(previous, files["listings.json"], today))
    summary.published, summary.message = outcome.changed, outcome.message
    return summary
