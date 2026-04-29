import json
import os
from openai import OpenAI
from dotenv import load_dotenv

from langsmith import traceable
from langsmith.wrappers import wrap_openai

load_dotenv()

client = wrap_openai(OpenAI(api_key=os.getenv("OPENAI_API_KEY")))

# ── Helpers ───────────────────────────────────────────────────────────────────

def _llm(prompt: str) -> dict:
    """
    Single shared LLM call used by all workers.
    Retries once on JSON parse failure, returns empty dict on second failure.
    All calls flow through the LangSmith-wrapped client so every worker's
    token usage and latency appears as a child span automatically.
    """
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except (json.JSONDecodeError, Exception) as e:
            if attempt == 1:
                print(f"[scorer] LLM call failed after retry: {e}")
                return {}

def _llmUpgraded(prompt: str) -> dict:
    """
    Single shared LLM call used by all workers using better LLM model.
    Retries once on JSON parse failure, returns empty dict on second failure.
    All calls flow through the LangSmith-wrapped client so every worker's
    token usage and latency appears as a child span automatically.
    """
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except (json.JSONDecodeError, Exception) as e:
            if attempt == 1:
                print(f"[scorer] LLM call failed after retry: {e}")
                return {}


def _get_yoe(resume: dict) -> float:
    """
    Read years of experience directly from the resume/profile dict.
    The user sets this manually in the Profile tab — never computed here.
    Falls back to 0 if not set so downstream workers still get a valid number.
    """
    yoe = resume.get("years_of_experience")
    try:
        return float(yoe) if yoe not in (None, "", "None") else 0.0
    except (ValueError, TypeError):
        return 0.0


def _normalise_skills(resume: dict) -> list:
    """
    Skills may be a list (from the LLM parser) or a comma-separated string
    (after the user edits them in the Profile tab). Always return a clean list.
    """
    skills = resume.get("skills", [])
    if isinstance(skills, str):
        return [s.strip() for s in skills.split(",") if s.strip()]
    return skills


# ── Worker A — Skill Extractor ─────────────────────────────────────────────────

@traceable(name="worker_a_extract_skills", run_type="llm")
def extract_skills(job: dict) -> dict:
    """
    Worker A: reads the raw job description and pulls out hard, measurable
    requirements. This runs first because Workers B and C both depend on its
    output. If it fails, downstream workers fall back to empty lists/nulls
    so the pipeline still completes rather than crashing.
    """
    prompt = f"""
You are an expert at parsing job descriptions for technical Computer Science and Engineering roles. Extract ONLY hard, measurable skills, requirements, tools, or platforms.

Return valid JSON with exactly these fields:
- required_skills: list of technical HARD skills/tools that are mandatory for position, NOT soft skills or buzz words
    Good skills to return: Python, SQL, R, Salesforce, LangChain, MCP, Agentic AI, CI/CD Pipelines
- preferred_skills: list of skills that are "nice to have" or "preferred"
- required_years: integer (number of years of experience required for the role, return 0 ONLY if there is no mention whatsoever of years of experience.
- required_degree: string (e.g. "bachelor's in CS"), or null if not mentioned
- required_certifications: list (empty if none)
- position_level: string (return the level of the position as one of these options: Internship, entry-level, mid-level, senior-level, or director)

Job Title: {job.get("title", "")}
Company: {job.get("company", "")}
Job Description:
{job.get("description", "")}
"""
    result = _llmUpgraded(prompt)
    return {
        "required_skills":         result.get("required_skills", []),
        "preferred_skills":        result.get("preferred_skills", []),
        "required_years":          result.get("required_years"),
        "required_degree":         result.get("required_degree"),
        "required_certifications": result.get("required_certifications", []),
        "position_level":          result.get("position_level", [])
    }


# ── Worker B — Keyword Score ───────────────────────────────────────────────────

@traceable(name="worker_b_keyword_score", run_type="llm")
def score_keywords(resume: dict, extracted: dict) -> dict:
    """
    Worker B: compares the candidate's skills (from the profile/resume table)
    against what Worker A pulled from the job. Skills are normalised from the
    resume dict so any edits made in the Profile tab are reflected here.
    """
    skills = _normalise_skills(resume)

    prompt = f"""
You are a skill-matching expert.

Resume skills: {json.dumps(skills)}
Required skills from job: {json.dumps(extracted.get("required_skills", []))}
Preferred skills from job: {json.dumps(extracted.get("preferred_skills", []))}

Scoring rules (apply exactly):
- Start score = 100
- For each required skill missing from resume: subtract 20 points
- For each preferred skill missing from resume: subtract 5 points
- For each matching skill from resume: add 10 points
- If required_skills list is empty, set keyword_score = 80
- Clamp final score between 0 and 100
- Consider synonyms (e.g. "K8s" = "kubernetes", "Postgres" = "postgresql")

Return JSON:
{{
  "keyword_score": integer,
  "matched_required": list,
  "missing_required": list,
  "matched_preferred": list,
  "missing_preferred": list,
  "reasoning": "brief explanation"
}}
"""
    result = _llm(prompt)
    return {
        "keyword_score":     int(result.get("keyword_score", 0)),
        "matched_required":  result.get("matched_required", []),
        "missing_required":  result.get("missing_required", []),
        "matched_preferred": result.get("matched_preferred", []),
        "missing_preferred": result.get("missing_preferred", []),
        "reasoning":         result.get("reasoning", ""),
    }


# ── Worker C — Experience & Qualifications Score ───────────────────────────────

@traceable(name="worker_c_experience_score", run_type="llm")
def score_experience(resume: dict, extracted: dict, job: dict) -> dict:
    """
    Worker C: holistic assessment of YOE, degree, certifications, and domain
    similarity. YOE is read from resume["years_of_experience"] — set by the
    user in the Profile tab, never computed. A clean resume snapshot is built
    for the prompt so the LLM sees the latest profile-edited values only.
    """
    yoe = _get_yoe(resume)

    # Send only the fields relevant to experience scoring — avoids sending
    # stale nested dicts from the original parse alongside profile edits.
    resume_for_prompt = {
        "name":                resume.get("name", ""),
        "summary":             resume.get("summary", ""),
        "skills":              _normalise_skills(resume),
        "certifications":      resume.get("certifications", []),
        "education":           resume.get("education", ""),
        "years_of_experience": yoe,
    }

    prompt = f"""
You are an experienced hiring manager evaluating a candidate.

Candidate profile:
{json.dumps(resume_for_prompt, indent=2)}

Job requirements:
- Years needed: {extracted.get("required_years", "not specified")}
- Degree needed: {extracted.get("required_degree", "not specified")}
- Certifications needed: {json.dumps(extracted.get("required_certifications", []))}
- Role Level: {json.dumps(extracted.get("position_level", "not specified"))}
- Role: {job.get("title", "")} at {job.get("company", "")}

Scoring rubric (apply exactly):
- Start score = 100
- If required_years is specified and candidate years of experience is less: subtract 10 for 1 year missing, 20 for 2 years missing, and set TOTAL SCORE to 0 if missing 3 or more years no matter what other rules you have.
- If required_degree is specified and not found in resume education: subtract 25
- For each required certification missing from resume: subtract 10
- If candidate's experience seems unrelated to this role's domain: subtract 15
- Clamp final score between 0 and 100

Return JSON:
{{
  "experience_fit": integer,
  "years_meet": boolean,
  "degree_meet": boolean,
  "certifications_meet": boolean,
  "similar_role_experience": "one sentence on domain relevance",
  "reasoning": "brief overall explanation"
}}
"""
    result = _llm(prompt)
    return {
        "experience_fit":          int(result.get("experience_fit", 0)),
        "years_meet":              result.get("years_meet", False),
        "degree_meet":             result.get("degree_meet", False),
        "certifications_meet":     result.get("certifications_meet", False),
        "similar_role_experience": result.get("similar_role_experience", ""),
        "reasoning":               result.get("reasoning", ""),
    }


# ── Worker D — Recruiter POV Score ────────────────────────────────────────────

@traceable(name="worker_d_recruiter_score", run_type="llm")
def score_recruiter(resume: dict, job: dict) -> dict:
    """
    Worker D: simulates a recruiter's gut-check. Reads YOE and skills directly
    from the resume/profile dict so any Profile tab edits are reflected here.
    """
    yoe    = _get_yoe(resume)
    skills = _normalise_skills(resume)

    description_snippet = job.get("description", "")[:500]

    prompt = f"""
You are a recruiter. Score this candidate (0-100) for the role below.

Candidate:
- Years of experience: {yoe}
- Top skills: {json.dumps(skills[:10])}
- Summary: "{resume.get("summary", "")}"

Job: {job.get("title", "")} at {job.get("company", "")}
Description snippet: {description_snippet}

Step 1 — Classify the role type: intern, junior, mid, senior, startup, or enterprise.
Step 2 — Score using these weights for that role type:

| Role type     | YOE weight | Education weight | Projects/Soft skills weight |
|---------------|------------|------------------|-----------------------------|
| Intern/Junior | 20%        | 40%              | 40%                         |
| Mid           | 40%        | 20%              | 40%                         |
| Senior        | 70%        | 5%               | 25%                         |
| Startup       | 30%        | 10%              | 60%                         |
| Enterprise    | 60%        | 30%              | 10%                         |

Return JSON:
{{
  "recruiter_score": integer,
  "is_internship_or_junior_role": boolean,
  "company_culture_indicators": list,
  "potential_judgment": "one sentence on candidate potential",
  "would_interview": boolean
}}
"""
    result = _llm(prompt)
    return {
        "recruiter_score":              int(result.get("recruiter_score", 0)),
        "is_internship_or_junior_role": result.get("is_internship_or_junior_role", False),
        "company_culture_indicators":   result.get("company_culture_indicators", []),
        "potential_judgment":           result.get("potential_judgment", ""),
        "would_interview":              result.get("would_interview", False),
    }


# ── Pipeline entry point ───────────────────────────────────────────────────────

@traceable(name="score_job", run_type="tool")
def score_job(resume: dict, job: dict) -> dict:
    """
    Runs all four workers in sequence and combines their scores into a single
    weighted final score.

    Weights:  keyword 20% | experience 45% | recruiter 35%

    YOE comes from resume["years_of_experience"] (set in the Profile tab).
    All workers receive the same resume dict so they always see the latest
    profile-edited values for skills, summary, certifications, and YOE.
    """

    yoe = _get_yoe(resume)

    extracted = extract_skills(job)
    kw        = score_keywords(resume, extracted)
    exp       = score_experience(resume, extracted, job)  # reads YOE internally
    rec       = score_recruiter(resume, job)              # reads YOE internally

    keyword_score    = kw.get("keyword_score", 0)
    experience_score = exp.get("experience_fit", 0)
    recruiter_score  = rec.get("recruiter_score", 0)

    final_score = round(
        (keyword_score    * 0.20) +
        (experience_score * 0.45) +
        (recruiter_score  * 0.35)
    )
    final_score = max(0, min(100, final_score))

    print("\n-----------------------------")
    print(f"Job: {job.get('title')} @ {job.get('company')}")
    print(f"YOE (from profile): {yoe}")
    print(f"Keyword Score:    {keyword_score}  (matched: {kw.get('matched_required')}, missing: {kw.get('missing_required')})")
    print(f"Experience Score: {experience_score}  ({exp.get('reasoning', '')})")
    print(f"Recruiter Score:  {recruiter_score}  (interview: {rec.get('would_interview')})")
    print(f"Final Score:      {final_score}")
    print("-----------------------------\n")

    missing_keywords = kw.get("missing_required", []) + kw.get("missing_preferred", [])
    matched_keywords = kw.get("matched_required", []) + kw.get("matched_preferred", [])

    return {
        # ── Columns the rest of the app already reads ──
        "score":            final_score,
        "keywords":         matched_keywords,
        "missing_keywords": missing_keywords,
        "llm_summary":      exp.get("reasoning") or rec.get("potential_judgment", ""),

        # ── Sub-scores available for future insights tab / judge ──
        "sub_scores": {
            "keyword_score":    keyword_score,
            "experience_score": experience_score,
            "recruiter_score":  recruiter_score,
            "yoe":              yoe,
            "extracted":        extracted,
            "would_interview":  rec.get("would_interview"),
            "kw_reasoning":     kw.get("reasoning"),
            "exp_reasoning":    exp.get("reasoning"),
            "rec_judgment":     rec.get("potential_judgment"),
        }
    }