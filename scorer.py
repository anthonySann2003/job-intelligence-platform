import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def score_job(resume: dict, job: dict) -> dict:
    """
    Compare a parsed resume against a single job and return scoring data.
    Returns: { score, keywords, missing_keywords, llm_summary }
    """
    prompt = f"""You are an expert recruiter and resume analyst.

Compare this resume against the job and return ONLY valid JSON with exactly these fields:
{{
  "score": <integer 0-100>,
  "keywords": ["skills or terms from the job that ARE on the resume"],
  "missing_keywords": ["skills or terms from the job that are NOT on the resume"],
  "llm_summary": "one sentence explaining the score and biggest gaps"
}}

Scoring guide:
- 80-100: Strong match, most required skills present
- 60-79: Decent match, some gaps but transferable experience
- 40-59: Partial match, notable missing skills
- 0-39: Weak match, significant skill gap

RESUME:
{json.dumps(resume, indent=2)}

JOB TITLE: {job['title']} at {job['company']}
JOB DESCRIPTION:
{job['description']}"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        response_format={"type": "json_object"},
    )

    return json.loads(response.choices[0].message.content)