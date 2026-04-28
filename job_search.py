import os
import requests
from dotenv import load_dotenv

load_dotenv()

APP_ID = os.getenv("ADZUNA_APP_ID")
APP_KEY = os.getenv("ADZUNA_APP_KEY")
BASE_URL = "https://api.adzuna.com/v1/api/jobs"


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
        jobs.append({
            "title": job.get("title", ""),
            "company": job.get("company", {}).get("display_name", ""),
            "location": job.get("location", {}).get("display_name", ""),
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "description": job.get("description", ""),
            "url": job.get("redirect_url", ""),
            "created": job.get("created", ""),
        })

    return jobs