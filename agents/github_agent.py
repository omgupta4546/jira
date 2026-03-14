"""
agents/github_agent.py

Fetches GitHub Pull Request data:  metadata, commits, changed files and diffs.
"""
from __future__ import annotations
import logging
import re
from github import Github, GithubException

from config import get_settings
from models import GitHubPR, FileChange

logger = logging.getLogger(__name__)

# ─── Mock Data ────────────────────────────────────────────────────────────────
MOCK_PR = GitHubPR(
    pr_number=42,
    title="feat: implement Google OAuth2 login",
    description=(
        "This PR adds Google OAuth2 authentication.\n\n"
        "## Changes\n"
        "- Added `/auth/google` route that initiates the OAuth2 flow\n"
        "- Added `/auth/google/callback` that handles the redirect\n"
        "- JWT token is generated and returned on success\n"
        "- User email and display name saved to `users` table on first login\n"
        "- Error page shown when auth fails\n\n"
        "Closes PROJ-123"
    ),
    author="dev-jane",
    base_branch="main",
    head_branch="feature/google-oauth",
    state="open",
    commits=[
        "feat: add Google OAuth2 client configuration",
        "feat: implement /auth/google route and callback handler",
        "feat: generate JWT on successful OAuth login",
        "feat: persist user profile on first login",
        "fix: show error message on OAuth failure",
        "test: add unit tests for OAuth callback handler",
    ],
    files_changed=[
        FileChange(
            filename="auth/oauth.py",
            status="added",
            additions=120,
            deletions=0,
            patch=(
                "@@ -0,0 +1,120 @@\n"
                "+from fastapi import APIRouter, Request\n"
                "+from fastapi.responses import RedirectResponse, JSONResponse\n"
                "+from authlib.integrations.starlette_client import OAuth\n"
                "+import jwt, os\n"
                "+\n"
                "+router = APIRouter(prefix='/auth')\n"
                "+oauth = OAuth()\n"
                "+oauth.register('google',\n"
                "+    client_id=os.getenv('GOOGLE_CLIENT_ID'),\n"
                "+    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),\n"
                "+    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',\n"
                "+    client_kwargs={'scope': 'openid email profile'}\n"
                "+)\n"
                "+\n"
                "+@router.get('/google')\n"
                "+async def login_google(request: Request):\n"
                "+    redirect_uri = request.url_for('auth_google_callback')\n"
                "+    return await oauth.google.authorize_redirect(request, redirect_uri)\n"
                "+\n"
                "+@router.get('/google/callback', name='auth_google_callback')\n"
                "+async def auth_google_callback(request: Request):\n"
                "+    try:\n"
                "+        token = await oauth.google.authorize_access_token(request)\n"
                "+        user_info = token.get('userinfo')\n"
                "+        # Save user to DB\n"
                "+        await save_user_if_new(user_info['email'], user_info['name'])\n"
                "+        access_token = jwt.encode({'sub': user_info['email']}, os.getenv('JWT_SECRET'), algorithm='HS256')\n"
                "+        return JSONResponse({'access_token': access_token, 'token_type': 'bearer'})\n"
                "+    except Exception as e:\n"
                "+        return JSONResponse({'error': 'Authentication failed', 'detail': str(e)}, status_code=400)\n"
            ),
        ),
        FileChange(
            filename="frontend/login.html",
            status="modified",
            additions=8,
            deletions=1,
            patch=(
                "@@ -12,1 +12,8 @@\n"
                "-<!-- login buttons placeholder -->\n"
                "+<div class='login-container'>\n"
                "+  <h2>Welcome Back</h2>\n"
                "+  <a href='/auth/google' class='btn-google'>\n"
                "+    <img src='/static/google-icon.svg' alt='Google'>\n"
                "+    Login with Google\n"
                "+  </a>\n"
                "+</div>\n"
            ),
        ),
        FileChange(
            filename="db/users.py",
            status="modified",
            additions=22,
            deletions=0,
            patch=(
                "@@ -35,0 +36,22 @@\n"
                "+async def save_user_if_new(email: str, display_name: str):\n"
                "+    \"\"\"Persist user email and display_name on first OAuth login.\"\"\"\n"
                "+    existing = await db.users.find_one({'email': email})\n"
                "+    if not existing:\n"
                "+        await db.users.insert_one({\n"
                "+            'email': email,\n"
                "+            'display_name': display_name,\n"
                "+            'created_at': datetime.utcnow()\n"
                "+        })\n"
            ),
        ),
        FileChange(
            filename="tests/test_oauth.py",
            status="added",
            additions=45,
            deletions=0,
            patch=(
                "@@ -0,0 +1,45 @@\n"
                "+import pytest\n"
                "+from httpx import AsyncClient\n"
                "+from main import app\n"
                "+\n"
                "+@pytest.mark.asyncio\n"
                "+async def test_google_login_redirect():\n"
                "+    async with AsyncClient(app=app, base_url='http://test') as ac:\n"
                "+        response = await ac.get('/auth/google')\n"
                "+    assert response.status_code == 302\n"
                "+    assert 'accounts.google.com' in response.headers['location']\n"
            ),
        ),
    ],
    merged=False,
)


# ─── Agent ───────────────────────────────────────────────────────────────────

class GitHubAgent:
    """
    Responsible for fetching Pull Request metadata, commit messages,
    changed files, and diffs using the GitHub REST API.
    """

    PR_URL_PATTERN = re.compile(
        r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)"
    )

    def __init__(self):
        cfg = get_settings()
        self.mock = cfg.mock_mode
        if not self.mock:
            self.gh = Github(cfg.github_token)

    def _parse_pr_url(self, url: str) -> tuple[str, str, int]:
        m = self.PR_URL_PATTERN.match(url.strip())
        if not m:
            raise ValueError(f"Invalid GitHub PR URL: {url}")
        return m.group("owner"), m.group("repo"), int(m.group("number"))

    def run(self, pr_url: str) -> GitHubPR:
        """Main entry point. Returns a structured GitHubPR."""
        if self.mock:
            logger.info("[GitHubAgent] Mock mode — returning sample PR data.")
            return MOCK_PR

        owner, repo_name, pr_number = self._parse_pr_url(pr_url)
        logger.info(f"[GitHubAgent] Fetching PR #{pr_number} from {owner}/{repo_name}")

        try:
            repo = self.gh.get_repo(f"{owner}/{repo_name}")
            pr = repo.get_pull(pr_number)

            # Commits
            commits = [c.commit.message.split("\n")[0] for c in pr.get_commits()]

            # Files changed
            files_changed = []
            for f in pr.get_files():
                files_changed.append(FileChange(
                    filename=f.filename,
                    status=f.status,
                    additions=f.additions,
                    deletions=f.deletions,
                    patch=f.patch or "",
                ))

            return GitHubPR(
                pr_number=pr.number,
                title=pr.title,
                description=pr.body or "",
                author=pr.user.login,
                base_branch=pr.base.ref,
                head_branch=pr.head.ref,
                state=pr.state,
                commits=commits,
                files_changed=files_changed,
                merged=pr.merged,
            )

        except GithubException as e:
            logger.error(f"[GitHubAgent] GitHub API error: {e}")
            raise RuntimeError(f"GitHub API error: {e.data.get('message', str(e))}")
