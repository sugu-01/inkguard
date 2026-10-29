"""
api/index.py — Vercel serverless entry point for InkGuard.

This file:
  1. Adds the backend/ directory to sys.path so all existing modules import
     correctly (db, engine, llm, models, etc.).
  2. Imports the canonical FastAPI app from backend/api.py.
  3. Mounts a route to serve frontend/index.html at the root path (/).

Vercel expects a variable named `app` (a FastAPI/Starlette instance) in this
file.  All other routes (/health, /check) are defined in backend/api.py and
are automatically available.
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Make backend/ importable — Vercel runs from the repo root, so we add
# the absolute path to backend/ at the front of sys.path.
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent        # repo root (inkguard/)
_BACKEND = _ROOT / "backend"
_FRONTEND = _ROOT / "frontend"

if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# ---------------------------------------------------------------------------
# Import the canonical FastAPI app from backend/api.py
# ---------------------------------------------------------------------------
from api import app  # noqa: E402  (backend/api.py → app)

# ---------------------------------------------------------------------------
# Serve the frontend at /
# ---------------------------------------------------------------------------
from fastapi.responses import HTMLResponse  # noqa: E402

_INDEX_HTML = _FRONTEND / "index.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_frontend():
    """Serve the InkGuard frontend."""
    return _INDEX_HTML.read_text(encoding="utf-8")

