"""
agents/analysis_agent.py

Compares Jira requirements against the GitHub PR diff
using Gemini to produce per-requirement evidence.
"""
from __future__ import annotations
import json
import logging
import re

from config import get_settings
from models import (GitHubPR, JiraTicket, JiraRequirement,
                    RequirementResult, Evidence)
from agents.ai_client import AIClient

logger = logging.getLogger(__name__)

# ─── Mock Data ────────────────────────────────────────────────────────────────
MOCK_RESULTS: list[RequirementResult] = [
    RequirementResult(
        requirement_id="AC-1",
        description="A 'Login with Google' button is visible on the login page.",
        met=True, confidence=95,
        evidence=[Evidence(file="frontend/login.html", start_line=14, end_line=18,
                           snippet="<a href='/auth/google' class='btn-google'>Login with Google</a>",
                           rationale="HTML anchor tag styled as a button pointing to the Google OAuth route.")],
    ),
    RequirementResult(
        requirement_id="AC-2",
        description="Clicking the button redirects the user to Google's OAuth2 consent screen.",
        met=True, confidence=92,
        evidence=[Evidence(file="auth/oauth.py", start_line=16, end_line=19,
                           snippet="return await oauth.google.authorize_redirect(request, redirect_uri)",
                           rationale="The /auth/google endpoint calls authorize_redirect which triggers the OAuth2 consent flow.")],
    ),
    RequirementResult(
        requirement_id="AC-3",
        description="After successful Google authentication, the user is redirected back to the app.",
        met=True, confidence=90,
        evidence=[Evidence(file="auth/oauth.py", start_line=22, end_line=30,
                           snippet="async def auth_google_callback(request: Request): token = await oauth.google.authorize_access_token(request)",
                           rationale="Callback route handles Google redirect and exchanges code for a token.")],
    ),
    RequirementResult(
        requirement_id="AC-4",
        description="A JWT access token is issued upon successful login.",
        met=True, confidence=97,
        evidence=[Evidence(file="auth/oauth.py", start_line=28, end_line=29,
                           snippet="access_token = jwt.encode({'sub': user_info['email']}, os.getenv('JWT_SECRET'), algorithm='HS256')",
                           rationale="JWT is explicitly generated and returned in the JSON response.")],
    ),
    RequirementResult(
        requirement_id="AC-5",
        description="Failed authentication shows a user-friendly error message.",
        met=True, confidence=80,
        evidence=[Evidence(file="auth/oauth.py", start_line=31, end_line=33,
                           snippet="return JSONResponse({'error': 'Authentication failed', 'detail': str(e)}, status_code=400)",
                           rationale="Exception handler returns a JSON error message, though a frontend error page would be more user-friendly.")],
    ),
    RequirementResult(
        requirement_id="AC-6",
        description="The user's email and display name are stored in the database on first login.",
        met=True, confidence=94,
        evidence=[Evidence(file="db/users.py", start_line=36, end_line=44,
                           snippet="async def save_user_if_new(email, display_name): ... await db.users.insert_one({...})",
                           rationale="save_user_if_new() is called on callback and inserts email + display_name on first login.")],
    ),
]


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _build_diff_summary(pr: GitHubPR, max_chars: int = 12000) -> str:
    """Build a compact textual diff summary to pass to Gemini."""
    parts = [
        f"PR Title: {pr.title}",
        f"PR Description:\n{pr.description}",
        f"\nCommit Messages:\n" + "\n".join(f"  - {c}" for c in pr.commits),
        "\n=== FILES CHANGED ===",
    ]
    total = sum(len(p) for p in parts)
    for fc in pr.files_changed:
        block = (
            f"\n--- {fc.filename} ({fc.status}) "
            f"+{fc.additions}/-{fc.deletions} ---\n{fc.patch}"
        )
        if total + len(block) > max_chars:
            parts.append(f"\n[...diff truncated for {fc.filename}...]")
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts)


class CodeAnalysisAgent:
    """
    For each Jira requirement, asks Gemini to evaluate whether
    the GitHub PR diff satisfies it, and returns structured evidence.
    """

    PER_REQUIREMENT_PROMPT = """You are a senior code reviewer performing requirement traceability analysis.

JIRA REQUIREMENT:
ID: {req_id}
Description: {req_description}
Type: {req_type}
Priority: {req_priority}

GITHUB PULL REQUEST DIFF:
{diff_summary}

Task: Determine whether the code changes in this PR satisfy the above requirement.

Return a single JSON object (no markdown fences) with these exact fields:
{{
  "requirement_id": "{req_id}",
  "met": true or false,
  "confidence": 0-100 (integer),
  "notes": "brief explanation of your reasoning",
  "evidence": [
    {{
      "file": "path/to/file.py",
      "start_line": <integer or null>,
      "end_line": <integer or null>,
      "snippet": "the relevant code snippet",
      "rationale": "why this snippet satisfies / does not satisfy the requirement"
    }}
  ]
}}

Rules:
- If met=false, evidence should show what is MISSING or INCORRECT.
- Be specific — quote actual code from the diff.
- If a requirement is partially satisfied, set met=false and note what is missing.
- confidence reflects how certain you are, accounting for diff completeness."""

    def __init__(self):
        cfg = get_settings()
        self.mock = cfg.mock_mode
        if not self.mock:
            self.model = AIClient()

    def _evaluate_requirement(self, req: JiraRequirement, diff_summary: str) -> RequirementResult:
        prompt = self.PER_REQUIREMENT_PROMPT.format(
            req_id=req.id,
            req_description=req.description,
            req_type=req.type.value,
            req_priority=req.priority,
            diff_summary=diff_summary,
        )
        response = self.model.generate(prompt)
        raw = _clean_json(response)
        data = json.loads(raw)

        evidence = [
            Evidence(
                file=e.get("file", ""),
                start_line=e.get("start_line"),
                end_line=e.get("end_line"),
                snippet=e.get("snippet", ""),
                rationale=e.get("rationale", ""),
            )
            for e in data.get("evidence", [])
        ]
        return RequirementResult(
            requirement_id=data.get("requirement_id", req.id),
            description=req.description,
            met=bool(data.get("met", False)),
            confidence=int(data.get("confidence", 0)),
            evidence=evidence,
            notes=data.get("notes", ""),
        )

    def run(self, ticket: JiraTicket, pr: GitHubPR) -> list[RequirementResult]:
        """Evaluate ALL requirements. Returns list of RequirementResult."""
        if self.mock:
            logger.info("[CodeAnalysisAgent] Mock mode — returning sample results.")
            return MOCK_RESULTS

        diff_summary = _build_diff_summary(pr)
        results: list[RequirementResult] = []
        for req in ticket.requirements:
            logger.info(f"[CodeAnalysisAgent] Evaluating requirement {req.id}…")
            try:
                result = self._evaluate_requirement(req, diff_summary)
                results.append(result)
            except Exception as e:
                logger.error(f"[CodeAnalysisAgent] Failed on {req.id}: {e}")
                results.append(RequirementResult(
                    requirement_id=req.id,
                    description=req.description,
                    met=False,
                    confidence=0,
                    notes=f"Analysis failed: {e}",
                ))
        return results
