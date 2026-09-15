import time

import requests

from scrapers.base import Job

# Community-maintained trackers of active postings across hundreds of
# companies, updated continuously by bots + PRs. MIT-licensed and published
# specifically for third-party consumption like this.
COOP_LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships"
    "/dev/.github/scripts/listings.json"
)
NEW_GRAD_LISTINGS_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions"
    "/dev/.github/scripts/listings.json"
)

COOP_SOURCE = "github_aggregator"
NEW_GRAD_SOURCE = "github_aggregator_newgrad"


def _format_posted_at(epoch_seconds) -> str | None:
    if not epoch_seconds:
        return None
    return time.strftime("%Y-%m-%d", time.gmtime(epoch_seconds))


def scrape_github_aggregator(listings_url: str, source: str) -> list[Job]:
    response = requests.get(listings_url, timeout=15)
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
                source=source,
                posted_at=_format_posted_at(posting.get("date_posted")),
            )
        )
    return jobs
