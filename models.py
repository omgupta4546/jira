"""
models.py — Pydantic schemas for all request/response data.
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


# ─── Enums ───────────────────────────────────────────────────────────────────

class Verdict(str, Enum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"


class RequirementType(str, Enum):
    FEATURE = "feature"
    BUG = "bug"
    IMPROVEMENT = "improvement"
    UNKNOWN = "unknown"


# ─── Input Models ────────────────────────────────────────────────────────────

class EvaluateRequest(BaseModel):
    github_pr_url: str = Field(..., description="Full URL of the GitHub Pull Request")
    jira_ticket_id: Optional[str] = Field(None, description="Jira ticket ID, e.g. PROJ-123")
    jira_ticket_json: Optional[dict] = Field(None, description="Raw Jira ticket JSON (alternative to ID)")

    class Config:
        json_schema_extra = {
            "example": {
                "github_pr_url": "https://github.com/owner/repo/pull/42",
                "jira_ticket_id": "PROJ-123"
            }
        }


# ─── Jira Models ─────────────────────────────────────────────────────────────

class JiraRequirement(BaseModel):
    id: str
    description: str
    type: RequirementType = RequirementType.UNKNOWN
    priority: str = "Medium"


class JiraTicket(BaseModel):
    ticket_id: str
    title: str
    description: str
    requirements: List[JiraRequirement]
    raw_acceptance_criteria: str = ""
    priority: str = "Medium"
    status: str = "In Progress"


# ─── GitHub Models ───────────────────────────────────────────────────────────

class FileChange(BaseModel):
    filename: str
    status: str  # added, modified, removed
    additions: int
    deletions: int
    patch: str = ""  # the diff


class GitHubPR(BaseModel):
    pr_number: int
    title: str
    description: str
    author: str
    base_branch: str
    head_branch: str
    state: str
    commits: List[str]          # commit messages
    files_changed: List[FileChange]
    merged: bool = False


# ─── Analysis Models ─────────────────────────────────────────────────────────

class Evidence(BaseModel):
    file: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    snippet: str
    rationale: str


class RequirementResult(BaseModel):
    requirement_id: str
    description: str
    met: bool
    confidence: int = Field(..., ge=0, le=100)
    evidence: List[Evidence] = []
    notes: str = ""


# ─── Test Generation Models ───────────────────────────────────────────────────

class GeneratedTest(BaseModel):
    requirement_id: str
    test_name: str
    test_code: str
    framework: str = "pytest"


# ─── Verdict / Output Models ─────────────────────────────────────────────────

class EvaluationReport(BaseModel):
    verdict: Verdict
    confidence: int = Field(..., ge=0, le=100)
    summary: str
    jira_ticket: JiraTicket
    pull_request: GitHubPR
    requirement_results: List[RequirementResult]
    generated_tests: List[GeneratedTest] = []
    total_requirements: int
    met_count: int
    unmet_count: int
    evaluated_at: str
