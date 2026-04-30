import os
import json
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI
from langsmith import traceable
from langsmith.wrappers import wrap_openai

load_dotenv()

client        = wrap_openai(OpenAI(api_key=os.getenv("OPENAI_API_KEY")))
RAPIDAPI_KEY  = os.getenv("RAPID_API_KEY")

JSEARCH_URL   = "https://jsearch.p.rapidapi.com/search"
JSEARCH_HEADERS = {
    "X-RapidAPI-Key":  RAPIDAPI_KEY,
    "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
}
MUSE_BASE_URL = "https://www.themuse.com/api/public/jobs"

# ── Constants ─────────────────────────────────────────────────────────────────

JSEARCH_EXPERIENCE_MAP = {
    "Internship":   "under_3_years_experience",
    "Entry-level":  "under_3_years_experience",
    "Mid-level":    "more_than_3_years_experience",
    "Senior-level": "more_than_3_years_experience",
    "Director":     "more_than_3_years_experience",
}

MUSE_LEVEL_MAP = {
    "Internship":   ["Internship"],
    "Entry-level":  ["Entry Level", "Internship"],
    "Mid-level":    ["Mid Level"],
    "Senior-level": ["Senior Level", "Management", "Director"],
    "Director":     ["Director", "VP", "Executive"],
}

CITY_MAP = {
    "AL": "Birmingham",    "AK": "Anchorage",     "AZ": "Phoenix",
    "AR": "Little Rock",   "CA": "San Francisco",  "CO": "Denver",
    "CT": "Hartford",      "DE": "Wilmington",     "FL": "Miami",
    "GA": "Atlanta",       "HI": "Honolulu",       "ID": "Boise",
    "IL": "Chicago",       "IN": "Indianapolis",   "IA": "Des Moines",
    "KS": "Wichita",       "KY": "Louisville",     "LA": "New Orleans",
    "ME": "Portland",      "MD": "Baltimore",      "MA": "Boston",
    "MI": "Detroit",       "MN": "Minneapolis",    "MS": "Jackson",
    "MO": "St. Louis",     "MT": "Billings",       "NE": "Omaha",
    "NV": "Las Vegas",     "NH": "Manchester",     "NJ": "Newark",
    "NM": "Albuquerque",   "NY": "New York",       "NC": "Charlotte",
    "ND": "Fargo",         "OH": "Columbus",       "OK": "Oklahoma City",
    "OR": "Portland",      "PA": "Philadelphia",   "RI": "Providence",
    "SC": "Charleston",    "SD": "Sioux Falls",    "TN": "Nashville",
    "TX": "Austin",        "UT": "Salt Lake City", "VT": "Burlington",
    "VA": "Richmond",      "WA": "Seattle",        "WV": "Charleston",
    "WI": "Milwaukee",     "WY": "Cheyenne",       "DC": "Washington",
}

BLOCKED_COMPANIES = {
    "walmart", "mcdonald's", "mcdonalds", "target", "kroger",
    "dollar general", "dollar tree", "walgreens", "cvs",
    "home depot", "lowes", "lowe's",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)


def _company_is_blocked(company: str) -> bool:
    return company.lower().strip() in BLOCKED_COMPANIES


def _build_muse_location(state: str) -> str:
    city = CITY_MAP.get(state.upper(), "")
    return f"{city}, {state.upper()}" if city else state.upper()


def _build_jsearch_query(job_titles: str, state: str) -> str:
    """
    Build a JSearch query string from job titles and state.
    Spreads multiple titles into a single OR query.
    e.g. "Data Engineer, ML Engineer" + "NY" ->
         "Data Engineer OR ML Engineer in New York"
    """
    city    = CITY_MAP.get(state.upper(), state)
    titles  = [t.strip() for t in job_titles.split(",") if t.strip()]
    if len(titles) > 1:
        title_str = " OR ".join(titles)
    else:
        title_str = titles[0] if titles else "software engineer"
    return f"{title_str} in {city}"

# ── LLM Filter ────────────────────────────────────────────────────────────────

@traceable(name="intent_filter_jobs", run_type="llm")
def _filter_jobs_by_llm(
    jobs: list[dict],
    job_titles: str,
    experience_level: str,
) -> list[dict]:
    """
    Single gpt-4o-mini call that filters a batch of jobs down to only
    genuinely relevant ones. Experience level used as a guide not a
    hard cutoff — LLM uses judgment on borderline cases.
    """
    if not jobs:
        return []

    job_list = "\n".join(
        f"{i}. {job['title']} @ {job['company']}"
        for i, job in enumerate(jobs)
    )

    prompt = f"""
You are a job relevance filter. The user is searching for:
- Target roles: {job_titles}
- Preferred experience level: {experience_level}

Below is a numbered list of job postings. Return the indices of jobs
that are genuinely relevant to what the user is looking for.

Relevance rules:
- Be inclusive — if a title is plausibly related to the target roles keep it
- Accept synonyms and related titles
- Use experience level as a GUIDE not a hard filter:
    For Internship/Entry-level: prefer internships and junior roles, accept
    mid-level if the title is a strong match, reject Director/VP/Senior Staff
    For Mid-level: prefer mid-level, accept senior if title matches well
    For Senior-level/Director: prefer senior and above, accept mid-level
    if title is a strong match
- Exclude jobs clearly unrelated to target roles regardless of level —
  retail, food service, manual labor, HR, legal, unrelated industries

Jobs:
{job_list}

Return ONLY valid JSON:
{{"relevant_indices": [0, 1, 4, ...]}}
"""

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            result  = json.loads(response.choices[0].message.content)
            indices = result.get("relevant_indices", [])
            valid   = [i for i in indices if isinstance(i, int) and 0 <= i < len(jobs)]

            print(f"[_filter_jobs_by_llm] {len(valid)}/{len(jobs)} jobs passed filter")
            for i in valid:
                print(f"  ✅ {jobs[i]['title']} @ {jobs[i]['company']}")

            return [jobs[i] for i in valid]

        except Exception as e:
            if attempt == 1:
                print(f"[_filter_jobs_by_llm] Failed after retry: {e}")
                return jobs  # fail open

# ── JSearch ───────────────────────────────────────────────────────────────────

def search_jobs_jsearch(
    job_titles: str,
    state: str,
    experience_level: str,
    results_per_page: int = 10,
) -> list[dict]:
    """
    Search JSearch (Google Jobs via RapidAPI).
    Returns jobs normalized to the same dict shape as save_jobs() expects.
    Plain text descriptions — no HTML stripping needed.
    Salary fields come back as floats or None — no parsing needed.
    """
    query       = _build_jsearch_query(job_titles, state)
    experience  = JSEARCH_EXPERIENCE_MAP.get(experience_level, "under_3_years_experience")

    print(f"[search_jobs_jsearch] query='{query}' experience='{experience}'")

    params = {
        "query":            query,
        "page":             "1",
        "num_pages":        "1",
        "job_requirements": experience,
        "employment_types": "FULLTIME,PARTTIME,INTERN",
    }

    try:
        response = requests.get(JSEARCH_URL, headers=JSEARCH_HEADERS, params=params)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[search_jobs_jsearch] API call failed: {e}")
        return []

    if data.get("status") != "OK":
        print(f"[search_jobs_jsearch] Bad status: {data.get('message', 'unknown error')}")
        return []

    raw_jobs = data.get("data", [])
    print(f"[search_jobs_jsearch] {len(raw_jobs)} raw jobs returned")

    jobs = []
    for job in raw_jobs:
        description = job.get("job_description", "")
        if not description:
            continue

        company = job.get("employer_name", "")
        if _company_is_blocked(company):
            continue

        url = job.get("job_apply_link", "")
        if not url:
            continue

        # Build location string from structured fields
        city  = job.get("job_city")  or ""
        state_field = job.get("job_state") or ""
        if city and state_field:
            location_str = f"{city}, {state_field}"
        elif job.get("job_is_remote"):
            location_str = "Remote"
        else:
            location_str = job.get("job_location", "")

        jobs.append({
            "title":       job.get("job_title", ""),
            "company":     company,
            "location":    location_str,
            "salary_min":  job.get("job_min_salary"),
            "salary_max":  job.get("job_max_salary"),
            "description": description,
            "url":         url,
            "created":     job.get("job_posted_at_datetime_utc", datetime.utcnow().isoformat()),
        })

    print(f"[search_jobs_jsearch] {len(jobs)} jobs after normalization")
    return jobs


# ── Muse (kept for future use) ────────────────────────────────────────────────

def search_jobs_muse(
    category: str,
    state: str,
    experience_level: str,
    job_titles: str = "",
    results_per_page: int = 10,
) -> list[dict]:
    """
    Muse search — kept in codebase for future use.
    Not called by run_agentic_search() unless added to sources list.
    """
    levels   = MUSE_LEVEL_MAP.get(experience_level, [])
    location = _build_muse_location(state)

    def _fetch(page: int = 1) -> tuple[list, int]:
        params = [
            ("category",   category),
            ("location",   location),
            ("page",       page),
            ("descending", "true"),
        ]
        response   = requests.get(MUSE_BASE_URL, params=params)
        response.raise_for_status()
        data       = response.json()
        return data.get("results", []), data.get("page_count", 1)

    jobs       = []
    page       = 1
    page_count = 1

    while page <= min(page_count, 10):
        batch, page_count = _fetch(page)
        if not batch:
            break

        for job in batch:
            url = job.get("refs", {}).get("landing_page", "")
            if not url:
                continue
            description = _strip_html(job.get("contents", ""))
            if not description:
                continue
            company    = job.get("company", {}).get("name", "")
            if _company_is_blocked(company):
                continue
            locations  = job.get("locations", [])
            levels_raw = job.get("levels", [])
            jobs.append({
                "title":       job.get("name", ""),
                "company":     company,
                "location":    locations[0].get("name", "") if locations else "",
                "level":       levels_raw[0].get("name", "") if levels_raw else "",
                "salary_min":  None,
                "salary_max":  None,
                "description": description,
                "url":         url,
                "created":     job.get("publication_date", datetime.utcnow().isoformat()),
            })

        if len(jobs) >= results_per_page * 3:
            break
        page += 1

    return jobs[:results_per_page]

# ── Orchestrator ──────────────────────────────────────────────────────────────

@traceable(name="run_agentic_search", run_type="tool")
def run_agentic_search(
    experience_level: str,
    category: str,
    state: str,
    notes: str,
    job_titles: str = "",
    sources: list = None,
) -> list[dict]:
    """
    Orchestrator entry point called by app.py.
    sources controls which APIs are active:
        ["jsearch"]         — JSearch only (default)
        ["muse"]            — Muse only
        ["jsearch", "muse"] — both combined
    """
    if sources is None:
        sources = ["jsearch"]

    print(f"[run_agentic_search] sources={sources} level='{experience_level}' "
          f"titles='{job_titles}' state='{state}'")

    raw_jobs = []

    if "jsearch" in sources:
        jsearch_jobs = search_jobs_jsearch(
            job_titles=job_titles,
            state=state,
            experience_level=experience_level,
            results_per_page=10,
        )
        raw_jobs.extend(jsearch_jobs)

    if "muse" in sources:
        muse_jobs = search_jobs_muse(
            category=category,
            state=state,
            experience_level=experience_level,
            job_titles=job_titles,
            results_per_page=10,
        )
        raw_jobs.extend(muse_jobs)

    print(f"[run_agentic_search] {len(raw_jobs)} total raw jobs before filter")

    # LLM filter — one call across all sources combined
    if raw_jobs:
        raw_jobs = _filter_jobs_by_llm(raw_jobs, job_titles, experience_level)

    # Deduplicate by URL
    seen        = set()
    unique_jobs = []
    for job in raw_jobs:
        url = job.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique_jobs.append(job)

    print(f"[run_agentic_search] {len(unique_jobs)} unique jobs ready for scoring")
    return unique_jobs