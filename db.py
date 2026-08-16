import hashlib
import os
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

CREATE TABLE IF NOT EXISTS channels (
    channel_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    guild_name TEXT,
    registered_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS posted_jobs (
    channel_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    posted_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (channel_id, job_id)
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
    db_dir = os.path.dirname(DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def upsert_job(
    company: str,
    title: str,
    url: str,
    source: str,
    location: str | None = None,
    job_type: str | None = None,
    posted_at: str | None = None,
) -> int:
    """Insert a job into the catalog if it hasn't been seen before, and
    return its id either way. Whether a job is "new" is now a per-channel
    question (see get_unposted_job_ids), not a global one."""
    dedup_hash = _dedup_hash(company, title, url)
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO jobs
                (dedup_hash, company, title, location, job_type, url, source, posted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (dedup_hash, company, title, location, job_type, url, source, posted_at),
        )
        conn.commit()
        row = conn.execute("SELECT id FROM jobs WHERE dedup_hash = ?", (dedup_hash,)).fetchone()
        return row[0]


def register_channel(channel_id: int, guild_id: int, guild_name: str | None) -> bool:
    """Register a channel to receive postings. Returns True if newly
    registered, False if it was already registered."""
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO channels (channel_id, guild_id, guild_name) VALUES (?, ?, ?)",
            (channel_id, guild_id, guild_name),
        )
        conn.commit()
        return cursor.rowcount > 0


def unregister_channel(channel_id: int) -> bool:
    """Returns True if a registered channel was removed, False if it
    wasn't registered."""
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        conn.commit()
        return cursor.rowcount > 0


def list_channel_ids() -> list[int]:
    with _connect() as conn:
        rows = conn.execute("SELECT channel_id FROM channels").fetchall()
        return [row[0] for row in rows]


def get_unposted_job_ids(channel_id: int, job_ids: list[int]) -> set[int]:
    """Of the given job ids, return the ones not yet posted to this channel."""
    if not job_ids:
        return set()
    with _connect() as conn:
        placeholders = ",".join("?" for _ in job_ids)
        rows = conn.execute(
            f"SELECT job_id FROM posted_jobs WHERE channel_id = ? AND job_id IN ({placeholders})",
            (channel_id, *job_ids),
        ).fetchall()
        already_posted = {row[0] for row in rows}
        return set(job_ids) - already_posted


def mark_posted(channel_id: int, job_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO posted_jobs (channel_id, job_id) VALUES (?, ?)",
            (channel_id, job_id),
        )
        conn.commit()
