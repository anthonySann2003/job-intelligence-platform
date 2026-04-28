import json
import gradio as gr
from job_search import search_jobs
from db import init_db, save_jobs, load_jobs, get_unscored_jobs, update_job_score
from resume import parse_resume
from scorer import score_job

init_db()

# Held in memory after parsing — scorer reads from here
parsed_resume = {}


def format_jobs(jobs: list[dict]) -> str:
    if not jobs:
        return "No jobs found."

    output = ""
    for i, job in enumerate(jobs, 1):
        salary = ""
        if job["salary_min"] and job["salary_max"]:
            salary = f"${job['salary_min']:,.0f} – ${job['salary_max']:,.0f}"
        elif job["salary_min"]:
            salary = f"From ${job['salary_min']:,.0f}"

        score_line = ""
        if job.get("score") is not None:
            score_line = f"⭐ Score: {job['score']}/100  |  {job.get('llm_summary', '')}\n"
            if job.get("missing_keywords"):
                missing = json.loads(job["missing_keywords"])
                score_line += f"❌ Missing: {', '.join(missing[:8])}\n"

        output += f"""
---
**{i}. {job['title']}** @ {job['company']}
📍 {job['location']}{"  |  💰 " + salary if salary else ""}
{score_line}🔗 [View Job]({job['url']})

{job['description'][:300]}...
"""
    return output.strip()


def run_search(keywords: str, location: str):
    if not keywords.strip():
        return "Please enter at least one keyword.", ""
    try:
        jobs = search_jobs(keywords, location)
    except Exception as e:
        return f"Error: {e}", ""

    inserted = save_jobs(jobs)
    status = f"✅ Found {len(jobs)} jobs — {inserted} new, {len(jobs) - inserted} already saved."
    return format_jobs(jobs), status


def show_saved():
    jobs = load_jobs()
    status = f"📦 {len(jobs)} jobs in database."
    return format_jobs(jobs), status


def upload_resume(file):
    global parsed_resume
    if file is None:
        return "No file uploaded.", ""
    try:
        parsed_resume = parse_resume(file.name)
        display = json.dumps(parsed_resume, indent=2)
        status = f"✅ Resume parsed for {parsed_resume.get('name', 'Unknown')} — ready to score."
        return status, display
    except Exception as e:
        return f"❌ Error: {e}", ""


def score_saved_jobs():
    """Score all unscored saved jobs, yielding progress after each one."""
    global parsed_resume

    if not parsed_resume:
        yield "❌ Parse your resume first.", ""
        return

    jobs = get_unscored_jobs()
    if not jobs:
        yield "✅ All saved jobs already scored. Load Saved Jobs to see results.", ""
        return

    results = []
    for i, job in enumerate(jobs, 1):
        status = f"⏳ Scoring job {i}/{len(jobs)}: {job['title']} @ {job['company']}..."
        yield status, ""

        try:
            result = score_job(parsed_resume, job)
            update_job_score(
                job_id=job["id"],
                score=result["score"],
                keywords=json.dumps(result.get("keywords", [])),
                missing_keywords=json.dumps(result.get("missing_keywords", [])),
                llm_summary=result.get("llm_summary", ""),
            )
            job.update({
                "score": result["score"],
                "keywords": json.dumps(result.get("keywords", [])),
                "missing_keywords": json.dumps(result.get("missing_keywords", [])),
                "llm_summary": result.get("llm_summary", ""),
            })
            results.append(job)
        except Exception as e:
            status = f"❌ Failed on {job['title']}: {e}"
            yield status, ""
            continue

    yield f"✅ Scored {len(results)}/{len(jobs)} jobs.", format_jobs(results)


with gr.Blocks(title="Job Dashboard") as app:
    gr.Markdown("# 🔍 Job Dashboard")

    with gr.Tab("Search"):
        with gr.Row():
            keywords = gr.Textbox(label="Keywords", placeholder="e.g. python data engineer")
            location = gr.Textbox(label="Location", placeholder="e.g. new york", value="new york")
        search_btn = gr.Button("Search", variant="primary")
        search_status = gr.Textbox(label="Status", interactive=False)
        search_results = gr.Markdown()
        search_btn.click(fn=run_search, inputs=[keywords, location], outputs=[search_results, search_status])

    with gr.Tab("Saved Jobs"):
        load_btn = gr.Button("Load Saved Jobs", variant="secondary")
        saved_status = gr.Textbox(label="Status", interactive=False)
        saved_results = gr.Markdown()
        load_btn.click(fn=show_saved, outputs=[saved_results, saved_status])

    with gr.Tab("Resume"):
        gr.Markdown("Upload your resume, then score it against all saved jobs.")
        pdf_upload = gr.File(label="Upload Resume (PDF)", file_types=[".pdf"])
        parse_btn = gr.Button("Parse Resume", variant="primary")
        resume_status = gr.Textbox(label="Status", interactive=False)
        resume_output = gr.Code(label="Parsed Resume (JSON)", language="json")
        parse_btn.click(fn=upload_resume, inputs=[pdf_upload], outputs=[resume_status, resume_output])

        gr.Markdown("---")
        score_btn = gr.Button("Score Saved Jobs", variant="primary")
        score_status = gr.Textbox(label="Scoring Status", interactive=False)
        score_results = gr.Markdown()
        score_btn.click(fn=score_saved_jobs, outputs=[score_status, score_results])

app.launch()