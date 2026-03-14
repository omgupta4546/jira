"""
agents/orchestrator.py

Coordinates the full multi-agent pipeline:
  JiraAgent → GitHubAgent → CodeAnalysisAgent → TestGenAgent → VerdictAgent
"""
from __future__ import annotations
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from models import EvaluateRequest, EvaluationReport
from agents.jira_agent import JiraAgent
from agents.github_agent import GitHubAgent
from agents.analysis_agent import CodeAnalysisAgent
from agents.test_gen_agent import TestGenerationAgent
from agents.verdict_agent import VerdictAgent

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Runs all agents in the correct sequence:

    Step 1 (Parallel): Jira Agent + GitHub Agent  → fetch data independently
    Step 2 (Serial):   Code Analysis Agent        → needs both ticket + PR
    Step 3 (Parallel): Test Gen Agent             → can run alongside verdict prep
    Step 4 (Serial):   Verdict Agent              → needs all previous results
    """

    def __init__(self):
        self.jira_agent = JiraAgent()
        self.github_agent = GitHubAgent()
        self.analysis_agent = CodeAnalysisAgent()
        self.test_gen_agent = TestGenerationAgent()
        self.verdict_agent = VerdictAgent()
        self._executor = ThreadPoolExecutor(max_workers=4)

    async def _run_in_thread(self, fn, *args):
        """Run a synchronous function in a thread pool (non-blocking)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, fn, *args)

    async def evaluate(self, request: EvaluateRequest) -> EvaluationReport:
        logger.info("=== Orchestrator: Starting evaluation pipeline ===")

        # ── Step 1: Fetch Jira + GitHub data in parallel ──────────────────────
        logger.info("[Step 1/4] Fetching Jira ticket and GitHub PR simultaneously…")

        jira_future = self._run_in_thread(
            self.jira_agent.run,
            request.jira_ticket_id,
            request.jira_ticket_json,
        )
        github_future = self._run_in_thread(
            self.github_agent.run,
            request.github_pr_url,
        )

        ticket, pr = await asyncio.gather(jira_future, github_future)

        logger.info(f"[Step 1/4] ✓ Ticket: '{ticket.title}' | PR #{pr.pr_number}: '{pr.title}'")

        # ── Step 2: Code Analysis ──────────────────────────────────────────────
        logger.info("[Step 2/4] Running Code Analysis Agent…")
        requirement_results = await self._run_in_thread(
            self.analysis_agent.run, ticket, pr
        )
        met = sum(1 for r in requirement_results if r.met)
        logger.info(f"[Step 2/4] ✓ Analysis complete — {met}/{len(requirement_results)} requirements met.")

        # ── Step 3: Test Generation (optional) ────────────────────────────────
        logger.info("[Step 3/4] Running Test Generation Agent…")
        generated_tests = await self._run_in_thread(
            self.test_gen_agent.run, ticket, pr
        )
        logger.info(f"[Step 3/4] ✓ Generated {len(generated_tests)} test stubs.")

        # ── Step 4: Verdict ───────────────────────────────────────────────────
        logger.info("[Step 4/4] Running Verdict Agent…")
        report = await self._run_in_thread(
            self.verdict_agent.run,
            ticket,
            pr,
            requirement_results,
            generated_tests,
        )
        logger.info(f"[Step 4/4] ✓ Final verdict: {report.verdict} (confidence: {report.confidence}%)")

        logger.info("=== Orchestrator: Pipeline complete ===")
        return report
