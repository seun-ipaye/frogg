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
    id: int | None = None  # set once the job is upserted into the DB catalog
