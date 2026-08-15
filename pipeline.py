from db import insert_job
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
    return only the jobs that are new (not already in the database)."""
    scraped = scrape_all_companies()
    matched = [job for job in scraped if is_internship(job) and is_canadian(job)]

    new_jobs = []
    for job in matched:
        if insert_job(
            company=job.company,
            title=job.title,
            url=job.url,
            location=job.location,
            job_type=job.job_type,
            source=job.source,
            posted_at=job.posted_at,
        ):
            new_jobs.append(job)
    return new_jobs
