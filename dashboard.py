"""
dashboard.py
------------
Gradio UI for the Job Intelligence Platform.
Displays ranked jobs, KPI banner, and AI-powered insights.
"""

import gradio as gr
from config import DASHBOARD_TITLE, DASHBOARD_PORT, SCORE_THRESHOLD
import database


def build_kpi_banner(kpi: dict | None) -> str:
    """Render the top KPI bar as a Markdown string."""
    pass


def build_job_table(min_score: float) -> list[list]:
    """
    Fetch jobs from DB above min_score and format for gr.Dataframe.
    Columns: Score, Title, Company, Location, Recommendation, Applied
    """
    pass


def build_job_detail(job_id: int) -> str:
    """
    Render the right-panel job detail view as a Markdown string.
    Includes: title, company, recommendation badge, match reason,
    missing keywords, resume tweak suggestion, apply link.
    """
    pass


def mark_job_applied(job_id: int) -> str:
    """Toggle applied status and return a confirmation message."""
    pass


def launch_dashboard() -> None:
    """Construct and launch the Gradio Blocks interface."""
    pass
