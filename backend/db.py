"""
db.py — Data access layer for InkGuard.

Priority:
  1. Supabase (live database) — used when credentials are present and reachable.
  2. seed.json (local fallback) — used when Supabase is unavailable or unconfigured.

Data is normalised to the shape that engine.py expects:
  rules:
    - type "banned_terms" → "ban"
    - terms: list  → {term: None, ...}
    - terms: dict  → kept as-is
  facts:
    - kw: str      → [str]
    - kw: list     → kept as-is

Credentials are loaded from backend/.env and are never logged or returned
to callers.
"""

import json
import logging
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supabase client (optional — None when credentials are absent)
# ---------------------------------------------------------------------------

_supabase = None

_SUPABASE_URL = os.getenv("SUPABASE_URL", "")
_SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if _SUPABASE_URL and _SUPABASE_KEY:
    try:
        from supabase import create_client
        _supabase = create_client(_SUPABASE_URL, _SUPABASE_KEY)
        log.info("Supabase client initialised.")
    except Exception:
        log.warning("Supabase client failed to initialise — falling back to seed data.")
        _supabase = None

# ---------------------------------------------------------------------------
# Seed-file fallback
# ---------------------------------------------------------------------------

_SEED = Path(__file__).parent / "data" / "seed.json"


def _load_seed() -> dict:
    """Return the seed data dict; empty structure if the file is missing."""
    if _SEED.exists():
        return json.loads(_SEED.read_text(encoding="utf-8"))
    return {"rules": [], "facts": []}


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

# Map type names from seed/Supabase → engine internal names.
_TYPE_MAP = {
    "banned_terms": "ban",
    "ban":          "ban",
    "tone":         "tone",
    "disclaimer":   "disclaimer",  # engine ignores; kept for completeness
    "injection":    "inject",       # engine ignores; kept for completeness
    "inject":       "inject",
}


def _normalise_rule(raw: dict) -> dict | None:
    """
    Normalise a raw rule dict to the shape engine.check_banned() expects.

    Returns None if the rule is missing required fields.
    """
    rule_id = raw.get("id")
    raw_type = raw.get("type", "")
    approved = raw.get("approved", False)
    page = raw.get("page", 0)
    quote = raw.get("quote", "")

    if not rule_id or not quote:
        return None

    norm_type = _TYPE_MAP.get(raw_type, raw_type)

    # Normalise terms to {term: replacement_or_None}
    raw_terms = raw.get("terms", {})
    if isinstance(raw_terms, list):
        terms = {str(t): None for t in raw_terms if t}
    elif isinstance(raw_terms, dict):
        terms = {str(k): (str(v) if v is not None else None) for k, v in raw_terms.items()}
    else:
        terms = {}

    return {
        "id":       rule_id,
        "type":     norm_type,
        "approved": bool(approved),
        "page":     int(page),
        "quote":    str(quote),
        "terms":    terms,
    }


def _normalise_fact(raw: dict) -> dict | None:
    """
    Normalise a raw fact dict to the shape engine.check_claims() expects.

    Returns None if required fields are missing.
    Facts whose 'expires' date is in the past are kept (engine flags them
    as stale — that is correct behaviour); we do NOT silently drop them.
    """
    fact_id = raw.get("id")
    kw = raw.get("kw")
    val = raw.get("val")
    owner = raw.get("owner", "Unknown")
    expires = raw.get("expires", "")

    if not fact_id or kw is None or val is None:
        return None

    # Normalise kw to list[str]
    if isinstance(kw, str):
        kw = [kw]
    elif not isinstance(kw, list):
        kw = [str(kw)]
    else:
        kw = [str(k) for k in kw if k]

    # Validate expires is a parseable ISO date; default to far future if absent.
    if not expires:
        expires = "2099-12-31"
    try:
        date.fromisoformat(str(expires))
    except ValueError:
        log.warning("Fact %s has unparseable expires '%s'; treating as 2099-12-31.", fact_id, expires)
        expires = "2099-12-31"

    return {
        "id":      fact_id,
        "kw":      kw,
        "val":     val,          # engine compares numerically; non-numeric → "unverified"
        "owner":   str(owner),
        "expires": str(expires),
    }


# ---------------------------------------------------------------------------
# Supabase loaders
# ---------------------------------------------------------------------------

_DEFAULT_COMPANY = os.getenv("INKGUARD_COMPANY_NAME", "InkGuard Demo Company")


def _company_id(company_name: str) -> str | None:
    """Return the Supabase row ID for a company, or None if not found."""
    try:
        result = (
            _supabase.table("companies")
            .select("id")
            .eq("name", company_name)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["id"]
    except Exception:
        log.warning("Could not look up company '%s' in Supabase.", company_name)
    return None


def _fetch_supabase_rules(company_name: str) -> list[dict]:
    cid = _company_id(company_name)
    if cid is None:
        return []
    try:
        result = (
            _supabase.table("rules")
            .select("id,type,approved,page,quote,terms")
            .eq("company_id", cid)
            .execute()
        )
        return result.data or []
    except Exception:
        log.warning("Supabase rules fetch failed for company '%s'.", company_name)
        return []


def _fetch_supabase_facts(company_name: str) -> list[dict]:
    cid = _company_id(company_name)
    if cid is None:
        return []
    try:
        result = (
            _supabase.table("approved_facts")
            .select("id,kw,val,owner,expires")
            .eq("company_id", cid)
            .execute()
        )
        return result.data or []
    except Exception:
        log.warning("Supabase facts fetch failed for company '%s'.", company_name)
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_rules(company_name: str = _DEFAULT_COMPANY) -> list[dict]:
    """
    Return a list of normalised rule dicts for the given company.

    Tries Supabase first; falls back to seed.json on any failure.
    Never raises — returns an empty list in the worst case.
    """
    raw: list[dict] = []

    if _supabase is not None:
        raw = _fetch_supabase_rules(company_name)
        if raw:
            log.info("Loaded %d rules from Supabase for '%s'.", len(raw), company_name)
        else:
            log.warning("Supabase returned no rules; using seed.json fallback.")

    if not raw:
        raw = _load_seed().get("rules", [])
        log.info("Loaded %d rules from seed.json.", len(raw))

    normalised = [_normalise_rule(r) for r in raw]
    return [r for r in normalised if r is not None]


def load_facts(company_name: str = _DEFAULT_COMPANY) -> list[dict]:
    """
    Return a list of normalised fact dicts for the given company.

    Tries Supabase first; falls back to seed.json on any failure.
    Never raises — returns an empty list in the worst case.
    """
    raw: list[dict] = []

    if _supabase is not None:
        raw = _fetch_supabase_facts(company_name)
        if raw:
            log.info("Loaded %d facts from Supabase for '%s'.", len(raw), company_name)
        else:
            log.warning("Supabase returned no facts; using seed.json fallback.")

    if not raw:
        raw = _load_seed().get("facts", [])
        log.info("Loaded %d facts from seed.json.", len(raw))

    normalised = [_normalise_fact(f) for f in raw]
    return [f for f in normalised if f is not None]


def supabase_available() -> bool:
    """True if a Supabase client was successfully initialised."""
    return _supabase is not None

