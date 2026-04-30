import sqlite3
import json
from datetime import datetime

DB_PATH = "jobs.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                title             TEXT,
                company           TEXT,
                location          TEXT,
                salary_min        REAL,
                salary_max        REAL,
                description       TEXT,
                url               TEXT UNIQUE,
                created           TEXT,
                score             REAL,
                keywords          TEXT,
                missing_keywords  TEXT,
                llm_summary       TEXT
            )
        """)
        # Add scoring columns to existing DBs that predate this change
        for col, coltype in [
            ("score",            "REAL"),
            ("keywords",         "TEXT"),
            ("missing_keywords", "TEXT"),
            ("llm_summary",      "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {coltype}")
            except Exception:
                pass  # column already exists, skip

        # Single-row resume store — also serves as the user's editable profile
        conn.execute("""
            CREATE TABLE IF NOT EXISTS resumes (
                id          INTEGER PRIMARY KEY,
                parsed_json TEXT,
                filename    TEXT,
                uploaded_at TEXT
            )
        """)

        conn.commit()


def save_jobs(jobs: list[dict]) -> int:
    """Insert jobs, skip duplicates (url is unique). Returns count of newly inserted."""
    inserted = 0
    with get_connection() as conn:
        for job in jobs:
            try:
                conn.execute("""
                    INSERT INTO jobs (title, company, location, salary_min, salary_max, description, url, created)
                    VALUES (:title, :company, :location, :salary_min, :salary_max, :description, :url, :created)
                """, job)
                inserted += 1
            except sqlite3.IntegrityError:
                pass  # duplicate url, skip it
        conn.commit()
    return inserted


def load_jobs() -> list[dict]:
    """Load all stored jobs from the database."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def get_unscored_jobs() -> list[dict]:
    """Return only jobs that haven't been scored yet."""
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM jobs WHERE score IS NULL ORDER BY id ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def update_job_score(job_id: int, score: float, keywords: str, missing_keywords: str, llm_summary: str):
    """Write scoring results back to a job row."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE jobs
            SET score = ?, keywords = ?, missing_keywords = ?, llm_summary = ?
            WHERE id = ?
        """, (score, keywords, missing_keywords, llm_summary, job_id))
        conn.commit()


def save_resume(parsed: dict, filename: str = ""):
    """
    Persist a single resume/profile, replacing any existing one.
    Called both on initial PDF parse and whenever the user saves edits
    from the Profile tab — single source of truth for the scorer.
    """
    with get_connection() as conn:
        conn.execute("DELETE FROM resumes")
        conn.execute("""
            INSERT INTO resumes (id, parsed_json, filename, uploaded_at)
            VALUES (1, ?, ?, ?)
        """, (json.dumps(parsed), filename, datetime.utcnow().isoformat()))
        conn.commit()


def load_resume() -> dict | None:
    """Return the stored resume/profile dict, or None if none exists."""
    with get_connection() as conn:
        row = conn.execute("SELECT parsed_json FROM resumes LIMIT 1").fetchone()
    return json.loads(row[0]) if row else None


def clear_job_score(job_id: int):
    """Reset scoring columns to NULL for a single job."""
    with get_connection() as conn:
        conn.execute("""
            UPDATE jobs
            SET score = NULL, keywords = NULL, missing_keywords = NULL, llm_summary = NULL
            WHERE id = ?
        """, (job_id,))
        conn.commit()

def get_insights() -> dict:
    """
    Aggregate insights from all scored jobs in the DB.
    Returns a dict with score distribution, missing keyword counts,
    and top scored jobs. No new LLM calls — purely SQL + Python aggregation.
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM jobs WHERE score IS NOT NULL ORDER BY score DESC"
        ).fetchall()

    jobs = [dict(row) for row in rows]

    if not jobs:
        return {"empty": True}

    # ── Score distribution ─────────────────────────────────────────────────
    distribution = {
        "strong":  0,  # 80-100
        "good":    0,  # 66-79
        "partial": 0,  # 50-65
        "poor":    0,  # 0-49
    }
    for job in jobs:
        score = job["score"]
        if score >= 80:
            distribution["strong"]  += 1
        elif score >= 66:
            distribution["good"]    += 1
        elif score >= 50:
            distribution["partial"] += 1
        else:
            distribution["poor"]    += 1

    # ── Missing keyword frequency ──────────────────────────────────────────
    keyword_counts = {}
    for job in jobs:
        raw = job.get("missing_keywords")
        if not raw:
            continue
        try:
            keywords = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for kw in keywords:
            kw = kw.strip().lower()
            if kw:
                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

    top_missing = sorted(
        keyword_counts.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    # ── Top scored jobs ────────────────────────────────────────────────────
    top_jobs = jobs[:10]

    return {
        "empty":        False,
        "total_scored": len(jobs),
        "distribution": distribution,
        "top_missing":  top_missing,
        "top_jobs":     top_jobs,
    }