import logging
from dataclasses import dataclass, field

from scrapers.base import Job
from scrapers.github_aggregator import (
    COOP_LABEL,
    COOP_LISTINGS_URL,
    COOP_SOURCE,
    NEW_GRAD_LISTINGS_URL,
    NEW_GRAD_SOURCE,
    scrape_github_aggregator,
)
from scrapers.greenhouse import scrape_greenhouse
from scrapers.lever import scrape_lever
from scrapers.workday import scrape_workday_status

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


@dataclass
class ScrapeReport:
    jobs: list[Job] = field(default_factory=list)
    # Labels of sources whose FULL listing set was fetched this run. A failed
    # fetch (or a truncated Workday board) is absent from this set, which is
    # what stops "returned nothing" from being mistaken for "everything closed".
    complete: set[str] = field(default_factory=set)


def _try_scrape(label: str, scrape_fn, *args):
    """Run a scraper; on failure log and return None so one broken source
    (a changed API shape, a timeout, a 404) doesn't take down the whole run."""
    try:
        return scrape_fn(*args)
    except Exception:
        logger.exception("Scrape failed for %s, skipping", label)
        return None


def scrape_all_sources(include_new_grad: bool = True) -> ScrapeReport:
    report = ScrapeReport()

    def add(label: str, jobs: list[Job] | None, complete: bool = True) -> None:
        if jobs is None:
            return
        report.jobs.extend(jobs)
        if complete:
            report.complete.add(label)

    # Primary sources: community-maintained aggregators already covering
    # hundreds of companies (one for co-ops/internships, one for new grad
    # roles). Our hand-registered scrapers below supplement them for
    # Canadian companies/postings they might miss.
    add(COOP_LABEL, _try_scrape(COOP_LABEL, scrape_github_aggregator, COOP_LISTINGS_URL, COOP_SOURCE))
    if include_new_grad:
        label = "github_aggregator_newgrad"
        add(label, _try_scrape(label, scrape_github_aggregator, NEW_GRAD_LISTINGS_URL, NEW_GRAD_SOURCE))
    for company_name, board_token in GREENHOUSE_COMPANIES.items():
        label = f"greenhouse:{company_name}"
        add(label, _try_scrape(label, scrape_greenhouse, company_name, board_token))
    for company_name, company_token in LEVER_COMPANIES.items():
        label = f"lever:{company_name}"
        add(label, _try_scrape(label, scrape_lever, company_name, company_token))
    for company_name, (tenant, wd_host, site) in WORKDAY_COMPANIES.items():
        label = f"workday:{company_name}"
        result = _try_scrape(label, scrape_workday_status, company_name, tenant, wd_host, site)
        if result is not None:
            add(label, result[0], complete=result[1])
    return report


def scrape_all_companies() -> list[Job]:
    """What the Discord pipeline uses - unchanged behavior."""
    return scrape_all_sources().jobs
