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
    priority_province TEXT,
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


def _migrate(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS won't add new columns to a table that
    already exists (e.g. the live Railway deploy's channels table predates
    priority_province) - patch those in explicitly."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(channels)").fetchall()}
    if "priority_province" not in columns:
        conn.execute("ALTER TABLE channels ADD COLUMN priority_province TEXT")


def init_db() -> None:
    db_dir = os.path.dirname(DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
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


def register_channel(
    channel_id: int, guild_id: int, guild_name: str | None, priority_province: str | None = None
) -> bool:
    """Register a channel to receive postings, or update its priority
    province if it's already registered (so re-running !setup can change
    the choice). Returns True if newly registered, False if it already
    existed (regardless of whether the province changed)."""
    with _connect() as conn:
        existed = conn.execute(
            "SELECT 1 FROM channels WHERE channel_id = ?", (channel_id,)
        ).fetchone() is not None
        conn.execute(
            """
            INSERT INTO channels (channel_id, guild_id, guild_name, priority_province)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                guild_name = excluded.guild_name,
                priority_province = excluded.priority_province
            """,
            (channel_id, guild_id, guild_name, priority_province),
        )
        conn.commit()
        return not existed


def unregister_channel(channel_id: int) -> bool:
    """Returns True if a registered channel was removed, False if it
    wasn't registered."""
    with _connect() as conn:
        cursor = conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
        conn.commit()
        return cursor.rowcount > 0


def list_channels() -> list[tuple[int, str | None]]:
    """Returns (channel_id, priority_province) for every registered channel."""
    with _connect() as conn:
        rows = conn.execute("SELECT channel_id, priority_province FROM channels").fetchall()
        return [(row[0], row[1]) for row in rows]


def is_channel_registered(channel_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM channels WHERE channel_id = ?", (channel_id,)).fetchone()
        return row is not None


def get_priority_province(channel_id: int) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT priority_province FROM channels WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        return row[0] if row else None


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
