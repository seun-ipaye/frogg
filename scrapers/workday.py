import re
from datetime import date, timedelta

import requests

from scrapers.base import Job

WORKDAY_JOBS_URL = "https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
WORKDAY_JOB_BASE_URL = "https://{tenant}.{wd_host}.myworkdayjobs.com/en-US/{site}"

PAGE_SIZE = 20
MAX_PAGES = 5  # caps a single company at 100 postings per scrape

_DAYS_AGO_RE = re.compile(r"posted (\d+)\+?\s*days? ago")


def _format_posted_at(posted_on: str | None) -> str | None:
    """Workday gives relative text like 'Posted Today'/'Posted Yesterday'/
    'Posted 3 Days Ago'/'Posted 30+ Days Ago' instead of a real date."""
    if not posted_on:
        return None
    text = posted_on.strip().lower()
    if text == "posted today":
        days_ago = 0
    elif text == "posted yesterday":
        days_ago = 1
    else:
        match = _DAYS_AGO_RE.match(text)
        if not match:
            return None
        days_ago = int(match.group(1))
    return (date.today() - timedelta(days=days_ago)).isoformat()


def scrape_workday(company_name: str, tenant: str, wd_host: str, site: str) -> list[Job]:
    jobs = []
    base_url = WORKDAY_JOB_BASE_URL.format(tenant=tenant, wd_host=wd_host, site=site)

    for page in range(MAX_PAGES):
        offset = page * PAGE_SIZE
        response = requests.post(
            WORKDAY_JOBS_URL.format(tenant=tenant, wd_host=wd_host, site=site),
            json={"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": ""},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break

        for posting in postings:
            jobs.append(
                Job(
                    company=company_name,
                    title=posting["title"],
                    url=base_url + posting["externalPath"],
                    location=posting.get("locationsText"),
                    source="workday",
                    posted_at=_format_posted_at(posting.get("postedOn")),
                )
            )

        if offset + PAGE_SIZE >= data.get("total", 0):
            break

    return jobs
