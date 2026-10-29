
"""
api.py — Main FastAPI entry point for InkGuard.

Local development:
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Production:
    uvicorn api:app --host 0.0.0.0 --port $PORT

Routes
------
GET  /       — Serve the InkGuard frontend
GET  /health — Liveness + Supabase connectivity status
POST /check  — Check ad-copy against approved rules and facts
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import db
import engine
import llm
from models import CheckRequest, CheckResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# backend/api.py -> project_root/frontend/index.html
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_FILE = PROJECT_ROOT / "frontend" / "index.html"

# ---------------------------------------------------------------------------
# Application-level cache
# ---------------------------------------------------------------------------

RULES: list[dict] = []
FACTS: list[dict] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load rules and facts at startup."""
    global RULES, FACTS

    RULES = db.load_rules()
    FACTS = db.load_facts()

    log.info(
        "Startup: %d rules, %d facts loaded (Supabase: %s).",
        len(RULES),
        len(FACTS),
        db.supabase_available(),
    )

    yield


app = FastAPI(
    title="InkGuard API",
    description="Brand guideline and ad-copy review API",
    version="0.2.0",
    lifespan=lifespan,
)

# Same-origin frontend/backend deployment.
# Keep CORS enabled for local development or any other required origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def serve_frontend():
    """Serve the InkGuard website from the same public URL as the API."""
    if not FRONTEND_FILE.is_file():
        log.error("Frontend file not found: %s", FRONTEND_FILE)
        raise HTTPException(
            status_code=500,
            detail="Frontend file is missing from the deployment.",
        )

    return FileResponse(
        path=str(FRONTEND_FILE),
        media_type="text/html",
    )


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Report API status and Supabase connectivity."""
    return {
        "status": "ok",
        "rules_loaded": len(RULES),
        "facts_loaded": len(FACTS),
        "supabase": db.supabase_available(),
    }


@app.post("/check", response_model=CheckResponse)
def check_content(request: CheckRequest):
    """
    Check advertisement copy against approved brand rules and facts.

    Deterministic checks always run.
    AI tone checks run when approved tone rules exist.
    AI failures do not suppress deterministic findings.
    """
    if not request.text or not request.text.strip():
        raise HTTPException(
            status_code=422,
            detail="text must not be empty",
        )

    # Load current rules and facts for each request.
    rules = db.load_rules()
    facts = db.load_facts()

    # Deterministic checks.
    findings = engine.check(request.text, rules, facts)

    # Optional AI tone checks.
    tone_rules = [
        rule
        for rule in rules
        if rule.get("type") == "tone"
        and rule.get("approved") is True
    ]

    ai_available = False

    if tone_rules:
        try:
            ai_findings = llm.ai_findings(
                request.text,
                tone_rules,
            )
            findings.extend(ai_findings)
            ai_available = True

        except llm.AIUnavailable as exc:
            log.info(
                "AI unavailable (%s); deterministic findings only.",
                exc,
            )

    findings.sort(key=lambda finding: (finding.start, finding.end))

    return CheckResponse(
        findings=findings,
        ai_available=ai_available,
    )
