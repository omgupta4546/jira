"""
agents/jira_agent.py

Fetches a Jira ticket via REST API and extracts structured requirements
using the Gemini AI model.
"""
from __future__ import annotations
import json
import logging
import re
import requests
from requests.auth import HTTPBasicAuth

from config import get_settings
from models import JiraTicket, JiraRequirement, RequirementType
from agents.ai_client import AIClient

logger = logging.getLogger(__name__)


# ─── Mock Data ────────────────────────────────────────────────────────────────
MOCK_TICKET = JiraTicket(
    ticket_id="PROJ-123",
    title="User Authentication — OAuth2 Login with Google",
    description=(
        "As a user, I want to log in using my Google account so that I don't "
        "need to remember a separate password for this application."
    ),
    raw_acceptance_criteria=(
        "1. A 'Login with Google' button is visible on the login page.\n"
        "2. Clicking the button redirects the user to Google's OAuth2 consent screen.\n"
        "3. After successful Google authentication, the user is redirected back to the app.\n"
        "4. A JWT access token is issued upon successful login.\n"
        "5. Failed authentication shows a user-friendly error message.\n"
        "6. The user's email and display name are stored in the database on first login."
    ),
    requirements=[
        JiraRequirement(id="AC-1", description="A 'Login with Google' button is visible on the login page.", type=RequirementType.FEATURE, priority="High"),
        JiraRequirement(id="AC-2", description="Clicking the button redirects the user to Google's OAuth2 consent screen.", type=RequirementType.FEATURE, priority="High"),
        JiraRequirement(id="AC-3", description="After successful Google authentication, the user is redirected back to the app.", type=RequirementType.FEATURE, priority="High"),
        JiraRequirement(id="AC-4", description="A JWT access token is issued upon successful login.", type=RequirementType.FEATURE, priority="High"),
        JiraRequirement(id="AC-5", description="Failed authentication shows a user-friendly error message.", type=RequirementType.BUG, priority="Medium"),
        JiraRequirement(id="AC-6", description="The user's email and display name are stored in the database on first login.", type=RequirementType.FEATURE, priority="Medium"),
    ],
    priority="High",
    status="In Progress",
)


# ─── Helper ───────────────────────────────────────────────────────────────────

def _clean_json(raw: str) -> str:
    """Strip markdown code fences if the model wrapped JSON in ```json ... ```."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


# ─── Agent ───────────────────────────────────────────────────────────────────

class JiraAgent:
    """
    Responsible for:
      1. Fetching the Jira ticket from the REST API (or accepting raw JSON).
      2. Using Gemini to extract a structured list of requirements.
    """

    EXTRACTION_PROMPT = """You are a requirements engineer. Analyze this Jira ticket and extract ALL requirements.

JIRA TICKET:
Title: {title}
Description: {description}
Acceptance Criteria:
{acceptance_criteria}

Return a JSON array (and ONLY the JSON array, no markdown fences) where each element has:
- "id": string like "AC-1", "AC-2", etc.
- "description": the full requirement text
- "type": one of "feature", "bug", "improvement", "unknown"
- "priority": one of "High", "Medium", "Low"

Be exhaustive — capture every testable requirement, even implicit ones from the description."""

    def __init__(self):
        cfg = get_settings()
        self.mock = cfg.mock_mode
        if not self.mock:
            self.model = AIClient()
            self.jira_auth = HTTPBasicAuth(cfg.jira_email, cfg.jira_api_token)
            self.jira_base_url = cfg.jira_base_url.rstrip("/")

    def fetch_raw_ticket(self, ticket_id: str) -> dict:
        """Fetch Jira ticket JSON from the REST API."""
        url = f"{self.jira_base_url}/rest/api/3/issue/{ticket_id}"
        resp = requests.get(url, auth=self.jira_auth, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _parse_raw_jira(self, raw: dict) -> tuple[str, str, str, str, str]:
        """Extract fields from Jira issue JSON."""
        fields = raw.get("fields", {})
        title = fields.get("summary", "No title")
        priority = fields.get("priority", {}).get("name", "Medium") if fields.get("priority") else "Medium"
        status = fields.get("status", {}).get("name", "Unknown") if fields.get("status") else "Unknown"

        # Description is in Atlassian Document Format (ADF) — extract text content
        desc_adf = fields.get("description") or {}
        description = self._adf_to_text(desc_adf) if isinstance(desc_adf, dict) else str(desc_adf)

        # Acceptance criteria often in a custom field or within description
        ac_raw = fields.get("customfield_10016") or fields.get("acceptanceCriteria") or ""
        if isinstance(ac_raw, dict):
            ac_raw = self._adf_to_text(ac_raw)
        acceptance_criteria = str(ac_raw)

        return title, description, acceptance_criteria, priority, status

    def _adf_to_text(self, node: dict, depth: int = 0) -> str:
        """Recursively extract plain text from Atlassian Document Format."""
        result = []
        if node.get("type") == "text":
            result.append(node.get("text", ""))
        for child in node.get("content", []):
            result.append(self._adf_to_text(child, depth + 1))
        sep = "\n" if node.get("type") in ("paragraph", "heading", "listItem", "bulletList") else ""
        return sep.join(result)

    def _extract_requirements_with_ai(self, title: str, description: str, acceptance_criteria: str) -> list[JiraRequirement]:
        """Use Gemini to parse requirements from ticket text."""
        prompt = self.EXTRACTION_PROMPT.format(
            title=title,
            description=description,
            acceptance_criteria=acceptance_criteria or "(see description)",
        )
        response = self.model.generate(prompt)
        raw_json = _clean_json(response)
        data = json.loads(raw_json)

        requirements = []
        for item in data:
            req = JiraRequirement(
                id=item.get("id", f"REQ-{len(requirements)+1}"),
                description=item.get("description", ""),
                type=RequirementType(item.get("type", "unknown")),
                priority=item.get("priority", "Medium"),
            )
            requirements.append(req)
        return requirements

    def run(self, ticket_id: str | None = None, raw_json: dict | None = None) -> JiraTicket:
        """Main entry point. Returns a structured JiraTicket."""
        if self.mock:
            logger.info("[JiraAgent] Mock mode — returning sample ticket.")
            return MOCK_TICKET

        # 1. Get raw ticket data
        if raw_json:
            ticket_data = raw_json
            ticket_id = ticket_id or raw_json.get("key", "UNKNOWN")
        elif ticket_id:
            logger.info(f"[JiraAgent] Fetching Jira ticket: {ticket_id}")
            ticket_data = self.fetch_raw_ticket(ticket_id)
        else:
            raise ValueError("Either ticket_id or raw_json must be provided.")

        # 2. Parse fields
        title, description, ac, priority, status = self._parse_raw_jira(ticket_data)

        # 3. Extract requirements with Gemini
        logger.info(f"[JiraAgent] Extracting requirements with AI for ticket: {ticket_id}")
        requirements = self._extract_requirements_with_ai(title, description, ac)

        return JiraTicket(
            ticket_id=ticket_id or "UNKNOWN",
            title=title,
            description=description,
            requirements=requirements,
            raw_acceptance_criteria=ac,
            priority=priority,
            status=status,
        )
