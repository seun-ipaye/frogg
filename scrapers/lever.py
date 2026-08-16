from datetime import datetime, timezone

import requests

from scrapers.base import Job

LEVER_API_URL = "https://api.lever.co/v0/postings/{company_token}?mode=json"


def _format_posted_at(created_at_ms: int | None) -> str | None:
    if not created_at_ms:
        return None
    return datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def scrape_lever(company_name: str, company_token: str) -> list[Job]:
    response = requests.get(LEVER_API_URL.format(company_token=company_token), timeout=10)
    response.raise_for_status()

    jobs = []
    for posting in response.json():
        categories = posting.get("categories") or {}
        jobs.append(
            Job(
                company=company_name,
                title=posting["text"],
                url=posting["hostedUrl"],
                location=categories.get("location"),
                job_type=categories.get("commitment"),
                source="lever",
                posted_at=_format_posted_at(posting.get("createdAt")),
            )
        )
    return jobs
