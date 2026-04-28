import json
import os
from openai import OpenAI
from agents import trace
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

with trace("Resume Scoring"):
    def score_job(resume: dict, job: dict) -> dict:
        """
        Hybrid scoring system:
        - 40% Keyword Match
        - 30% Experience Fit
        - 30% Recruiter Score

        Returns:
        {
            score,
            keywords,
            missing_keywords,
            llm_summary
        }
        """

        prompt = f"""
    You are an expert recruiter and resume analyst.

    Compare this resume against the job.

    Return ONLY valid JSON with exactly this structure:

    {{
    "job_skills": ["list of important technical skills, tools, keywords from the job"],
    "experience_fit": <integer 0-100>,
    "recruiter_score": <integer 0-100>,
    "llm_summary": "one sentence explaining fit and biggest gaps"
    }}

    Scoring Definitions:

    experience_fit:
    - Measures how closely past experience aligns with responsibilities.
    - Consider transferable skills.
    - Consider relevant projects, tools, industries, seniority.

    recruiter_score:
    - Holistic recruiter judgment.
    - Would this candidate be worth interviewing based on resume vs job?

    Rules:
    - job_skills should be concise and relevant.
    - Prefer technical skills, platforms, tools, certifications, methodologies.
    - Use lowercase keywords when possible.
    - No extra text outside JSON.

    RESUME:
    {json.dumps(resume, indent=2)}

    JOB TITLE: {job['title']} at {job['company']}

    JOB DESCRIPTION:
    {job['description']}
    """
        with trace("Resume x Job Description Scorer"):
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=700,
                response_format={"type": "json_object"},
            )


        result = json.loads(response.choices[0].message.content)

        # -------------------------
        # Parse LLM Response
        # -------------------------
        job_skills = result.get("job_skills", [])
        experience_fit = int(result.get("experience_fit", 0))
        recruiter_score = int(result.get("recruiter_score", 0))
        llm_summary = result.get("llm_summary", "")

        # -------------------------
        # Build Resume Search Text
        # -------------------------
        resume_text_parts = []

        if "skills" in resume:
            resume_text_parts.extend(resume["skills"])

        if "summary" in resume:
            resume_text_parts.append(resume["summary"])

        for exp in resume.get("experience", []):
            resume_text_parts.append(exp.get("title", ""))
            resume_text_parts.append(exp.get("company", ""))
            resume_text_parts.append(exp.get("description", ""))

        resume_text = " ".join(resume_text_parts).lower()

        # -------------------------
        # Keyword Matching
        # -------------------------
        matched_keywords = []
        missing_keywords = []

        for skill in job_skills:
            skill_clean = skill.lower().strip()

            if skill_clean and skill_clean in resume_text:
                matched_keywords.append(skill_clean)
            else:
                missing_keywords.append(skill_clean)

        total_keywords = len(job_skills)

        if total_keywords == 0:
            keyword_score = 50
        else:
            keyword_score = (len(matched_keywords) / total_keywords) * 100

        # -------------------------
        # Final Hybrid Score
        # -------------------------
        final_score = round(
            (keyword_score * 0.40) +
            (experience_fit * 0.30) +
            (recruiter_score * 0.30)
        )

        # Clamp 0-100
        final_score = max(0, min(100, final_score))

        return {
            "score": final_score,
            "keywords": matched_keywords,
            "missing_keywords": missing_keywords,
            "llm_summary": llm_summary
        }