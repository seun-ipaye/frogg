from datetime import datetime

import requests

from scrapers.base import Job

GREENHOUSE_API_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"


def _format_posted_at(first_published: str | None) -> str | None:
    if not first_published:
        return None
    return datetime.fromisoformat(first_published).strftime("%Y-%m-%d")


def scrape_greenhouse(company_name: str, board_token: str) -> list[Job]:
    response = requests.get(GREENHOUSE_API_URL.format(board_token=board_token), timeout=10)
    response.raise_for_status()

    jobs = []
    for posting in response.json().get("jobs", []):
        jobs.append(
            Job(
                company=company_name,
                title=posting["title"],
                url=posting["absolute_url"],
                location=(posting.get("location") or {}).get("name"),
                source="greenhouse",
                posted_at=_format_posted_at(posting.get("first_published")),
            )
        )
    return jobs
