"""
main.py — FastAPI application entry point.

Routes:
  GET  /           → Serves the frontend SPA
  GET  /health     → Health check
  POST /evaluate   → Main evaluation endpoint
  GET  /demo       → Run evaluation with built-in mock data
"""
from __future__ import annotations
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from models import EvaluateRequest, EvaluationReport
from agents.orchestrator import Orchestrator
from config import get_settings

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ─── App Setup ───────────────────────────────────────────────────────────────
import os
print("--- ENVIRONMENT INSPECTION ---")
print(f"OS MOCK_MODE: {os.environ.get('MOCK_MODE')}")
print(f"OS AI_PROVIDER: {os.environ.get('AI_PROVIDER')}")
print(f"Current Dir: {os.getcwd()}")
print("------------------------------")

settings = get_settings()
print(f"🚀 AI Jira Ticket Evaluator starting...")
print(f"🤖 Active AI Provider: {settings.ai_provider.upper()}")
print(f"📋 Mock Mode: {settings.mock_mode}")
if settings.ai_provider == "gemini":
    print(f"💎 Model: {settings.gemini_model}")
else:
    print(f"🧠 Model: {settings.openai_model}")

app = FastAPI(
    title="AI Jira Ticket Evaluator",
    description=(
        "Multi-agent AI system that automatically evaluates whether a GitHub PR "
        "satisfies the requirements described in a Jira ticket."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend static files
FRONTEND_DIR = Path(__file__).parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# ─── Orchestrator (singleton) ─────────────────────────────────────────────────
orchestrator = Orchestrator()


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def serve_frontend():
    """Serve the main SPA."""
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"message": "AI Jira Ticket Evaluator API", "docs": "/api/docs"})


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "mock_mode": settings.mock_mode,
        "test_generation": settings.enable_test_generation,
    }


@app.post("/evaluate", response_model=EvaluationReport)
async def evaluate(request: EvaluateRequest):
    """
    Main evaluation endpoint.

    Runs the full multi-agent pipeline:
    Jira Agent → GitHub Agent → Analysis Agent → Test Gen Agent → Verdict Agent
    """
    if not request.github_pr_url:
        raise HTTPException(status_code=400, detail="github_pr_url is required.")
    if not request.jira_ticket_id and not request.jira_ticket_json:
        raise HTTPException(
            status_code=400,
            detail="Either jira_ticket_id or jira_ticket_json is required."
        )

    logger.info(f"Evaluation request: PR={request.github_pr_url}, Jira={request.jira_ticket_id}")
    try:
        report = await orchestrator.evaluate(request)
        return report
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error during evaluation")
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")


@app.get("/demo", response_model=EvaluationReport)
async def demo():
    """
    Run a full evaluation using built-in mock data.
    No API keys required — perfect for hackathon demos!
    """
    demo_request = EvaluateRequest(
        github_pr_url="https://github.com/demo-org/demo-repo/pull/42",
        jira_ticket_id="PROJ-123",
    )
    # Force mock mode for this endpoint regardless of env setting
    import os, importlib, config as cfg_module
    original = os.environ.get("MOCK_MODE")
    os.environ["MOCK_MODE"] = "true"
    cfg_module.get_settings.cache_clear()

    try:
        # Temporarily recreate orchestrator in mock mode
        demo_orch = Orchestrator()
        report = await demo_orch.evaluate(demo_request)
    finally:
        if original is None:
            os.environ.pop("MOCK_MODE", None)
        else:
            os.environ["MOCK_MODE"] = original
        cfg_module.get_settings.cache_clear()

    return report


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
