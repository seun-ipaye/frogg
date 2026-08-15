import requests

from scrapers.base import Job

WORKDAY_JOBS_URL = "https://{tenant}.{wd_host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
WORKDAY_JOB_BASE_URL = "https://{tenant}.{wd_host}.myworkdayjobs.com/en-US/{site}"

PAGE_SIZE = 20
MAX_PAGES = 5  # caps a single company at 100 postings per scrape


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
                )
            )

        if offset + PAGE_SIZE >= data.get("total", 0):
            break

    return jobs
