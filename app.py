import json
import gradio as gr
from job_search import search_jobs
from db import init_db, save_jobs, load_jobs
from resume import parse_resume

# Make sure the table exists when the app starts
init_db()


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

        output += f"""
---
**{i}. {job['title']}** @ {job['company']}
📍 {job['location']}{"  |  💰 " + salary if salary else ""}
🔗 [View Job]({job['url']})

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
    if file is None:
        return "No file uploaded.", ""

    try:
        parsed = parse_resume(file.name)
        # Pretty print JSON for display
        display = json.dumps(parsed, indent=2)
        status = f"✅ Resume parsed for {parsed.get('name', 'Unknown')}"
        return status, display
    except Exception as e:
        return f"❌ Error: {e}", ""


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
        gr.Markdown("Upload your resume PDF to parse and structure it.")
        pdf_upload = gr.File(label="Upload Resume (PDF)", file_types=[".pdf"])
        parse_btn = gr.Button("Parse Resume", variant="primary")
        resume_status = gr.Textbox(label="Status", interactive=False)
        resume_output = gr.Code(label="Parsed Resume (JSON)", language="json")

        parse_btn.click(fn=upload_resume, inputs=[pdf_upload], outputs=[resume_status, resume_output])

app.launch()