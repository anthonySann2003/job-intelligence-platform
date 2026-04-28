"""
scraper.py
----------
Fetches and parses job posting text from URLs.
Primary: httpx + BeautifulSoup
Fallback: Playwright (for JS-rendered pages)
"""

import httpx
from bs4 import BeautifulSoup
from config import SCRAPER_MIN_CHARS, SCRAPER_TIMEOUT_SECONDS, SCRAPER_HEADERS

# Tags to strip before extracting text
JUNK_TAGS = ["script", "style", "nav", "footer", "aside", "header", "noscript"]

# CSS selectors to target job content, tried in priority order
CONTENT_SELECTORS = [
    "main",
    "#content",
    ".job-description",
    ".posting-description",          # Lever
    '[data-qa="job-description"]',   # Greenhouse
    "article",
    ".content",
]


def scrape_with_httpx(url: str) -> str:
    """
    Fetch URL with httpx, strip junk tags, extract text from known selectors.
    Returns plain text of job posting, or empty string on failure.
    """
    pass


def scrape_with_playwright(url: str) -> str:
    """
    Fallback scraper using Playwright for JS-rendered pages.
    Only called when httpx result is below SCRAPER_MIN_CHARS.
    Returns plain text of job posting.
    """
    pass


def scrape_job(url: str) -> str:
    """
    Main entry point. Tries httpx first, falls back to Playwright if needed.
    Returns clean plain text of the job posting.
    """
    pass
