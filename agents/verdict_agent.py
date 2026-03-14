"""
agents/verdict_agent.py

Aggregates per-requirement results and uses Gemini to produce
a final PASS / PARTIAL / FAIL verdict with confidence and summary.
"""
from __future__ import annotations
import json
import logging
import re
from datetime import datetime, timezone

from config import get_settings
from models import (JiraTicket, GitHubPR, RequirementResult,
                    GeneratedTest, EvaluationReport, Verdict)
from agents.ai_client import AIClient

logger = logging.getLogger(__name__)


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


class VerdictAgent:
    """
    Final agent in the pipeline.
    Takes per-requirement results and produces the overall evaluation report.
    """

    VERDICT_PROMPT = """You are a principal engineer making a final decision on whether a GitHub Pull Request 
satisfies all Jira acceptance criteria.

JIRA TICKET: {title} ({ticket_id})
TOTAL REQUIREMENTS: {total}
MET: {met_count}
UNMET: {unmet_count}

PER-REQUIREMENT RESULTS:
{results_summary}

Based on the above, produce a final evaluation. Return a JSON object (no markdown fences) with:
{{
  "verdict": "PASS" | "PARTIAL" | "FAIL",
  "confidence": 0-100,
  "summary": "2-3 sentence executive summary for the reviewer"
}}

Verdict rules:
- PASS:    ALL requirements are met (met_count == total).
- PARTIAL: SOME requirements are met (0 < met_count < total).
- FAIL:    NO requirements are met OR critical blockers exist.

Your confidence should account for:
- Average confidence scores of individual requirements
- Clarity of the evidence provided
- Whether high-priority requirements are met"""

    def __init__(self):
        cfg = get_settings()
        self.mock = cfg.mock_mode
        if not self.mock:
            self.model = AIClient()

    def _build_results_summary(self, results: list[RequirementResult]) -> str:
        lines = []
        for r in results:
            status = "✅ MET" if r.met else "❌ NOT MET"
            lines.append(
                f"[{r.requirement_id}] {status} (confidence: {r.confidence}%)\n"
                f"  {r.description}\n"
                f"  Notes: {r.notes or 'N/A'}"
            )
        return "\n\n".join(lines)

    def run(
        self,
        ticket: JiraTicket,
        pr: GitHubPR,
        requirement_results: list[RequirementResult],
        generated_tests: list[GeneratedTest],
    ) -> EvaluationReport:

        met_count = sum(1 for r in requirement_results if r.met)
        total = len(requirement_results)
        unmet_count = total - met_count

        if self.mock:
            # Determine verdict from mock data directly
            if met_count == total:
                verdict = Verdict.PASS
            elif met_count == 0:
                verdict = Verdict.FAIL
            else:
                verdict = Verdict.PARTIAL
            avg_conf = sum(r.confidence for r in requirement_results) // max(total, 1)
            summary = (
                f"The PR implements all {total} acceptance criteria from {ticket.ticket_id}. "
                f"All OAuth2 flow components are correctly implemented — Google login button, "
                f"redirect handling, JWT generation, and user persistence are all verified in the diff."
            )
        else:
            results_summary = self._build_results_summary(requirement_results)
            prompt = self.VERDICT_PROMPT.format(
                title=ticket.title,
                ticket_id=ticket.ticket_id,
                total=total,
                met_count=met_count,
                unmet_count=unmet_count,
                results_summary=results_summary,
            )
            logger.info("[VerdictAgent] Generating final verdict with Gemini…")
            try:
                response = self.model.generate(prompt)
                raw = _clean_json(response)
                data = json.loads(raw)
                verdict = Verdict(data.get("verdict", "PARTIAL"))
                avg_conf = int(data.get("confidence", 50))
                summary = data.get("summary", "Evaluation complete.")
            except Exception as e:
                logger.error(f"[VerdictAgent] Gemini call failed: {e}. Falling back to rule-based verdict.")
                if met_count == total:
                    verdict = Verdict.PASS
                elif met_count == 0:
                    verdict = Verdict.FAIL
                else:
                    verdict = Verdict.PARTIAL
                avg_conf = sum(r.confidence for r in requirement_results) // max(total, 1)
                summary = f"{met_count}/{total} requirements satisfied."

        return EvaluationReport(
            verdict=verdict,
            confidence=avg_conf,
            summary=summary,
            jira_ticket=ticket,
            pull_request=pr,
            requirement_results=requirement_results,
            generated_tests=generated_tests,
            total_requirements=total,
            met_count=met_count,
            unmet_count=unmet_count,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )
