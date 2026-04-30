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
    yoe = resume.get("years_of_experience")
    try:
        return float(yoe) if yoe not in (None, "", "None") else 0.0
    except (ValueError, TypeError):
        return 0.0


def _normalise_skills(resume: dict) -> list:
    skills = resume.get("skills", [])
    if isinstance(skills, str):
        return [s.strip() for s in skills.split(",") if s.strip()]
    return skills


@traceable(name="summarize_job", run_type="llm")
def summarize_job(job: dict) -> str:
    """
    Single gpt-4o-mini call that reads the job description and returns
    a clean 2-3 sentence summary of what the role is.
    Describes the job itself — not candidate fit.
    """
    prompt = f"""
You are a job summarizer. Read the job posting below and write a concise
2-3 sentence summary describing what the role is, what the company does,
and what the main focus of the work will be.

Write in plain English. Do not mention the candidate, scoring, or fit.
Do not use bullet points. Just 2-3 clean sentences.

Job Title: {job.get("title", "")}
Company: {job.get("company", "")}
Description:
{job.get("description", "")[:3000]}

Return ONLY valid JSON:
{{"summary": "2-3 sentence summary here"}}
"""
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
            return result.get("summary", "")
        except Exception as e:
            if attempt == 1:
                print(f"[summarize_job] Failed after retry: {e}")
                return ""


# ── Worker A — Skill Extractor ─────────────────────────────────────────────────

@traceable(name="worker_a_extract_skills", run_type="llm")
def extract_skills(job: dict) -> dict:
    prompt = f"""
<role>
You are an expert technical recruiter and job description analyst. Your job is to extract structured requirements from a job posting with high precision. You only extract what is explicitly stated — you never infer or assume requirements that are not directly written in the posting.
</role>

<job_information>
Job Title: {job.get("title", "")}
Company: {job.get("company", "")}
Job Description:
{job.get("description", "")}
</job_information>

<instructions>
You will extract structured data from the job posting above in two passes.

PASS 1 — QUOTE EXTRACTION:
Read the job description carefully and pull out the exact sentences or phrases that mention each of the following. If nothing in the description mentions a category, write "not mentioned" for that category.

- Skills and tools: exact phrases that list required or preferred technical skills, tools, platforms, or languages
- Experience: exact phrases that mention years of experience
- Education: exact phrases that mention degree requirements
- Certifications: exact phrases that mention required or preferred certifications
- Seniority: exact phrases that indicate the level of the role (e.g. "senior", "entry level", "intern", "3+ years")

PASS 2 — STRUCTURED EXTRACTION:
Using ONLY the quoted phrases from Pass 1 as your source, extract the following fields. Do not use any information from the job description that you did not quote in Pass 1.

Fields to extract:
- required_skills: technical HARD skills, tools, platforms, or languages that are explicitly stated as mandatory or required. Do NOT include soft skills, personality traits, or buzzwords.
    Good examples: Python, SQL, React, AWS, Docker, LangChain, CI/CD, Kubernetes
    Bad examples: "strong communicator", "team player", "fast learner", "problem solver"
- preferred_skills: technical skills explicitly described as "preferred", "nice to have", "a plus", or "bonus"
- required_years: integer of years of experience explicitly stated. Return 0 ONLY if years of experience are not mentioned anywhere in the posting.
- required_degree: the exact degree requirement as a string (e.g. "Bachelor's in Computer Science"), or null if not mentioned
- required_certifications: list of certifications explicitly named in the posting, empty list if none
- position_level: classify the role as exactly one of these options based only on what the posting states: Internship, entry-level, mid-level, senior-level, director
</instructions>

<critical_rules>
- Every field in Pass 2 must be grounded in a quote from Pass 1. If you did not quote it, do not extract it.
- Never infer a skill because it seems likely for the role type. Only extract what is written.
- Never add soft skills to required_skills or preferred_skills under any circumstances.
- If required_years is ambiguous or not stated, return 0.
- If position_level is not explicitly stated, infer it only from the job title, not from the description.
</critical_rules>

<output_format>
Return only valid JSON with exactly these fields:
{{
  "pass1_quotes": {{
    "skills_quotes": "exact quoted text or not mentioned",
    "experience_quotes": "exact quoted text or not mentioned",
    "education_quotes": "exact quoted text or not mentioned",
    "certifications_quotes": "exact quoted text or not mentioned",
    "seniority_quotes": "exact quoted text or not mentioned"
  }},
  "required_skills": list,
  "preferred_skills": list,
  "required_years": integer,
  "required_degree": string or null,
  "required_certifications": list,
  "position_level": "Internship | entry-level | mid-level | senior-level | director"
}}
</output_format>
"""
    result = _llmUpgraded(prompt)
    return {
        "required_skills":         result.get("required_skills", []),
        "preferred_skills":        result.get("preferred_skills", []),
        "required_years":          result.get("required_years"),
        "required_degree":         result.get("required_degree"),
        "required_certifications": result.get("required_certifications", []),
        "position_level":          result.get("position_level", ""),
        "pass1_quotes":            result.get("pass1_quotes", {}),
    }

# ── Worker B — Keyword Score ───────────────────────────────────────────────────

@traceable(name="worker_b_keyword_score", run_type="llm")
def score_keywords(resume: dict, extracted: dict) -> dict:
    skills = _normalise_skills(resume)

    prompt = f"""
<role>
You are acting as a very harsh and brutally honest keyword scoring machine comparing a job description and candidate's resume and you always follow the same order of operations provided below:
</role>

<rules>
General Rules When Scoring:
- You are a scrutinizing scorer in favor of the job and against the candidate
- Final score must be between 0 and 100
- Each rubric is a seperate score, judge the required skills individually from the preferred skills
- A 65-70 in the required skills means the candidate is missing no required skills, and a 25-30 in the preferred means the candidate is missing no preferred skills.
- You are a harsh and critical scoring system with emphasis on being unbiased and purely data centric
- If required_skills list is empty, set the total keyword_score to 80
- If preferred_skills list is empty, set the total preferred_skills score to 15
- Consider synonyms (e.g. "K8s" = "kubernetes", "Postgres" = "postgresql")
</rules>

<instructions>
<required_skills_instructions>
1. As a crticial and ubiased keyword scoring machine, score the required skills for the job versus the candidate's skills according to the rubric below with 70 being a perfect score for required skills and 0 being the worst score possible:
65-70 points = The candidate has all or almost all of the required skills for the position, but any missing skills are somewhat related to the candidate's skills (IDEAL CANDIDATE).
60-65 points = The candidate has most or half of the required skills for the position, and any missing skills are unrelated to the candidate's skills (GOOD CANDIDATE).
55-60 points = The candidate only has half or some of the required skills for the position, but the missing skills are somewhat related to the candidate's skills (POTENTIAL CANDIDATE).
45-55 points = The candidate only has half or some of the required skills for the position, and the missing skills are unrelated to the candidate's skills (MEDIORCRE CANDIDATE).
35-45 points = The candidate is missing most of the required skills, but most of the missing skills are somewhat related to the candidate's skills (UNLIKELY CANDIDATE).
15-35 points = The candidate is missing most of the required skills, and the missing skills are mostly unrelated to the candidate's skills (REJECTED CANDIDATE).
0-15 points = The candidate is missing most or all of required skills, and the missing skills are mostly unrelated to the candidate's skills (IMPOSSIBLE CANDIDATE).

Required skills for job: {json.dumps(extracted.get("required_skills", []))}
Candidate's skills: {json.dumps(skills)}

After scoring the required skills, cite the exact points range you went with and the reasoning for it in the reasoning json field.
</required_skills_instructions>

<preferred_skills_instructions>
2. As a crticial and ubiased keyword scoring machine, score the preferred skills for the job versus the candidate's skills according to the rubric below with 30 being a perfect score for preferred skills and 0 being the worst: 
25-30 points = The candidate has all or almost all of the preferred skills for the position, and any missing skills are somewhat related to the candidate's skills (IDEAL CANDIDATE).
20-25 points = The candidate has some or more than half of the preferred skills, and missing skills are somewhat related to the candidate's skills (GOOD CANDIDATE). 
10-20 points = The candidate has half or less than half of the preferred skills, and the missing skills are mostly unrelated to the candidate's skills (MEDIOCRE CANDIDATE)
0-10 points = The candidate is missing most or all of the preferred skills, and missing skills are mostly unrelated to the candidate's skills (REJECTED CANDIDATE).

Preferred skills for job: {json.dumps(extracted.get("preferred_skills", []))}
Candidate's skills: {json.dumps(skills)}

After scoring the preferred skills, cite the exact points range you went with and the reasoning for it in the reasoning json field combined with your reasoning from the required skills section.
</preferred_skills_instructions>

3. After scoring both the required and preferred skills against the candidate's skills, add together the points from each and return the final result in the keyword_score json field.
Also fill out the matched_required, missing_required, matched_preferred, missing_preferred lists accordingly.
</instructions>

Return JSON:
{{
  "keyword_score": integer,
  "matched_required": list,
  "missing_required": list,
  "matched_preferred": list,
  "missing_preferred": list,
  "reasoning": "brief explanation of reasoning with specific point ranges cited"
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


# ── Worker C Judge ─────────────────────────────────────────────────────────────

@traceable(name="worker_c_judge", run_type="llm")
def judge_experience(resume_for_prompt: dict, extracted: dict, job: dict, worker_c_result: dict) -> dict:
    prompt = f"""
<role>
You are an arithmetic auditor. You do not re-evaluate candidates. Your only job is to verify that the deductions described in a scorer's reasoning correctly add up to the score it returned, and fix it if they don't.
</role>

<candidate_information>
{json.dumps(resume_for_prompt, indent=2)}
</candidate_information>

<job_information>
- Years needed: {extracted.get("required_years", "not specified")}
- Degree needed: {extracted.get("required_degree", "not specified")}
- Certifications needed: {json.dumps(extracted.get("required_certifications", []))}
- Role Level: {extracted.get("position_level", "not specified")}
- Role: {job.get("title", "")} at {job.get("company", "")}
</job_information>

<worker_c_output>
Score returned: {worker_c_result.get("experience_fit")}
Reasoning: {worker_c_result.get("reasoning")}
</worker_c_output>

<instructions>
1. Read the reasoning carefully and list every deduction mentioned with its point value.
2. Sum all the deductions found in the reasoning.
3. Compute what the score should be: 100 - total deductions.
4. Compare that to the score returned.
5. If they match: corrected_score = the returned score.
6. If they do not match: corrected_score = 100 - total deductions from the reasoning.
7. Do not invent new deductions. Only use what is explicitly stated in the reasoning.
</instructions>

Return JSON:
{{
  "deductions_found": list of integers,
  "deductions_sum": integer,
  "expected_score": integer,
  "returned_score": integer,
  "scores_match": boolean,
  "corrected_score": integer,
  "judge_reasoning": "one sentence explaining what you found and what correction if any was made"
}}
"""
    result = _llm(prompt)
    return {
        "deductions_found": result.get("deductions_found", []),
        "deductions_sum":   result.get("deductions_sum", 0),
        "expected_score":   result.get("expected_score", worker_c_result.get("experience_fit", 0)),
        "returned_score":   result.get("returned_score", worker_c_result.get("experience_fit", 0)),
        "scores_match":     result.get("scores_match", True),
        "corrected_score":  result.get("corrected_score", worker_c_result.get("experience_fit", 0)),
        "judge_reasoning":  result.get("judge_reasoning", ""),
    }


# ── Worker C — Experience & Qualifications Score ───────────────────────────────

@traceable(name="worker_c_experience_score", run_type="llm")
def score_experience(resume: dict, extracted: dict, job: dict) -> dict:
    yoe = _get_yoe(resume)

    resume_for_prompt = {
        "name":                resume.get("name", ""),
        "summary":             resume.get("summary", ""),
        "skills":              _normalise_skills(resume),
        "certifications":      resume.get("certifications", []),
        "education":           resume.get("education", ""),
        "years_of_experience": yoe,
        "professional_level":  resume.get("professional_level", "not specified"),
    }

    candidate_level = resume_for_prompt["professional_level"]

    prompt = f"""
<role>
You are a precise hiring evaluator. You follow scoring rules exactly as written, perform arithmetic carefully, and never deviate from the rubric.
</role>

<candidate_information>
{json.dumps(resume_for_prompt, indent=2)}
</candidate_information>

<job_information>
- Years needed: {extracted.get("required_years", "not specified")}
- Degree needed: {extracted.get("required_degree", "not specified")}
- Certifications needed: {json.dumps(extracted.get("required_certifications", []))}
- Role Level: {extracted.get("position_level", "not specified")}
- Role: {job.get("title", "")} at {job.get("company", "")}
</job_information>

<scoring_rules>
Start at 100. Apply each deduction below in order. Track your running score after each step.

STEP 1 — YEARS OF EXPERIENCE:
- If "Years needed" is 0, null, or "not specified": deduct 0 points, move on.
- If "Years needed" is a real number greater than 0 AND the candidate's years_of_experience is less than that number: deduct 25 points.
- Otherwise: deduct 0 points.

STEP 2 — PROFESSIONAL LEVEL:
The seniority levels ranked from 1 (lowest) to 5 (highest) are:
1 = Internship
2 = Entry-level
3 = Mid-level
4 = Senior-level
5 = Director

- If "Role Level" is null or "not specified": deduct 0 points, move on.
- Find the number for the candidate's level ({candidate_level}) and the number for the job's Role Level.
- If the candidate's number is LESS THAN the job's number: deduct 35 points.
- If the candidate's number is GREATER THAN OR EQUAL TO the job's number: deduct 0 points.

STEP 3 — EDUCATION:
- If "Degree needed" is null or "not specified": deduct 0 points, move on.
- If the candidate's education does not meet or exceed the required degree: deduct 15 points.
- Otherwise: deduct 0 points.

STEP 4 — CERTIFICATIONS:
- If "Certifications needed" is an empty list: deduct 0 points, move on.
- If the candidate is missing any required certification: deduct 15 points total (not per certification).
- Otherwise: deduct 0 points.

STEP 5 — DOMAIN RELEVANCE:
- If the candidate's summary is completely unrelated to the job title and domain: deduct 10 points.
- If there is any reasonable overlap: deduct 0 points.

STEP 6 — FINAL SCORE:
- Your running score after Step 5 is your experience_fit. Copy that number directly.
- Do NOT apply any additional deductions beyond Steps 1-5.
- Do NOT perform any further arithmetic. The running score is already the answer.
</scoring_rules>

<critical_rules>
- You have exactly 5 steps to apply deductions. There are no other deductions.
- Any deduction not listed in Steps 1-5 is forbidden. Do not invent new penalties.
- The running score after Step 5 = experience_fit. Do not subtract it from anything.
</critical_rules>

<output_format>
Return only valid JSON. The experience_fit value MUST equal 100 minus the sum of all deductions you applied.
{{
  "experience_fit": integer,
  "years_meet": boolean,
  "degree_meet": boolean,
  "certifications_meet": boolean,
  "level_meet": boolean,
  "similar_role_experience": "one sentence on domain relevance",
  "reasoning": "walk through each step: what you checked, what you deducted, and your running score after each step"
}}
</output_format>
"""
    result = _llm(prompt)
    judge  = judge_experience(resume_for_prompt, extracted, job, result)

    if not judge.get("scores_match"):
        print(f"[judge_c] Corrected score: {judge['returned_score']} → {judge['corrected_score']} | {judge['judge_reasoning']}")

    return {
        "experience_fit":          judge["corrected_score"],
        "years_meet":              result.get("years_meet", False),
        "degree_meet":             result.get("degree_meet", False),
        "certifications_meet":     result.get("certifications_meet", False),
        "similar_role_experience": result.get("similar_role_experience", ""),
        "reasoning":               result.get("reasoning", ""),
        "judge_reasoning":         judge.get("judge_reasoning", ""),
    }


# ── Worker D — Recruiter POV Score ────────────────────────────────────────────

@traceable(name="worker_d_recruiter_score", run_type="llm")
def score_recruiter(resume: dict, job: dict) -> dict:
    yoe    = _get_yoe(resume)
    skills = _normalise_skills(resume)
    candidate_level = resume.get("professional_level", "not specified")

    prompt = f"""
<role>
You are a experienced recruiter doing a gut-check evaluation of a candidate for a role. You are direct, consistent, and follow the scoring rubric exactly as written.
</role>

<candidate_information>
- Name: {resume.get("name", "")}
- Summary: {resume.get("summary", "")}
- Years of experience: {yoe}
- Professional level: {candidate_level}
- Skills: {json.dumps(skills[:15])}
- Certifications: {json.dumps(resume.get("certifications", []))}
</candidate_information>

<job_information>
- Role: {job.get("title", "")} at {job.get("company", "")}
- Full description: {job.get("description", "")}
</job_information>

<scoring_rules>
Start at 100. Apply each deduction in order. Track your running score after each step.

STEP 1 — CLASSIFY ROLE SENIORITY:
Classify the role as exactly one of: Intern, Junior, Mid, Senior.
Use the job title and description to determine this. This classification drives the weights in Step 2.

STEP 2 — YEARS OF EXPERIENCE FIT:
Weights by role type:
- Intern: YOE is not a major factor, deduct 0 unless candidate has 0 years and role requires some hands-on experience
- Junior: If candidate has less than 1 year for a role expecting some experience, deduct 15 points
- Mid: If candidate's YOE is more than 2 years below what the role implies, deduct 25 points
- Senior: If candidate's YOE is more than 3 years below what the role implies, deduct 35 points

STEP 3 — PROFESSIONAL LEVEL ALIGNMENT:
The seniority levels ranked from 1 (lowest) to 5 (highest) are:
1 = Internship
2 = Entry-level
3 = Mid-level
4 = Senior-level
5 = Director

- Find the number for the candidate's professional level ({candidate_level}) and the number for the classified role seniority from Step 1.
- If the candidate's number is LESS THAN the role's number by 2 or more: deduct 20 points.
- If the candidate's number is LESS THAN the role's number by exactly 1: deduct 10 points.
- If the candidate's number is GREATER THAN OR EQUAL TO the role's number: deduct 0 points.

STEP 4 — SKILLS RELEVANCE:
As a recruiter skimming the resume, how well do the candidate's skills match the role's needs overall?
- Candidate's skills are mostly unrelated to the role: deduct 25 points.
- Candidate has some relevant skills but clear gaps: deduct 15 points.
- Candidate's skills are a reasonable match: deduct 0 points.

STEP 5 — SUMMARY AND OVERALL IMPRESSION:
Does the candidate's summary and background give a recruiter confidence they understand this type of role?
- Summary is completely unrelated to the role domain: deduct 10 points.
- Summary is vague or gives no signal either way: deduct 5 points.
- Summary is relevant and gives a clear picture: deduct 0 points.

STEP 6 — FINAL SCORE:
- Your running score after Step 5 is your recruiter_score. Copy that number directly.
- Do NOT apply any additional deductions beyond Steps 1-5.
- Do NOT perform any further arithmetic. The running score is already the answer.
- Clamp between 0 and 100.
</scoring_rules>

<critical_rules>
- You have exactly 5 steps to apply deductions. There are no other deductions.
- Any deduction not listed in Steps 1-5 is forbidden. Do not invent new penalties.
- The running score after Step 5 = recruiter_score. Do not subtract it from anything.
</critical_rules>

<output_format>
Return only valid JSON.
{{
  "recruiter_score": integer,
  "role_classification": "Intern | Junior | Mid | Senior",
  "is_internship_or_junior_role": boolean,
  "fit_flags": ["short specific reason the candidate is or isn't a fit", "another reason"],
  "potential_judgment": "one sentence on the candidate's overall potential for this role",
  "would_interview": boolean,
  "reasoning": "walk through each step: what you checked, what you deducted, and your running score after each step"
}}
</output_format>
"""
    result = _llm(prompt)
    return {
        "recruiter_score":              int(result.get("recruiter_score", 0)),
        "role_classification":          result.get("role_classification", ""),
        "is_internship_or_junior_role": result.get("is_internship_or_junior_role", False),
        "fit_flags":                    result.get("fit_flags", []),
        "potential_judgment":           result.get("potential_judgment", ""),
        "would_interview":              result.get("would_interview", False),
        "reasoning":                    result.get("reasoning", ""),
    }


# ── Pipeline entry point ───────────────────────────────────────────────────────

@traceable(name="score_job", run_type="tool")
def score_job(resume: dict, job: dict) -> dict:
    yoe = _get_yoe(resume)

    extracted = extract_skills(job)
    kw        = score_keywords(resume, extracted)
    exp       = score_experience(resume, extracted, job)
    rec       = score_recruiter(resume, job)

    keyword_score    = kw.get("keyword_score", 0)
    experience_score = exp.get("experience_fit", 0)
    recruiter_score  = rec.get("recruiter_score", 0)

    final_score = round(
        (keyword_score    * 0.30) +
        (experience_score * 0.40) +
        (recruiter_score  * 0.30)
    )
    final_score = max(0, min(100, final_score))

    # Generate clean job summary for UI display
    summary = summarize_job(job)

    print("\n-----------------------------")
    print(f"Job: {job.get('title')} @ {job.get('company')}")
    print(f"YOE (from profile): {yoe}")
    print(f"Keyword Score:    {keyword_score}")
    print(f"Experience Score: {experience_score}")
    print(f"Recruiter Score:  {recruiter_score}")
    print(f"Final Score:      {final_score}")
    print(f"Summary:          {summary[:80]}...")
    print("-----------------------------\n")

    missing_keywords = kw.get("missing_required", []) + kw.get("missing_preferred", [])
    matched_keywords = kw.get("matched_required", []) + kw.get("matched_preferred", [])

    return {
        "score":            final_score,
        "keywords":         matched_keywords,
        "missing_keywords": missing_keywords,
        "llm_summary":      summary,

        "sub_scores": {
            "keyword_score":    keyword_score,
            "experience_score": experience_score,
            "recruiter_score":  recruiter_score,
            "yoe":              yoe,
            "extracted":        extracted,
            "would_interview":  rec.get("would_interview"),
            "kw_reasoning":     kw.get("reasoning"),
            "exp_reasoning":    exp.get("reasoning"),
            "judge_reasoning":  exp.get("judge_reasoning"),
            "rec_judgment":     rec.get("potential_judgment"),
        }
    }