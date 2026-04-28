"""
database.py
-----------
SQLite schema creation and all query helpers.
Handles: jobs, keyword_frequency, kpi_runs tables.
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional
from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """Return a connection with row_factory set for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    pass


# ── Job queries ───────────────────────────────────────────────────────────────

def upsert_job(job: dict) -> None:
    """Insert or update a job record. URL is the unique key."""
    pass


def get_all_jobs(min_score: float = 0.0) -> list[dict]:
    """Return all jobs above min_score, ordered by final_score DESC."""
    pass


def mark_applied(job_id: int, applied: bool = True) -> None:
    """Toggle the applied flag for a job."""
    pass


# ── Keyword queries ───────────────────────────────────────────────────────────

def update_keyword_frequencies(keywords: list[str]) -> None:
    """Increment count for each keyword, insert if not present."""
    pass


def get_top_keywords(limit: int = 10) -> list[dict]:
    """Return top N keywords by frequency."""
    pass


# ── KPI queries ───────────────────────────────────────────────────────────────

def save_kpi_run(
    jobs_processed: int,
    match_rate: float,
    top_missing_keyword: str,
) -> None:
    """Persist a KPI snapshot for this pipeline run."""
    pass


def get_latest_kpi() -> Optional[dict]:
    """Return the most recent KPI run record."""
    pass
