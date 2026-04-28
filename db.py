import sqlite3

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