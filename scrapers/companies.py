import logging

from scrapers.base import Job
from scrapers.github_aggregator import scrape_github_aggregator
from scrapers.greenhouse import scrape_greenhouse
from scrapers.lever import scrape_lever
from scrapers.workday import scrape_workday

logger = logging.getLogger(__name__)

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


def _safe_scrape(source_label: str, scrape_fn, *args) -> list[Job]:
    """Run a scraper and swallow failures so one broken source (a changed
    API shape, a timeout, a 404) doesn't take down the whole pipeline run."""
    try:
        return scrape_fn(*args)
    except Exception:
        logger.exception("Scrape failed for %s, skipping", source_label)
        return []


def scrape_all_companies() -> list[Job]:
    # Primary source: a community-maintained aggregator already covering
    # hundreds of companies. Our hand-registered scrapers below supplement
    # it for Canadian companies/postings it might miss.
    jobs = _safe_scrape("github_aggregator", scrape_github_aggregator)
    for company_name, board_token in GREENHOUSE_COMPANIES.items():
        jobs.extend(_safe_scrape(f"greenhouse:{company_name}", scrape_greenhouse, company_name, board_token))
    for company_name, company_token in LEVER_COMPANIES.items():
        jobs.extend(_safe_scrape(f"lever:{company_name}", scrape_lever, company_name, company_token))
    for company_name, (tenant, wd_host, site) in WORKDAY_COMPANIES.items():
        jobs.extend(
            _safe_scrape(f"workday:{company_name}", scrape_workday, company_name, tenant, wd_host, site)
        )
    return jobs
