#!/usr/bin/env python3
"""
Quick test: paste a job URL and see if BeautifulSoup can extract the text.
Falls back to Playwright if the page needs JavaScript.

Setup (run once):
    pip install httpx beautifulsoup4 playwright
    playwright install chromium
"""

import asyncio
import sys
import httpx
from bs4 import BeautifulSoup

# Tags that are pure noise — strip these entirely
JUNK_TAGS = ["script", "style", "nav", "header", "footer",
             "noscript", "iframe", "svg", "form", "aside"]

def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(JUNK_TAGS):
        tag.decompose()

    # Try to find the main content block first
    main = (
        soup.find("main") or
        soup.find(id="content") or
        soup.find(class_="job-description") or
        soup.find(class_="posting-description") or  # Lever
        soup.find(attrs={"data-qa": "job-description"}) or  # Greenhouse
        soup.find(class_="jobsearch-jobDescriptionText") or  # Indeed-style
        soup.body
    )

    text = main.get_text(separator="\n") if main else soup.get_text(separator="\n")
    # Clean up whitespace
    lines = [l.strip() for l in text.splitlines()]
    lines = [l for l in lines if l]
    return "\n".join(lines)


async def fetch_with_httpx(url: str) -> str | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        text = extract_text(r.text)
        return text if len(text) > 300 else None


async def fetch_with_playwright(url: str) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return "[Playwright not installed — run: pip install playwright && playwright install chromium]"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=20000)
        html = await page.content()
        await browser.close()
        return extract_text(html)


async def main(url: str):
    print(f"\n{'='*60}")
    print(f"Testing URL: {url}")
    print(f"{'='*60}\n")

    print("→ Trying httpx (fast, no JS)...")
    try:
        text = await fetch_with_httpx(url)
        if text:
            print(f"✓ httpx SUCCESS — got {len(text)} characters\n")
            print("--- First 1500 chars of extracted text ---\n")
            print(text[:1500])
            print("\n--- Last 500 chars ---\n")
            print(text[-500:])
            return
        else:
            print("✗ httpx returned too little text (JS-rendered page?)\n")
    except Exception as e:
        print(f"✗ httpx failed: {e}\n")

    print("→ Falling back to Playwright (slower, handles JS)...")
    try:
        text = await fetch_with_playwright(url)
        print(f"✓ Playwright result — got {len(text)} characters\n")
        print("--- First 1500 chars of extracted text ---\n")
        print(text[:1500])
        print("\n--- Last 500 chars ---\n")
        print(text[-500:])
    except Exception as e:
        print(f"✗ Playwright also failed: {e}")


if __name__ == "__main__":
    # Read from url.txt if no argument given (avoids PowerShell & issues)
    if len(sys.argv) < 2:
        try:
            with open("url.txt") as f:
                url = f.read().strip()
            print(f"Read URL from url.txt")
        except FileNotFoundError:
            print("Usage: python test_scraper.py <job-url>")
            print("   OR: paste your URL into a file called url.txt and run: python test_scraper.py")
            sys.exit(1)
    else:
        url = sys.argv[1]

    asyncio.run(main(url))
