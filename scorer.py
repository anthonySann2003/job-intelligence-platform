import json
import os
import math
from openai import OpenAI
from dotenv import load_dotenv

# LangSmith tracing
from langsmith import traceable
from langsmith.wrappers import wrap_openai

load_dotenv()

# Wrap the OpenAI client so all LLM calls are automatically traced
client = wrap_openai(OpenAI(api_key=os.getenv("OPENAI_API_KEY")))

def cosine_similarity(vec1, vec2):
    """Compute cosine similarity between two embedding vectors."""
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

@traceable(name="score_job", run_type="tool")
def score_job(resume: dict, job: dict) -> dict:
    """
    Hybrid scoring system with embeddings + full trace visibility (LangSmith).
    """
    # --------------------------------------------------
    # 1. LLM STRUCTURED ANALYSIS
    # --------------------------------------------------
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
- Would this candidate be worth interviewing?

Rules:
- Use concise keywords
- Prefer technical skills/tools/platforms
- Lowercase when possible
- No extra text outside JSON

RESUME:
{json.dumps(resume, indent=2)}

JOB TITLE: {job['title']} at {job['company']}

JOB DESCRIPTION:
{job['description']}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=700,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)

    # --------------------------------------------------
    # 2. PARSE LLM OUTPUT
    # --------------------------------------------------
    job_skills = result.get("job_skills", [])
    experience_fit = int(result.get("experience_fit", 0))
    recruiter_score = int(result.get("recruiter_score", 0))
    llm_summary = result.get("llm_summary", "")

    # --------------------------------------------------
    # 3. BUILD RESUME TEXT
    # --------------------------------------------------
    resume_parts = []
    resume_parts.extend(resume.get("skills", []))
    resume_parts.append(resume.get("summary", ""))
    for exp in resume.get("experience", []):
        resume_parts.append(exp.get("title", ""))
        resume_parts.append(exp.get("company", ""))
        resume_parts.append(exp.get("description", ""))
    resume_text = " ".join(resume_parts).lower()

    # --------------------------------------------------
    # 4. KEYWORD MATCH SCORE
    # --------------------------------------------------
    matched_keywords = []
    missing_keywords = []
    for skill in job_skills:
        skill_clean = skill.lower().strip()
        if skill_clean and skill_clean in resume_text:
            matched_keywords.append(skill_clean)
        else:
            missing_keywords.append(skill_clean)
    total_keywords = len(job_skills)
    keyword_score = (len(matched_keywords) / total_keywords) * 100 if total_keywords > 0 else 50

    # --------------------------------------------------
    # 5. EMBEDDING SCORE
    # --------------------------------------------------
    job_text = f"{job['title']}\n{job['company']}\n{job['description']}"
    embedding_response = client.embeddings.create(
        model="text-embedding-3-small",
        input=[resume_text, job_text]
    )
    resume_embedding = embedding_response.data[0].embedding
    job_embedding = embedding_response.data[1].embedding
    similarity = cosine_similarity(resume_embedding, job_embedding)
    embedding_score = max(0, min(100, round(similarity * 100)))

    # --------------------------------------------------
    # 6. FINAL SCORE
    # --------------------------------------------------
    final_score = round(
        (keyword_score * 0.25) +
        (embedding_score * 0.35) +
        (experience_fit * 0.20) +
        (recruiter_score * 0.20)
    )
    final_score = max(0, min(100, final_score))

    #Debugging purposes: Printing 2 calculated scores in terminal
    print("\n-----------------------------")
    print(f"Job: {job['title']} @ {job['company']}")
    print(f"Keyword Score: {round(keyword_score, 2)}")
    print(f"Embedding Score: {round(embedding_score, 2)}")
    print(f"Experience Fit: {experience_fit}")
    print(f"Recruiter Score: {recruiter_score}")
    print(f"Final Score: {final_score}")
    print("-----------------------------\n")

    return {
        "score": final_score,
        "keywords": matched_keywords,
        "missing_keywords": missing_keywords,
        "llm_summary": llm_summary
    }