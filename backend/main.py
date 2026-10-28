
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import store
import engine
from models import CheckRequest, CheckResponse

app = FastAPI(title="InkGuard API")

# Allow the frontend to communicate with the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Test whether the backend is running
@app.get("/health")
def health():
    return {"ok": True, "message": "InkGuard API is running"}


# Check advertisement text
@app.post("/check", response_model=CheckResponse)
def check(req: CheckRequest):
    try:
        db = store.load()

        findings = engine.check(
            req.text,
            db["rules"],
            db["facts"]
        )

        return CheckResponse(
            findings=findings,
            ai_available=False
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
