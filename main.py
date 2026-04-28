"""
main.py
-------
Orchestrates the full Job Intelligence Platform pipeline:
  1. Init DB
  2. Fetch job URLs from Gmail
  3. Scrape each URL
  4. Extract structured data via LLM
  5. Score against resume
  6. Run AI analysis on top N jobs
  7. Persist results + keyword frequencies + KPI
  8. Launch Gradio dashboard
"""

import time
from datetime import datetime

import database
import gmail_client
import scraper
import ai_engine
from config import TOP_N_FOR_ANALYSIS, SCORE_THRESHOLD


def run_pipeline() -> dict:
    """
    Execute the full pipeline end-to-end.
    Returns a summary dict with run stats for display.
    """
    print(f"\n{'='*60}")
    print(f"  Job Intelligence Platform — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. Init database
    print("[1/7] Initializing database...")
    database.init_db()

    # 2. Fetch URLs from Gmail
    print("[2/7] Fetching job emails from Gmail...")
    urls = gmail_client.get_job_urls()
    print(f"      Found {len(urls)} job URLs\n")

    if not urls:
        print("No job URLs found. Check your Gmail labels/filters.")
        return {}

    # 3–6. Process each job
    print("[3/7] Scraping + extracting + scoring jobs...\n")
    all_scores = []
    all_missing_keywords = []

    resume_text = ai_engine.load_resume()
    _ = ai_engine.get_resume_embedding()  # warm up cache

    for i, url in enumerate(urls, 1):
        print(f"  [{i}/{len(urls)}] {url[:70]}...")

        # Scrape
        raw_text = scraper.scrape_job(url)
        if not raw_text:
            print(f"         ⚠ Skipped — could not scrape content\n")
            continue

        # Extract
        job_data = ai_engine.extract_job_data(raw_text)
        if not job_data:
            print(f"         ⚠ Skipped — extraction failed\n")
            continue

        # Score
        score_data = ai_engine.score_job(job_data, raw_text)
        all_scores.append(score_data["final_score"])

        print(f"         ✓ {job_data.get('title', 'Unknown')} @ {job_data.get('company', '?')} — score: {score_data['final_score']:.1f}")

        # Save to DB (without analysis yet)
        database.upsert_job({**job_data, **score_data, "url": url, "raw_text": raw_text})

    # 5. AI analysis on top N
    print(f"\n[5/7] Running AI analysis on top {TOP_N_FOR_ANALYSIS} jobs...")
    top_jobs = database.get_all_jobs(min_score=0.0)[:TOP_N_FOR_ANALYSIS]

    for job in top_jobs:
        analysis = ai_engine.analyze_job(job, {}, resume_text)
        if analysis:
            missing = analysis.get("missing_keywords", [])
            all_missing_keywords.extend(missing)
            database.upsert_job({**dict(job), **analysis})
            print(f"  ✓ {job['title']} — {analysis.get('recommendation', '?')}")

    # 6. Keyword frequencies
    print("\n[6/7] Updating keyword frequency table...")
    if all_missing_keywords:
        database.update_keyword_frequencies(all_missing_keywords)

    # 7. KPI
    print("[7/7] Saving KPI snapshot...")
    jobs_processed = len(all_scores)
    match_rate = (
        sum(1 for s in all_scores if s >= SCORE_THRESHOLD) / jobs_processed * 100
        if jobs_processed else 0.0
    )
    top_kw = database.get_top_keywords(limit=1)
    top_missing = top_kw[0]["keyword"] if top_kw else "N/A"

    database.save_kpi_run(
        jobs_processed=jobs_processed,
        match_rate=round(match_rate, 1),
        top_missing_keyword=top_missing,
    )

    summary = {
        "jobs_processed": jobs_processed,
        "time_saved_minutes": jobs_processed * 15,
        "match_rate": match_rate,
        "top_missing_keyword": top_missing,
    }

    print(f"\n{'='*60}")
    print(f"  ✅ Pipeline complete!")
    print(f"     Jobs processed : {summary['jobs_processed']}")
    print(f"     Time saved     : {summary['time_saved_minutes']} minutes")
    print(f"     Match rate     : {summary['match_rate']:.1f}%")
    print(f"     Top gap        : {summary['top_missing_keyword']}")
    print(f"{'='*60}\n")

    return summary


if __name__ == "__main__":
    run_pipeline()

    from dashboard import launch_dashboard
    launch_dashboard()
