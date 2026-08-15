from scrapers.base import Job
from scrapers.greenhouse import scrape_greenhouse

# Each entry maps a display company name to the ATS scraper used to fetch
# its postings and the identifier that scraper needs (e.g. a board token).
GREENHOUSE_COMPANIES = {
    "Hootsuite": "hootsuite",
    "Faire": "faire",
}


def scrape_all_companies() -> list[Job]:
    jobs = []
    for company_name, board_token in GREENHOUSE_COMPANIES.items():
        jobs.extend(scrape_greenhouse(company_name, board_token))
    return jobs
