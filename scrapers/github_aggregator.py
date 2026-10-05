import time
from dataclasses import replace

import requests

from config import COOP_TRACKER_REPO
from scrapers.base import Job
from scrapers.terms import earliest_term

# Community-maintained trackers of active postings across hundreds of
# companies, updated continuously by bots + PRs. NOTE: neither repo declares
# a license, so anything republishing this data should attribute the source.
_RAW_URL = "https://raw.githubusercontent.com/SimplifyJobs/{repo}/dev/.github/scripts/listings.json"
COOP_LISTINGS_URL = _RAW_URL.format(repo=COOP_TRACKER_REPO)
NEW_GRAD_LISTINGS_URL = _RAW_URL.format(repo="New-Grad-Positions")

COOP_SOURCE = "github_aggregator"
COOP_LABEL = "github_aggregator_coop"  # scrape label used for success/closing bookkeeping
NEW_GRAD_SOURCE = "github_aggregator_newgrad"

# The files are 12-13 MB each, but GitHub serves an ETag, so an unchanged file
# costs a ~60 ms 304 instead of a full download. Cached per (url, source).
_cache: dict[tuple[str, str], tuple[str, list[Job]]] = {}


def _format_posted_at(epoch_seconds) -> str | None:
    if not epoch_seconds:
        return None
    return time.strftime("%Y-%m-%d", time.gmtime(epoch_seconds))


def _copies(jobs: list[Job]) -> list[Job]:
    # Callers mutate jobs (e.g. pipeline sets job.id), so never hand out the cached objects.
    return [replace(job) for job in jobs]


def scrape_github_aggregator(listings_url: str, source: str) -> list[Job]:
    cache_key = (listings_url, source)
    cached = _cache.get(cache_key)
    headers = {"If-None-Match": cached[0]} if cached else {}

    response = requests.get(listings_url, headers=headers, timeout=15)
    if response.status_code == 304 and cached:
        return _copies(cached[1])
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
                term=earliest_term(posting.get("terms") or []),
            )
        )

    etag = response.headers.get("ETag")
    if etag:
        _cache[cache_key] = (etag, jobs)
    return _copies(jobs)
