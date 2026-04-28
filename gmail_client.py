"""
gmail_client.py
---------------
Gmail API OAuth2 authentication and job email fetching.
Extracts job posting URLs from email bodies.
"""

from typing import Optional
from config import GMAIL_SCOPES, GMAIL_SEARCH_QUERY, GMAIL_MAX_RESULTS, CREDENTIALS_PATH, TOKEN_PATH


def get_gmail_service():
    """
    Authenticate via OAuth2 and return an authorized Gmail API service object.
    On first run, opens a browser window for user consent and saves token.json.
    Subsequent runs use the cached token (auto-refreshed when expired).
    """
    pass


def fetch_job_emails(service) -> list[dict]:
    """
    Search Gmail for job alert emails matching GMAIL_SEARCH_QUERY.
    Returns a list of email dicts with keys: id, subject, body.
    """
    pass


def extract_urls_from_email(body: str) -> list[str]:
    """
    Extract all http/https URLs from raw email body text.
    Filters out unsubscribe links, tracking pixels, and known non-job domains.
    Returns a deduplicated list of candidate job posting URLs.
    """
    pass


def get_job_urls(max_results: int = GMAIL_MAX_RESULTS) -> list[str]:
    """
    Main entry point: authenticate, fetch emails, extract and return all job URLs.
    This is what main.py calls.
    """
    pass
