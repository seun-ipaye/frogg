from scrapers.base import Job
from scrapers.github_aggregator import scrape_github_aggregator
from scrapers.greenhouse import scrape_greenhouse
from scrapers.lever import scrape_lever
from scrapers.workday import scrape_workday

# Each entry maps a display company name to the identifier its ATS scraper
# needs (e.g. a board token).
GREENHOUSE_COMPANIES = {
    "Hootsuite": "hootsuite",
    "Faire": "faire",
    "D2L": "d2l",
}

LEVER_COMPANIES = {
    "Wattpad": "wattpad",
    "Wealthsimple": "wealthsimple",
}

# tenant, wd host (e.g. "wd3"), site name
WORKDAY_COMPANIES = {
    "RBC": ("rbc", "wd3", "RBCEARLYTALENT1"),
    "Manulife": ("manulife", "wd3", "MFCJH_Jobs"),
}


def scrape_all_companies() -> list[Job]:
    # Primary source: a community-maintained aggregator already covering
    # hundreds of companies. Our hand-registered scrapers below supplement
    # it for Canadian companies/postings it might miss.
    jobs = scrape_github_aggregator()
    for company_name, board_token in GREENHOUSE_COMPANIES.items():
        jobs.extend(scrape_greenhouse(company_name, board_token))
    for company_name, company_token in LEVER_COMPANIES.items():
        jobs.extend(scrape_lever(company_name, company_token))
    for company_name, (tenant, wd_host, site) in WORKDAY_COMPANIES.items():
        jobs.extend(scrape_workday(company_name, tenant, wd_host, site))
    return jobs
