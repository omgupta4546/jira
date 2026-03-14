"""
agents/test_gen_agent.py

Generates pytest test stubs for each Jira acceptance criterion
using Gemini. This is the optional "bonus" agent.
"""
from __future__ import annotations
import json
import logging
import re

from config import get_settings
from models import JiraTicket, GitHubPR, GeneratedTest
from agents.ai_client import AIClient

logger = logging.getLogger(__name__)

MOCK_TESTS: list[GeneratedTest] = [
    GeneratedTest(
        requirement_id="AC-1",
        test_name="test_google_login_button_visible",
        test_code=(
            "def test_google_login_button_visible(client):\n"
            "    \"\"\"AC-1: Login with Google button must be visible on the login page.\"\"\"\n"
            "    response = client.get('/login')\n"
            "    assert response.status_code == 200\n"
            "    assert 'Login with Google' in response.text\n"
            "    assert '/auth/google' in response.text\n"
        ),
    ),
    GeneratedTest(
        requirement_id="AC-2",
        test_name="test_google_oauth_redirect",
        test_code=(
            "@pytest.mark.asyncio\n"
            "async def test_google_oauth_redirect(async_client):\n"
            "    \"\"\"AC-2: /auth/google must redirect to Google consent screen.\"\"\"\n"
            "    response = await async_client.get('/auth/google', follow_redirects=False)\n"
            "    assert response.status_code == 302\n"
            "    assert 'accounts.google.com' in response.headers['location']\n"
        ),
    ),
    GeneratedTest(
        requirement_id="AC-4",
        test_name="test_jwt_issued_on_success",
        test_code=(
            "@pytest.mark.asyncio\n"
            "async def test_jwt_issued_on_success(async_client, mock_google_token):\n"
            "    \"\"\"AC-4: JWT access token must be returned on successful Google login.\"\"\"\n"
            "    response = await async_client.get('/auth/google/callback', params={'code': 'valid_code'})\n"
            "    body = response.json()\n"
            "    assert response.status_code == 200\n"
            "    assert 'access_token' in body\n"
            "    assert body['token_type'] == 'bearer'\n"
        ),
    ),
    GeneratedTest(
        requirement_id="AC-5",
        test_name="test_auth_failure_shows_error",
        test_code=(
            "@pytest.mark.asyncio\n"
            "async def test_auth_failure_shows_error(async_client, mock_google_failure):\n"
            "    \"\"\"AC-5: Failed auth must return a user-friendly error.\"\"\"\n"
            "    response = await async_client.get('/auth/google/callback', params={'error': 'access_denied'})\n"
            "    body = response.json()\n"
            "    assert response.status_code == 400\n"
            "    assert 'error' in body\n"
            "    assert body['error'] == 'Authentication failed'\n"
        ),
    ),
    GeneratedTest(
        requirement_id="AC-6",
        test_name="test_user_profile_saved_on_first_login",
        test_code=(
            "@pytest.mark.asyncio\n"
            "async def test_user_profile_saved_on_first_login(async_client, db, mock_google_token):\n"
            "    \"\"\"AC-6: User email and display_name must be saved to the DB on first login.\"\"\"\n"
            "    await async_client.get('/auth/google/callback', params={'code': 'valid_code'})\n"
            "    user = await db.users.find_one({'email': 'jane@example.com'})\n"
            "    assert user is not None\n"
            "    assert user['display_name'] == 'Jane Doe'\n"
        ),
    ),
]


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


class TestGenerationAgent:
    """
    Generates pytest test stubs that can be used to validate
    whether the acceptance criteria are properly implemented.
    """

    GENERATION_PROMPT = """You are a QA engineer. Given the Jira acceptance criteria and the PR diff below,
generate pytest test stubs that verify each acceptance criterion.

JIRA TICKET: {title}
ACCEPTANCE CRITERIA:
{acceptance_criteria}

PR DIFF SUMMARY:
{diff_summary}

Return a JSON array (no markdown fences) of test objects, each with:
- "requirement_id": the AC id this test targets
- "test_name": snake_case function name
- "test_code": full Python pytest function string (include docstring)

Important:
- Generate only one focused test per requirement.
- Use pytest and httpx AsyncClient patterns.
- Include realistic assertions based on the actual code in the diff.
- Add fixtures as function params (e.g., async_client, db)."""

    def __init__(self):
        cfg = get_settings()
        self.mock = cfg.mock_mode
        self.enabled = cfg.enable_test_generation
        if not self.mock and self.enabled:
            self.model = AIClient()

    def run(self, ticket: JiraTicket, pr: GitHubPR) -> list[GeneratedTest]:
        if self.mock:
            logger.info("[TestGenAgent] Mock mode — returning sample tests.")
            return MOCK_TESTS
        if not self.enabled:
            logger.info("[TestGenAgent] Disabled — skipping test generation.")
            return []

        # Build inputs
        ac_text = ticket.raw_acceptance_criteria or "\n".join(
            f"{r.id}: {r.description}" for r in ticket.requirements
        )
        diff_summary = "\n".join(
            f"[{f.filename}] +{f.additions}/-{f.deletions}\n{f.patch[:800]}"
            for f in pr.files_changed
        )

        prompt = self.GENERATION_PROMPT.format(
            title=ticket.title,
            acceptance_criteria=ac_text,
            diff_summary=diff_summary[:6000],
        )

        try:
            response = self.model.generate(prompt)
            raw = _clean_json(response)
            data = json.loads(raw)
            return [
                GeneratedTest(
                    requirement_id=t.get("requirement_id", ""),
                    test_name=t.get("test_name", "test_unknown"),
                    test_code=t.get("test_code", ""),
                )
                for t in data
            ]
        except Exception as e:
            logger.error(f"[TestGenAgent] Failed: {e}")
            return []
