import logging

from scrapers.base import Job
from scrapers.github_aggregator import (
    COOP_LISTINGS_URL,
    COOP_SOURCE,
    NEW_GRAD_LISTINGS_URL,
    NEW_GRAD_SOURCE,
    scrape_github_aggregator,
)
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
    # Primary sources: community-maintained aggregators already covering
    # hundreds of companies (one for co-ops/internships, one for new grad
    # roles). Our hand-registered scrapers below supplement them for
    # Canadian companies/postings they might miss.
    jobs = _safe_scrape("github_aggregator_coop", scrape_github_aggregator, COOP_LISTINGS_URL, COOP_SOURCE)
    jobs.extend(
        _safe_scrape(
            "github_aggregator_newgrad", scrape_github_aggregator, NEW_GRAD_LISTINGS_URL, NEW_GRAD_SOURCE
        )
    )
    for company_name, board_token in GREENHOUSE_COMPANIES.items():
        jobs.extend(_safe_scrape(f"greenhouse:{company_name}", scrape_greenhouse, company_name, board_token))
    for company_name, company_token in LEVER_COMPANIES.items():
        jobs.extend(_safe_scrape(f"lever:{company_name}", scrape_lever, company_name, company_token))
    for company_name, (tenant, wd_host, site) in WORKDAY_COMPANIES.items():
        jobs.extend(
            _safe_scrape(f"workday:{company_name}", scrape_workday, company_name, tenant, wd_host, site)
        )
    return jobs
