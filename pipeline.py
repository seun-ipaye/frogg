from datetime import date, datetime

from db import upsert_job
from scrapers.base import Job
from scrapers.companies import scrape_all_companies

INTERN_KEYWORDS = ("intern", "co-op", "coop")

# A job board's "active" listing can stay open for weeks/months after
# posting, which flooded a freshly-!setup channel with the entire backlog
# (111 jobs, most over a month old). Only show postings from within this
# window instead.
MAX_POSTING_AGE_DAYS = 4

# City/province names are deliberately excluded: they collide with US
# places (e.g. "Vancouver, WA", "Richmond, VA"). Every genuine Canadian
# posting we've checked across sources explicitly includes "Canada" in
# the location string, so that alone is both sufficient and precise.
CANADA_KEYWORDS = ("canada",)

# Sources that are already scoped to internship/co-op postings, so the
# title keyword filter would just drop legitimate entries with titles
# like "Summer Associate" or "Undergraduate Cartographer".
PRE_FILTERED_SOURCES = ("github_aggregator",)


def is_internship(job: Job) -> bool:
    if job.source in PRE_FILTERED_SOURCES:
        return True
    title = job.title.lower()
    return any(keyword in title for keyword in INTERN_KEYWORDS)


def is_canadian(job: Job) -> bool:
    location = (job.location or "").lower()
    return any(keyword in location for keyword in CANADA_KEYWORDS)


def is_recent(job: Job) -> bool:
    """A job with no parseable posted date is excluded rather than assumed
    fresh - the whole point of this filter is to stop stale/undated
    postings from flooding a channel."""
    if not job.posted_at:
        return False
    try:
        posted_date = datetime.strptime(job.posted_at, "%Y-%m-%d").date()
    except ValueError:
        return False
    return (date.today() - posted_date).days <= MAX_POSTING_AGE_DAYS


def run_pipeline() -> list[Job]:
    """Scrape all sources, filter to recent Canadian co-op/internship
    roles, and upsert each match into the job catalog. Returns every
    match (not just ones new to the catalog) - which of these are new is
    a per-channel question the caller answers via db.get_unposted_job_ids()."""
    scraped = scrape_all_companies()
    matched = [job for job in scraped if is_internship(job) and is_canadian(job) and is_recent(job)]

    for job in matched:
        job.id = upsert_job(
            company=job.company,
            title=job.title,
            url=job.url,
            location=job.location,
            job_type=job.job_type,
            source=job.source,
            posted_at=job.posted_at,
        )
    return matched
