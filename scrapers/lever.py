import requests

from scrapers.base import Job

LEVER_API_URL = "https://api.lever.co/v0/postings/{company_token}?mode=json"


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
            )
        )
    return jobs
