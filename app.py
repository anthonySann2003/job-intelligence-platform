import json
import gradio as gr
from job_search import search_jobs
from db import (
    init_db,
    save_jobs, load_jobs, get_unscored_jobs, update_job_score, clear_job_score,
    save_resume, load_resume,
)
from resume import parse_resume
from scorer import score_job

init_db()

# ── Session globals ────────────────────────────────────────────────────────────
# Single source of truth — the resumes table. Profile tab reads and writes here
# too, so there is no separate profile record to keep in sync.

parsed_resume: dict = load_resume() or {}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _resume_to_profile(resume: dict) -> dict:
    """
    Flatten the nested resume dict into display-friendly strings for the
    Profile tab fields. Education and experience dicts become one-per-line
    strings the user can read and edit directly.
    """
    # Education — already a plain string after a profile save, else list of dicts
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

    # Experience — same dual-form handling
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
    }


def _profile_fields_to_dict(
    name, email, summary, skills, yoe, certifications, education, experience
) -> dict:
    """
    Pack Gradio field values back into a dict that can be merged into
    parsed_resume. Skills and certifications are split from comma-separated
    strings into lists so the scorer can consume them directly.
    """
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
    }


# ── Search tab ─────────────────────────────────────────────────────────────────

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
**{i}. {job['title']}** @ {job['company']} *(ID: {job['id']})*
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


def clear_score(job_id_str: str):
    try:
        job_id = int(job_id_str)
    except ValueError:
        return "❌ Enter a valid numeric job ID.", show_saved()[0]
    clear_job_score(job_id)
    jobs = load_jobs()
    return f"✅ Score cleared for job ID {job_id}.", format_jobs(jobs)


# ── Resume tab ─────────────────────────────────────────────────────────────────

def upload_resume(file):
    global parsed_resume
    if file is None:
        return "No file uploaded.", ""
    try:
        parsed_resume = parse_resume(file.name)
        save_resume(parsed_resume, filename=file.name)
        display = json.dumps(parsed_resume, indent=2)
        status = f"✅ Resume parsed for {parsed_resume.get('name', 'Unknown')} — ready to score."
        return status, display
    except Exception as e:
        return f"❌ Error: {e}", ""


def score_saved_jobs():
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
    """
    Populate all profile fields from the current in-memory parsed_resume.
    Does NOT save — user reviews the fields and clicks Save Profile themselves.
    """
    if not parsed_resume:
        return ("", "", "", "", None, "", "", "", "❌ No resume loaded. Upload and parse your resume first.")
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
        "✅ Fields populated from resume — review and click Save Profile.",
    )


def handle_save_profile(name, email, summary, skills, yoe, certifications, education, experience):
    """
    Merge the edited field values back into parsed_resume and write to the
    resumes table. Single save, single table — no sync required.
    The raw nested experience/education dicts are preserved on parsed_resume
    since the profile tab doesn't expose them in structured form.
    """
    global parsed_resume

    edits = _profile_fields_to_dict(
        name, email, summary, skills, yoe, certifications, education, experience
    )

    # Merge edits onto the existing resume dict so unexposed fields are kept
    parsed_resume = {**parsed_resume, **edits}
    save_resume(parsed_resume)

    return "✅ Profile saved."


# ── UI ─────────────────────────────────────────────────────────────────────────

# Helper to safely read a flat field from parsed_resume for initial field values,
# handling both list-of-strings and plain string forms (skills, certs).
# Do NOT use for education/experience — those are lists of dicts and need
# _resume_to_profile() to flatten them properly.
def _pf(key, default=""):
    val = parsed_resume.get(key, default)
    if isinstance(val, list):
        # Guard: if it's a list of dicts (education/experience), return default
        if val and isinstance(val[0], dict):
            return default
        return ", ".join(val)
    return val or default

# Pre-flatten education and experience for initial UI field values.
# After a profile save these fields are stored as plain strings, but on first
# load from the parser they are lists of dicts — _resume_to_profile handles both.
_initial_profile = _resume_to_profile(parsed_resume) if parsed_resume else {}


with gr.Blocks(title="Job Dashboard") as app:
    gr.Markdown("# 🔍 Job Dashboard")

    # ── Search ──────────────────────────────────────────────────────────────────
    with gr.Tab("Search"):
        with gr.Row():
            keywords = gr.Textbox(label="Keywords", placeholder="e.g. python data engineer")
            location = gr.Textbox(label="Location", placeholder="e.g. new york", value="new york")
        search_btn     = gr.Button("Search", variant="primary")
        search_status  = gr.Textbox(label="Status", interactive=False)
        search_results = gr.Markdown()
        search_btn.click(fn=run_search, inputs=[keywords, location], outputs=[search_results, search_status])

    # ── Saved Jobs ──────────────────────────────────────────────────────────────
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
        clear_btn.click(fn=clear_score, inputs=[clear_id_input], outputs=[saved_status, saved_results])

    # ── Resume ──────────────────────────────────────────────────────────────────
    with gr.Tab("Resume"):
        gr.Markdown("Upload your resume, then score it against all saved jobs.")
        resume_status = gr.Textbox(
            label="Status",
            interactive=False,
            value=f"✅ Resume loaded from previous session ({parsed_resume.get('name', '')})." if parsed_resume else "",
        )
        pdf_upload    = gr.File(label="Upload Resume (PDF)", file_types=[".pdf"])
        parse_btn     = gr.Button("Parse Resume", variant="primary")
        resume_output = gr.Code(label="Parsed Resume (JSON)", language="json")
        parse_btn.click(fn=upload_resume, inputs=[pdf_upload], outputs=[resume_status, resume_output])

        gr.Markdown("---")
        score_btn     = gr.Button("Score Saved Jobs", variant="primary")
        score_status  = gr.Textbox(label="Scoring Status", interactive=False)
        score_results = gr.Markdown()
        score_btn.click(fn=score_saved_jobs, outputs=[score_status, score_results])

    # ── Profile ─────────────────────────────────────────────────────────────────
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
            prof_education, prof_experience,
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