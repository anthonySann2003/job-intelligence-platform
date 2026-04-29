import os
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("ADZUNA_APP_ID")
APP_KEY = os.getenv("ADZUNA_APP_KEY")
BASE_URL = "https://api.adzuna.com/v1/api/jobs"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def scrape_full_description(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=10)
    if response.status_code != 200:
        raise ValueError(f"Bad status: {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)

    if len(text) < 200:
        raise ValueError("Page text too short, likely blocked")

    return text


def search_jobs(keywords: str, location: str = "new york", results_per_page: int = 10) -> list[dict]:
    url = f"{BASE_URL}/us/search/1"
    params = {
        "app_id": APP_ID,
        "app_key": APP_KEY,
        "what": keywords,
        "where": location,
        "results_per_page": results_per_page,
        "content-type": "application/json",
    }

    response = requests.get(url, params=params)
    response.raise_for_status()

    jobs = []
    for job in response.json().get("results", []):
        job_dict = {
            "title": job.get("title", ""),
            "company": job.get("company", {}).get("display_name", ""),
            "location": job.get("location", {}).get("display_name", ""),
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "description": job.get("description", ""),
            "url": job.get("redirect_url", ""),
            "created": job.get("created", ""),
        }

        # Attempt to scrape full description
        try:
            job_dict["description"] = scrape_full_description(job_dict["url"])
        except Exception:
            continue

        jobs.append(job_dict)

    return jobs