from db import upsert_job
from scrapers.base import Job
from scrapers.companies import scrape_all_companies

INTERN_KEYWORDS = ("intern", "co-op", "coop")

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


def run_pipeline() -> list[Job]:
    """Scrape all sources, filter to Canadian co-op/internship roles, and
    upsert each match into the job catalog. Returns every match (not just
    ones new to the catalog) - which of these are new is a per-channel
    question the caller answers via db.get_unposted_job_ids()."""
    scraped = scrape_all_companies()
    matched = [job for job in scraped if is_internship(job) and is_canadian(job)]

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
