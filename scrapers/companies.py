from scrapers.base import Job
from scrapers.greenhouse import scrape_greenhouse
from scrapers.lever import scrape_lever

# Each entry maps a display company name to the identifier its ATS scraper
# needs (e.g. a board token).
GREENHOUSE_COMPANIES = {
    "Hootsuite": "hootsuite",
    "Faire": "faire",
}

LEVER_COMPANIES = {
    "Wattpad": "wattpad",
}


def scrape_all_companies() -> list[Job]:
    jobs = []
    for company_name, board_token in GREENHOUSE_COMPANIES.items():
        jobs.extend(scrape_greenhouse(company_name, board_token))
    for company_name, company_token in LEVER_COMPANIES.items():
        jobs.extend(scrape_lever(company_name, company_token))
    return jobs
