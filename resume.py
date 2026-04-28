import fitz  # PyMuPDF
import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def extract_text(pdf_path: str) -> str:
    """Pull raw text out of the PDF, page by page."""
    doc = fitz.open(pdf_path)
    return "\n".join(page.get_text() for page in doc)


def parse_resume(pdf_path: str) -> dict:
    """Extract text then ask the LLM to structure it as JSON."""
    raw_text = extract_text(pdf_path)

    prompt = f"""You are a resume parser. Extract the information from this resume and return ONLY valid JSON, no explanation, no markdown.

Use this exact structure:
{{
  "name": "string",
  "email": "string",
  "skills": ["skill1", "skill2"],
  "experience": [
    {{
      "title": "string",
      "company": "string",
      "start_date": "string",
      "end_date": "string",
      "description": "string"
    }}
  ],
  "education": [
    {{
      "degree": "string",
      "institution": "string",
      "start_date": "string",
      "end_date": "string
    }}
  ],
  "summary": "string"
}}

Resume text:
{raw_text}"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1500,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content.strip()
    return json.loads(content)