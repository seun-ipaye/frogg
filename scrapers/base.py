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
