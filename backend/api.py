"""
api.py — Main FastAPI entry point for InkGuard.

Start with:
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Routes
------
GET  /health   — liveness + Supabase connectivity status
POST /check    — check ad-copy text against approved rules and facts
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

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
# Application-level cache: load rules and facts once at startup.
# Module-level lists are patchable by tests.
# ---------------------------------------------------------------------------

RULES: list[dict] = []
FACTS: list[dict] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load rules and facts from Supabase (or seed.json fallback) at startup."""
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

# Allow the frontend to talk to the backend in local development.
# Restrict origins in production to your actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    """Liveness probe. Also reports whether Supabase is reachable."""
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

    - Deterministic rule checks (banned terms, numeric claims) always run.
    - AI tone checks (Groq) run when the LLM is configured and tone rules exist.
    - AI failure never suppresses deterministic findings.
    """
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")

    # Reload data on every request so the dev server picks up live changes.
    # In production, replace this with a background refresh / cache.
    rules = db.load_rules()
    facts = db.load_facts()

    # Deterministic checks — always authoritative.
    findings = engine.check(request.text, rules, facts)

    # AI tone checks — optional and additive.
    tone_rules = [
        r for r in rules
        if r.get("type") == "tone" and r.get("approved") is True
    ]

    ai_available = False
    if tone_rules:
        try:
            ai_findings = llm.ai_findings(request.text, tone_rules)
            findings.extend(ai_findings)
            ai_available = True
        except llm.AIUnavailable as exc:
            # Log the reason without exposing credentials or provider internals.
            log.info("AI unavailable (%s); deterministic findings only.", exc)
            ai_available = False

    findings.sort(key=lambda f: (f.start, f.end))

    return CheckResponse(findings=findings, ai_available=ai_available)
