import time

import requests

from scrapers.base import Job

# Community-maintained tracker of active internship/co-op postings across
# hundreds of companies, updated continuously by bots + PRs. MIT-licensed
# and published specifically for third-party consumption like this.
LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships"
    "/dev/.github/scripts/listings.json"
)


def _format_posted_at(epoch_seconds) -> str | None:
    if not epoch_seconds:
        return None
    return time.strftime("%Y-%m-%d", time.gmtime(epoch_seconds))


def scrape_github_aggregator() -> list[Job]:
    response = requests.get(LISTINGS_URL, timeout=15)
    response.raise_for_status()

    jobs = []
    for posting in response.json():
        if not posting.get("active"):
            continue
        jobs.append(
            Job(
                company=posting["company_name"],
                title=posting["title"],
                url=posting["url"],
                location="; ".join(posting.get("locations") or []) or None,
                source="github_aggregator",
                posted_at=_format_posted_at(posting.get("date_posted")),
            )
        )
    return jobs
