from dataclasses import dataclass


@dataclass
class Job:
    company: str
    title: str
    url: str
    location: str | None = None
    job_type: str | None = None
    source: str | None = None
    posted_at: str | None = None
    term: str | None = None  # e.g. "Summer 2027", when the source provides one
    id: int | None = None  # set once the job is upserted into the DB catalog
