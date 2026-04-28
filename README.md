# Job Intelligence Platform

A Python tool that reads job alert emails from Gmail, scrapes the full job postings, scores them against your resume using OpenAI embeddings + GPT-4o-mini, and displays ranked results with AI-powered insights in a Gradio dashboard.

---

## Setup

### 1. Clone & install dependencies

```bash
git clone <your-repo-url>
cd job-intelligence-platform

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium  # for JS-rendered job pages
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
```

### 3. Add your resume

Paste your resume as plain text into `resume.txt`. Remove the placeholder instructions.

### 4. Set up Gmail API (one time)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use an existing one)
3. Enable the **Gmail API**
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Choose **Desktop app**, download the JSON, rename it to `credentials.json` and place it in the project root
6. First run will open a browser for OAuth consent — approve it
7. `token.json` is saved automatically for future runs

### 5. Set up Gmail labels

Create a label called `job-alerts` in Gmail and set up filters to tag job alert emails automatically. The default search query also catches emails from `greenhouse.io`, `lever.co`, and `jobleads.com`.

---

## Run

```bash
python main.py
```

The pipeline will:
1. Fetch job emails from Gmail
2. Scrape each job posting
3. Extract structured data via GPT-4o-mini
4. Score each job against your resume
5. Run AI analysis on the top 15 matches
6. Save everything to `jobs.db`
7. Open the Gradio dashboard at http://localhost:7860

---

## Project structure

```
job-intelligence-platform/
├── main.py               # orchestrates the full pipeline
├── gmail_client.py       # Gmail API auth + fetch job emails
├── scraper.py            # httpx + BS4 scraper with Playwright fallback
├── ai_engine.py          # all OpenAI calls (extraction, scoring, explanation)
├── database.py           # SQLite schema + queries
├── dashboard.py          # Gradio UI
├── config.py             # API keys, constants, score weights
├── resume.txt            # plain text resume (paste yours here)
├── credentials.json      # Gmail OAuth (gitignored)
├── jobs.db               # SQLite database (gitignored)
└── requirements.txt
```

---

## Scoring formula

```
final_score = (
    0.4 × skill_match        # % of required skills found in resume
  + 0.3 × embedding_sim      # cosine similarity of job ↔ resume embeddings
  + 0.2 × seniority_fit      # exact=1.0, adjacent=0.5, mismatch=0.0
  + 0.1 × keyword_overlap    # simple token overlap
) × 100
```
