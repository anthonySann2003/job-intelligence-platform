"""
config.py
---------
Central configuration for the Job Intelligence Platform.
API keys are read from environment variables — never hardcoded.
Copy .env.example to .env and fill in your values.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# ── Gmail ─────────────────────────────────────────────────────────────────────
GMAIL_SCOPES: list[str] = ["https://www.googleapis.com/auth/gmail.readonly"]

# Gmail search query — adjust labels/senders to match your setup
GMAIL_SEARCH_QUERY: str = (
    "label:job-alerts OR from:greenhouse.io OR from:lever.co OR from:jobleads.com"
)

# Maximum number of emails to fetch per pipeline run (None = no limit)
GMAIL_MAX_RESULTS: int = 50

# ── Scoring ───────────────────────────────────────────────────────────────────
SCORE_THRESHOLD: int = 65          # minimum score to surface in dashboard
TOP_N_FOR_ANALYSIS: int = 15       # only run full AI analysis on top N jobs
TIME_SAVED_PER_JOB: int = 15       # minutes saved per job reviewed (for KPI)

SCORE_WEIGHTS: dict[str, float] = {
    "skill_match": 0.4,
    "embedding_similarity": 0.3,
    "seniority_fit": 0.2,
    "keyword_overlap": 0.1,
}

# ── Models ────────────────────────────────────────────────────────────────────
EXTRACTION_MODEL: str = "gpt-4o-mini"
ANALYSIS_MODEL: str = "gpt-4o-mini"
EMBEDDING_MODEL: str = "text-embedding-3-small"

# ── Scraper ───────────────────────────────────────────────────────────────────
SCRAPER_MIN_CHARS: int = 300       # below this → trigger Playwright fallback
SCRAPER_TIMEOUT_SECONDS: int = 15

# Realistic browser headers for httpx requests
SCRAPER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH: str = "jobs.db"
RESUME_PATH: str = "resume.txt"
CREDENTIALS_PATH: str = "credentials.json"
TOKEN_PATH: str = "token.json"

# ── Dashboard ─────────────────────────────────────────────────────────────────
DASHBOARD_TITLE: str = "Job Intelligence Platform"
DASHBOARD_PORT: int = 7860
