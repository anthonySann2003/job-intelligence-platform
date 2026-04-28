"""
database.py
-----------
SQLite schema creation and all query helpers.
Handles: jobs, keyword_frequency, kpi_runs tables.
"""
 
import sqlite3
import json
from datetime import datetime, timezone
from typing import Optional
from config import DB_PATH
 
 
def get_connection() -> sqlite3.Connection:
    """Return a connection with row_factory set for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
 
 
def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY,
                url TEXT UNIQUE,
                title TEXT,
                company TEXT,
                location TEXT,
                seniority TEXT,
                raw_text TEXT,
                skills_required TEXT,
                final_score REAL,
                recommendation TEXT,
                match_reason TEXT,
                missing_keywords TEXT,
                resume_tweak TEXT,
                fetched_at TIMESTAMP,
                applied INTEGER DEFAULT 0
            );
 
            CREATE TABLE IF NOT EXISTS keyword_frequency (
                keyword TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                last_seen TIMESTAMP
            );
 
            CREATE TABLE IF NOT EXISTS kpi_runs (
                id INTEGER PRIMARY KEY,
                run_at TIMESTAMP,
                jobs_processed INTEGER,
                time_saved_minutes INTEGER,
                match_rate REAL,
                top_missing_keyword TEXT
            );
        """)
 
 
# ── Job queries ───────────────────────────────────────────────────────────────
 
def upsert_job(job: dict) -> None:
    """Insert or update a job record. URL is the unique key.
 
    skills_required and missing_keywords are stored as JSON strings.
    The 'applied' flag is never overwritten on update — preserves user action.
    """
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO jobs (
                url, title, company, location, seniority, raw_text,
                skills_required, final_score, recommendation, match_reason,
                missing_keywords, resume_tweak, fetched_at, applied
            ) VALUES (
                :url, :title, :company, :location, :seniority, :raw_text,
                :skills_required, :final_score, :recommendation, :match_reason,
                :missing_keywords, :resume_tweak, :fetched_at, :applied
            )
            ON CONFLICT(url) DO UPDATE SET
                title              = excluded.title,
                company            = excluded.company,
                location           = excluded.location,
                seniority          = excluded.seniority,
                raw_text           = excluded.raw_text,
                skills_required    = excluded.skills_required,
                final_score        = excluded.final_score,
                recommendation     = excluded.recommendation,
                match_reason       = excluded.match_reason,
                missing_keywords   = excluded.missing_keywords,
                resume_tweak       = excluded.resume_tweak,
                fetched_at         = excluded.fetched_at
        """, {
            "url":              job.get("url"),
            "title":            job.get("title"),
            "company":          job.get("company"),
            "location":         job.get("location"),
            "seniority":        job.get("seniority"),
            "raw_text":         job.get("raw_text"),
            "skills_required":  json.dumps(job.get("skills_required", [])),
            "final_score":      job.get("final_score"),
            "recommendation":   job.get("recommendation"),
            "match_reason":     job.get("match_reason"),
            "missing_keywords": json.dumps(job.get("missing_keywords", [])),
            "resume_tweak":     job.get("resume_tweak"),
            "fetched_at":       job.get("fetched_at", datetime.now(timezone.utc).isoformat()),
            "applied":          job.get("applied", 0),
        })
 
 
def get_all_jobs(min_score: float = 0.0) -> list[dict]:
    """Return all jobs above min_score, ordered by final_score DESC."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE final_score >= ? ORDER BY final_score DESC",
            (min_score,)
        ).fetchall()
 
    jobs = []
    for row in rows:
        job = dict(row)
        job["skills_required"]  = json.loads(job["skills_required"] or "[]")
        job["missing_keywords"] = json.loads(job["missing_keywords"] or "[]")
        jobs.append(job)
    return jobs
 
 
def mark_applied(job_id: int, applied: bool = True) -> None:
    """Toggle the applied flag for a job."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET applied = ? WHERE id = ?",
            (1 if applied else 0, job_id)
        )
 
 
# ── Keyword queries ───────────────────────────────────────────────────────────
 
def update_keyword_frequencies(keywords: list[str]) -> None:
    """Increment count for each keyword, insert if not present."""
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        for kw in keywords:
            kw = kw.strip().lower()
            if not kw:
                continue
            conn.execute("""
                INSERT INTO keyword_frequency (keyword, count, last_seen)
                VALUES (?, 1, ?)
                ON CONFLICT(keyword) DO UPDATE SET
                    count     = count + 1,
                    last_seen = excluded.last_seen
            """, (kw, now))
 
 
def get_top_keywords(limit: int = 10) -> list[dict]:
    """Return top N keywords by frequency."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT keyword, count, last_seen FROM keyword_frequency ORDER BY count DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(row) for row in rows]
 
 
# ── KPI queries ───────────────────────────────────────────────────────────────
 
def save_kpi_run(
    jobs_processed: int,
    match_rate: float,
    top_missing_keyword: str,
) -> None:
    """Persist a KPI snapshot for this pipeline run."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO kpi_runs (run_at, jobs_processed, time_saved_minutes, match_rate, top_missing_keyword)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.now(timezone.utc).isoformat(),
            jobs_processed,
            jobs_processed * 15,
            match_rate,
            top_missing_keyword,
        ))
 
 
def get_latest_kpi() -> Optional[dict]:
    """Return the most recent KPI run record."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM kpi_runs ORDER BY run_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None
 
 
# ── Smoke test ────────────────────────────────────────────────────────────────
 
if __name__ == "__main__":
    import os
    import config
 
    TEST_DB = "test_smoke.db"
    config.DB_PATH = TEST_DB
 
    # Patch sqlite3.connect to always use the test DB
    _real_connect = sqlite3.connect
    sqlite3.connect = lambda path, **kw: _real_connect(TEST_DB, **kw)
 
    try:
        print("① init_db()...")
        init_db()
        print("   ✓ tables created")
 
        print("② upsert_job() — insert...")
        fake_job = {
            "url": "https://example.com/jobs/123",
            "title": "Senior Python Engineer",
            "company": "Acme Corp",
            "location": "Remote",
            "seniority": "senior",
            "raw_text": "We are looking for a senior Python engineer...",
            "skills_required": ["Python", "FastAPI", "PostgreSQL"],
            "final_score": 78.5,
            "recommendation": "Strong Apply",
            "match_reason": "Strong Python and API experience alignment.",
            "missing_keywords": ["Kubernetes", "Terraform"],
            "resume_tweak": "Add a bullet about deploying to Kubernetes.",
        }
        upsert_job(fake_job)
        print("   ✓ inserted")
 
        print("③ upsert_job() — update (same URL, new score + title)...")
        fake_job["final_score"] = 85.0
        fake_job["title"] = "Staff Python Engineer"
        upsert_job(fake_job)
        print("   ✓ updated")
 
        print("④ get_all_jobs()...")
        jobs = get_all_jobs(min_score=0.0)
        assert len(jobs) == 1, f"Expected 1 job, got {len(jobs)}"
        assert jobs[0]["title"] == "Staff Python Engineer"
        assert jobs[0]["skills_required"] == ["Python", "FastAPI", "PostgreSQL"]
        assert jobs[0]["final_score"] == 85.0
        print(f"   ✓ {len(jobs)} job: '{jobs[0]['title']}' @ {jobs[0]['company']} — score {jobs[0]['final_score']}")
 
        print("⑤ mark_applied()...")
        mark_applied(jobs[0]["id"], applied=True)
        jobs = get_all_jobs()
        assert jobs[0]["applied"] == 1
        print("   ✓ applied flag toggled on")
 
        print("⑥ update_keyword_frequencies()...")
        update_keyword_frequencies(["Kubernetes", "Terraform", "Kubernetes", "Docker"])
        kws = get_top_keywords(limit=3)
        assert kws[0]["keyword"] == "kubernetes"
        assert kws[0]["count"] == 2
        print(f"   ✓ top keywords: {[(k['keyword'], k['count']) for k in kws]}")
 
        print("⑦ save_kpi_run() + get_latest_kpi()...")
        save_kpi_run(jobs_processed=10, match_rate=70.0, top_missing_keyword="kubernetes")
        kpi = get_latest_kpi()
        assert kpi["jobs_processed"] == 10
        assert kpi["time_saved_minutes"] == 150
        print(f"   ✓ KPI: {kpi['jobs_processed']} jobs, {kpi['time_saved_minutes']} min saved, {kpi['match_rate']}% match rate")
 
        print("\n✅ All checks passed — database.py is working correctly.")
 
    finally:
        import gc
        gc.collect()
        sqlite3.connect = _real_connect
        if os.path.exists(TEST_DB):
            try:
                os.remove(TEST_DB)
                print(f"   (cleaned up {TEST_DB})")
            except PermissionError:
                print(f"   (note: could not delete {TEST_DB} — safe to delete manually)")
 