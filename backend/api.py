
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import engine
import llm
from models import CheckRequest, CheckResponse

app = FastAPI(
    title="InkGuard API",
    description="Brand guideline and content review API",
    version="0.1.0",
)

# Development configuration. Restrict origins before production deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Synthetic demo data only.
# Replace these lists with approved records from your database.
RULES = []
FACTS = []


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/check", response_model=CheckResponse)
def check_content(request: CheckRequest):
    # Deterministic checks always run, regardless of AI availability.
    findings = engine.check(request.text, RULES, FACTS)

    # AI findings are optional and only run for approved tone rules.
    tone_rules = [
        rule
        for rule in RULES
        if rule.get("type") == "tone" and rule.get("approved") is True
    ]

    ai_available = False

    if tone_rules:
        try:
            findings.extend(llm.ai_findings(request.text, tone_rules))
            ai_available = True
        except llm.AIUnavailable:
            # Keep all deterministic findings if the AI request fails.
            ai_available = False

    findings.sort(key=lambda finding: (finding.start, finding.end))

    return CheckResponse(
        findings=findings,
        ai_available=ai_available,
    )
