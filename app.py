import json
import gradio as gr
from db import (
    init_db,
    save_jobs, load_jobs, get_unscored_jobs, update_job_score, clear_job_score,
    save_resume, load_resume,
)
from resume import parse_resume
from scorer import score_job
from intent import run_agentic_search

init_db()

# ── Session globals ────────────────────────────────────────────────────────────
parsed_resume: dict = load_resume() or {}

# ── Constants ─────────────────────────────────────────────────────────────────
US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

MUSE_CATEGORIES = [
    "Software Engineering",
    "Data and Analytics",
    "Computer and IT",
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def _resume_to_profile(resume: dict) -> dict:
    raw_edu = resume.get("education", [])
    if isinstance(raw_edu, str):
        education_str = raw_edu
    else:
        lines = []
        for edu in raw_edu:
            parts = []
            if edu.get("degree"):      parts.append(edu["degree"])
            if edu.get("institution"): parts.append(f"@ {edu['institution']}")
            if edu.get("end_date"):    parts.append(f"({edu['end_date']})")
            lines.append(" ".join(parts))
        education_str = "\n".join(lines)

    raw_exp = resume.get("experience", [])
    if isinstance(raw_exp, str):
        experience_str = raw_exp
    else:
        lines = []
        for exp in raw_exp:
            parts = []
            if exp.get("title"):   parts.append(exp["title"])
            if exp.get("company"): parts.append(f"@ {exp['company']}")
            dates = " – ".join(filter(None, [exp.get("start_date"), exp.get("end_date")]))
            if dates: parts.append(f"({dates})")
            lines.append(" ".join(parts))
        experience_str = "\n".join(lines)

    skills = resume.get("skills", [])
    certs  = resume.get("certifications", [])

    return {
        "name":                resume.get("name", ""),
        "email":               resume.get("email", ""),
        "summary":             resume.get("summary", ""),
        "skills":              ", ".join(skills) if isinstance(skills, list) else skills,
        "years_of_experience": resume.get("years_of_experience") or None,
        "certifications":      ", ".join(certs) if isinstance(certs, list) else certs,
        "education":           education_str,
        "experience":          experience_str,
        "professional_level":  resume.get("professional_level", ""),
    }


def _profile_fields_to_dict(
    name, email, summary, skills, yoe, certifications, education, experience, professional_level
) -> dict:
    try:
        yoe_clean = float(yoe) if yoe not in (None, "", "None") else None
    except (ValueError, TypeError):
        yoe_clean = None

    return {
        "name":                name,
        "email":               email,
        "summary":             summary,
        "skills":              [s.strip() for s in skills.split(",") if s.strip()],
        "years_of_experience": yoe_clean,
        "certifications":      [c.strip() for c in certifications.split(",") if c.strip()],
        "education":           education,
        "experience":          experience,
        "professional_level":  professional_level,
    }


# ── Search tab ─────────────────────────────────────────────────────────────────

def format_jobs(jobs: list[dict]) -> str:
    if not jobs:
        return "No jobs found."

    output = ""
    for i, job in enumerate(jobs, 1):

        # ── Salary line ───────────────────────────────────────────────────
        salary = ""
        if job.get("salary_min") and job.get("salary_max"):
            salary = f"💰 ${job['salary_min']:,.0f} – ${job['salary_max']:,.0f}"
        elif job.get("salary_min"):
            salary = f"💰 From ${job['salary_min']:,.0f}"

        # ── Score line ────────────────────────────────────────────────────
        score_line = ""
        if job.get("score") is not None:
            score      = job["score"]
            score_line = f"⭐ **Score: {score}/100**"

        # ── Summary line ──────────────────────────────────────────────────
        summary_line = ""
        if job.get("llm_summary"):
            summary_line = f"\n📋 {job['llm_summary']}"

        # ── Missing keywords ──────────────────────────────────────────────
        missing_line = ""
        if job.get("missing_keywords"):
            try:
                missing = json.loads(job["missing_keywords"])
            except (json.JSONDecodeError, TypeError):
                missing = []
            if missing:
                missing_line = f"\n❌ **Missing:** {', '.join(missing[:8])}"

        # ── Assemble card ─────────────────────────────────────────────────
        output += f"""
---
### {i}. {job['title']} @ {job['company']}
📍 {job['location']}{"   " + salary if salary else ""}{"   " + score_line if score_line else ""}
{summary_line}
{missing_line}

🔗 [View Job]({job['url']}) *(ID: {job.get('id', 'N/A')})*

"""
    return output.strip()


def run_search(
    experience_level: str,
    category: str,
    state: str,
    job_titles: str,
    notes: str,
):
    global parsed_resume

    # ── Input validation ───────────────────────────────────────────────────────
    if not experience_level:
        yield "Please select an experience level.", ""
        return
    if not category:
        yield "Please select a job category.", ""
        return
    if not state:
        yield "Please select a state.", ""
        return
    if not job_titles.strip():
        yield "Please enter at least one job title to filter results.", ""
        return

    # ── Step 1 — Search ────────────────────────────────────────────────────────
    yield "🔍 Searching for jobs...", ""

    try:
        jobs = run_agentic_search(
            experience_level=experience_level,
            category=category,
            state=state,
            notes=notes,
            job_titles=job_titles,
        )
    except Exception as e:
        yield f"❌ Search failed: {e}", ""
        return

    if not jobs:
        yield "No jobs found. Try different titles, category, or state.", ""
        return

    # ── Step 2 — Save to DB ────────────────────────────────────────────────────
    yield f"📥 Found {len(jobs)} jobs — saving to database...", ""
    inserted = save_jobs(jobs)

    if not parsed_resume:
        yield (
            f"✅ Done — {len(jobs)} jobs found, {inserted} new. "
            f"Upload a resume to score them.",
            format_jobs(jobs),
        )
        return

    # ── Step 3 — Score ─────────────────────────────────────────────────────────
    this_search_urls = {j["url"] for j in jobs}
    to_score = [j for j in get_unscored_jobs() if j["url"] in this_search_urls]

    if not to_score:
        yield (
            f"✅ {len(jobs)} jobs found, {inserted} new — all already scored.",
            format_jobs(jobs),
        )
        return

    yield (
        f"✅ {inserted} new jobs saved — scoring {len(to_score)} jobs...",
        "",
    )

    scored_jobs = []
    for i, job in enumerate(to_score, 1):
        yield (
            f"⏳ Scoring job {i}/{len(to_score)}: "
            f"{job['title']} @ {job['company']}...",
            format_jobs(scored_jobs) if scored_jobs else "",
        )
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
                "score":            result["score"],
                "keywords":         json.dumps(result.get("keywords", [])),
                "missing_keywords": json.dumps(result.get("missing_keywords", [])),
                "llm_summary":      result.get("llm_summary", ""),
            })
            scored_jobs.append(job)
        except Exception as e:
            print(f"[run_search] Scoring failed for {job['title']}: {e}")
            continue

    yield (
        f"✅ Done — scored {len(scored_jobs)}/{len(to_score)} jobs.",
        format_jobs(scored_jobs),
    )


def show_saved():
    jobs = load_jobs()
    return format_jobs(jobs), f"📦 {len(jobs)} jobs in database."


def clear_score(job_id_str: str):
    try:
        job_id = int(job_id_str)
    except ValueError:
        return "❌ Enter a valid numeric job ID.", show_saved()[0]
    clear_job_score(job_id)
    return f"✅ Score cleared for job ID {job_id}.", format_jobs(load_jobs())


# --- Show insights function
def show_insights():
    from db import get_insights
    data = get_insights()

    if data.get("empty"):
        return "No scored jobs yet — run a search and score some jobs first."

    total = data["total_scored"]
    dist  = data["distribution"]

    def _bar(count, total):
        filled = round((count / total) * 20) if total else 0
        return "█" * filled + "░" * (20 - filled)

    # ── Score distribution ─────────────────────────────────────────────────
    dist_md = f"""## 📊 Score Distribution
*{total} scored jobs total*

| Fit Level | Range | Jobs | Distribution |
|-----------|-------|------|--------------|
| 💚 Strong fit  | 80–100 | {dist['strong']}  | `{_bar(dist['strong'],  total)}` |
| 🟢 Good fit    | 66–79  | {dist['good']}    | `{_bar(dist['good'],    total)}` |
| 🟡 Partial fit | 50–65  | {dist['partial']} | `{_bar(dist['partial'], total)}` |
| 🔴 Poor fit    | 0–49   | {dist['poor']}    | `{_bar(dist['poor'],    total)}` |
"""

    # ── Missing keywords ───────────────────────────────────────────────────
    if data["top_missing"]:
        kw_rows = "\n".join(
            f"| {i+1}. | {kw.title()} | {count} job{'s' if count != 1 else ''} |"
            for i, (kw, count) in enumerate(data["top_missing"])
        )
        kw_md = f"""---
## ❌ Top Missing Keywords
*Skills appearing most often in your gaps — consider adding these to your resume*

| # | Keyword | Missing In |
|---|---------|------------|
{kw_rows}
"""
    else:
        kw_md = "---\n## ❌ Top Missing Keywords\nNo keyword data yet.\n"

    # ── Top scored jobs ────────────────────────────────────────────────────
    if data["top_jobs"]:
        job_rows = "\n".join(
            f"| {i+1}. | {job['title']} | {job['company']} | "
            f"{'💚' if job['score'] >= 80 else '🟢' if job['score'] >= 66 else '🟡' if job['score'] >= 50 else '🔴'} "
            f"{job['score']}/100 | [View]({job['url']}) |"
            for i, job in enumerate(data["top_jobs"])
        )
        jobs_md = f"""---
## ⭐ Top Scored Jobs
| # | Title | Company | Score | Link |
|---|-------|---------|-------|------|
{job_rows}
"""
    else:
        jobs_md = "---\n## ⭐ Top Scored Jobs\nNo scored jobs yet.\n"

    return dist_md + kw_md + jobs_md

# ── Resume tab ─────────────────────────────────────────────────────────────────

def upload_resume(file):
    global parsed_resume
    if file is None:
        return "No file uploaded.", ""
    try:
        parsed_resume = parse_resume(file.name)
        save_resume(parsed_resume, filename=file.name)
        status = f"✅ Resume parsed for {parsed_resume.get('name', 'Unknown')} — ready to score."
        return status, json.dumps(parsed_resume, indent=2)
    except Exception as e:
        return f"❌ Error: {e}", ""


def score_saved_jobs():
    global parsed_resume
    if not parsed_resume:
        yield "❌ Parse your resume first.", ""
        return
    jobs = get_unscored_jobs()
    if not jobs:
        yield "✅ All saved jobs already scored.", ""
        return
    results = []
    for i, job in enumerate(jobs, 1):
        yield f"⏳ Scoring job {i}/{len(jobs)}: {job['title']} @ {job['company']}...", ""
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
                "score":            result["score"],
                "keywords":         json.dumps(result.get("keywords", [])),
                "missing_keywords": json.dumps(result.get("missing_keywords", [])),
                "llm_summary":      result.get("llm_summary", ""),
            })
            results.append(job)
        except Exception as e:
            yield f"❌ Failed on {job['title']}: {e}", ""
            continue
    yield f"✅ Scored {len(results)}/{len(jobs)} jobs.", format_jobs(results)


# ── Profile tab ────────────────────────────────────────────────────────────────

def load_from_resume():
    if not parsed_resume:
        return ("", "", "", "", None, "", "", "", None,
                "❌ No resume loaded. Upload and parse your resume first.")
    p = _resume_to_profile(parsed_resume)
    return (
        p["name"],
        p["email"],
        p["summary"],
        p["skills"],
        p["years_of_experience"],
        p["certifications"],
        p["education"],
        p["experience"],
        p["professional_level"],
        "✅ Fields populated from resume — review and click Save Profile.",
    )


def handle_save_profile(
    name, email, summary, skills, yoe, certifications, education, experience, professional_level
):
    global parsed_resume
    edits = _profile_fields_to_dict(
        name, email, summary, skills, yoe, certifications,
        education, experience, professional_level
    )
    parsed_resume = {**parsed_resume, **edits}
    save_resume(parsed_resume)
    return "✅ Profile saved."


# ── UI ─────────────────────────────────────────────────────────────────────────

def _pf(key, default=""):
    val = parsed_resume.get(key, default)
    if isinstance(val, list):
        if val and isinstance(val[0], dict):
            return default
        return ", ".join(val)
    return val or default

_initial_profile = _resume_to_profile(parsed_resume) if parsed_resume else {}

with gr.Blocks(title="Job Intelligence Dashboard") as app:
    gr.Markdown("# 🔍 Job Intelligence Dashboard")

    with gr.Tab("Search"):
        gr.Markdown(
            "Fill in all fields below to search for jobs. "
            "Job Titles filters results to matching roles only."
        )

        with gr.Row():
            experience_level = gr.Dropdown(
                label="Experience Level",
                choices=["Internship", "Entry-level", "Mid-level", "Senior-level", "Director"],
                value="Entry-level",
            )
            category = gr.Dropdown(
                label="Job Category",
                choices=MUSE_CATEGORIES,
                value="Software Engineering",
            )
            state = gr.Dropdown(
                label="State",
                choices=US_STATES,
                value="NY",
            )

        job_titles = gr.Textbox(
            label="Job Titles (comma-separated — required, filters results)",
            placeholder="e.g. Data Engineer, ML Engineer, Software Engineer",
        )
        notes = gr.Textbox(
            label="Notes (optional)",
            placeholder="e.g. prefer AI-first companies, avoid consulting",
            lines=2,
        )

        search_btn     = gr.Button("Search", variant="primary")
        search_status  = gr.Textbox(label="Status", interactive=False)
        search_results = gr.Markdown()

        search_btn.click(
            fn=run_search,
            inputs=[experience_level, category, state, job_titles, notes],
            outputs=[search_status, search_results],
        )

    #--- Insights tab ---
    with gr.Tab("Insights"):
        gr.Markdown(
            "Aggregate insights across all your scored jobs. "
            "Run a search and score jobs first to see data here."
        )
        insights_btn     = gr.Button("Load Insights", variant="primary")
        insights_output  = gr.Markdown()
        insights_btn.click(fn=show_insights, outputs=[insights_output])

    with gr.Tab("Saved Jobs"):
        load_btn      = gr.Button("Load Saved Jobs", variant="secondary")
        saved_status  = gr.Textbox(label="Status", interactive=False)
        saved_results = gr.Markdown()
        load_btn.click(fn=show_saved, outputs=[saved_results, saved_status])

        gr.Markdown("---")
        gr.Markdown("**🧪 Testing — Clear Score by Job ID**")
        with gr.Row():
            clear_id_input = gr.Textbox(label="Job ID", scale=1, placeholder="e.g. 42")
            clear_btn      = gr.Button("Clear Score", variant="stop", scale=1)
        clear_btn.click(
            fn=clear_score,
            inputs=[clear_id_input],
            outputs=[saved_status, saved_results],
        )

    with gr.Tab("Resume"):
        gr.Markdown("Upload your resume, then score it against all saved jobs.")
        resume_status = gr.Textbox(
            label="Status",
            interactive=False,
            value=(
                f"✅ Resume loaded from previous session ({parsed_resume.get('name', '')})."
                if parsed_resume else ""
            ),
        )
        pdf_upload    = gr.File(label="Upload Resume (PDF)", file_types=[".pdf"])
        parse_btn     = gr.Button("Parse Resume", variant="primary")
        resume_output = gr.Code(label="Parsed Resume (JSON)", language="json")
        parse_btn.click(
            fn=upload_resume,
            inputs=[pdf_upload],
            outputs=[resume_status, resume_output],
        )

        gr.Markdown("---")
        score_btn     = gr.Button("Score Saved Jobs", variant="primary")
        score_status  = gr.Textbox(label="Scoring Status", interactive=False)
        score_results = gr.Markdown()
        score_btn.click(fn=score_saved_jobs, outputs=[score_status, score_results])

    with gr.Tab("Profile"):
        gr.Markdown(
            "Edit your profile below — changes here update the resume the scorer uses. "
            "Click **Load from Resume** to re-seed from the latest parsed PDF, "
            "or edit directly and click **Save Profile**."
        )
        profile_status = gr.Textbox(label="Status", interactive=False)

        with gr.Row():
            load_resume_btn  = gr.Button("Load from Resume", variant="secondary")
            save_profile_btn = gr.Button("Save Profile", variant="primary")

        gr.Markdown("---")
        gr.Markdown("### Basic Info")
        with gr.Row():
            prof_name  = gr.Textbox(label="Name",  value=parsed_resume.get("name", ""))
            prof_email = gr.Textbox(label="Email", value=parsed_resume.get("email", ""))

        prof_summary = gr.Textbox(
            label="Professional Summary",
            lines=4,
            value=parsed_resume.get("summary", ""),
        )

        gr.Markdown("### Skills & Credentials")
        gr.Markdown("*Comma-separated — these feed directly into keyword scoring.*")
        with gr.Row():
            prof_skills = gr.Textbox(
                label="Skills (comma-separated)",
                lines=3,
                value=_pf("skills"),
            )
            prof_certs = gr.Textbox(
                label="Certifications (comma-separated)",
                lines=3,
                value=_pf("certifications"),
            )

        prof_yoe = gr.Number(
            label="Years of Experience (manual override)",
            value=parsed_resume.get("years_of_experience") or None,
            precision=1,
        )

        prof_level = gr.Dropdown(
            label="Professional Level",
            choices=["Internship", "Entry-level", "Mid-level", "Senior-level", "Director"],
            value=parsed_resume.get("professional_level") or None,
        )

        gr.Markdown("### Education")
        gr.Markdown("*One entry per line, e.g. `BSc Computer Science @ University X (2019)`*")
        prof_education = gr.Textbox(
            label="Education",
            lines=4,
            value=_initial_profile.get("education", ""),
        )

        gr.Markdown("### Experience")
        gr.Markdown("*One role per line, e.g. `Software Engineer @ TechCorp (2020-01 – 2024-01)`*")
        prof_experience = gr.Textbox(
            label="Experience",
            lines=6,
            value=_initial_profile.get("experience", ""),
        )

        _all_fields = [
            prof_name, prof_email, prof_summary,
            prof_skills, prof_yoe, prof_certs,
            prof_education, prof_experience, prof_level,
        ]

        load_resume_btn.click(
            fn=load_from_resume,
            outputs=[*_all_fields, profile_status],
        )
        save_profile_btn.click(
            fn=handle_save_profile,
            inputs=_all_fields,
            outputs=profile_status,
        )

app.launch()