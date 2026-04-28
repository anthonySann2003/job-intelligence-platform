import gradio as gr
from job_search import search_jobs


def run_search(keywords: str, location: str):
    if not keywords.strip():
        return "Please enter at least one keyword."

    try:
        jobs = search_jobs(keywords, location)
    except Exception as e:
        return f"Error: {e}"

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


with gr.Blocks(title="Job Dashboard") as app:
    gr.Markdown("# 🔍 Job Search")

    with gr.Row():
        keywords = gr.Textbox(label="Keywords", placeholder="e.g. python data engineer")
        location = gr.Textbox(label="Location", placeholder="e.g. new york", value="new york")

    search_btn = gr.Button("Search", variant="primary")
    results = gr.Markdown(label="Results")

    search_btn.click(fn=run_search, inputs=[keywords, location], outputs=results)

app.launch()