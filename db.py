import hashlib
import sqlite3
from contextlib import contextmanager

from config import DATABASE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_hash TEXT UNIQUE NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    job_type TEXT,
    url TEXT NOT NULL,
    source TEXT NOT NULL,
    posted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _dedup_hash(company: str, title: str, url: str) -> str:
    key = f"{company.strip().lower()}|{title.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(key.encode()).hexdigest()


@contextmanager
def _connect():
    conn = sqlite3.connect(DATABASE_PATH)
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA)
        conn.commit()


def insert_job(
    company: str,
    title: str,
    url: str,
    location: str | None = None,
    job_type: str | None = None,
    source: str | None = None,
    posted_at: str | None = None,
) -> bool:
    """Insert a job if it hasn't been seen before. Returns True if newly inserted."""
    dedup_hash = _dedup_hash(company, title, url)
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO jobs
                (dedup_hash, company, title, location, job_type, url, source, posted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (dedup_hash, company, title, location, job_type, url, source, posted_at),
        )
        conn.commit()
        return cursor.rowcount > 0
