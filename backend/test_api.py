"""
test_api.py — Integration tests for api.py (FastAPI endpoints).

Supabase and Groq are mocked throughout so these tests run offline.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import api
import db
import llm

client = TestClient(api.app)

# Demo rules/facts used by most tests (engine-compatible shape).
_RULES = [
    {
        "id": "R-DEMO",
        "type": "ban",
        "approved": True,
        "page": 1,
        "quote": "Never use cheap.",
        "terms": {"cheap": "affordable"},
    },
    {
        "id": "T-DEMO",
        "type": "tone",
        "approved": True,
        "page": 2,
        "quote": "Keep a professional tone.",
        "terms": {},
    },
]
_FACTS = [
    {
        "id": "F-DEMO",
        "kw": ["customers"],
        "val": 100_000,
        "owner": "Marketing",
        "expires": "2099-01-01",
    }
]


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_body_has_required_keys(self):
        body = client.get("/health").json()
        assert "status" in body
        assert "rules_loaded" in body
        assert "facts_loaded" in body
        assert "supabase" in body

    def test_status_is_ok(self):
        assert client.get("/health").json()["status"] == "ok"


# ---------------------------------------------------------------------------
# /check — basic contract
# ---------------------------------------------------------------------------

class TestCheckContract:
    def test_returns_200_with_valid_text(self):
        with patch.object(db, "load_rules", return_value=[]), \
             patch.object(db, "load_facts", return_value=[]):
            response = client.post("/check", json={"text": "Hello world."})
        assert response.status_code == 200

    def test_response_has_findings_and_ai_available(self):
        with patch.object(db, "load_rules", return_value=[]), \
             patch.object(db, "load_facts", return_value=[]):
            body = client.post("/check", json={"text": "Hello."}).json()
        assert "findings" in body
        assert "ai_available" in body

    def test_empty_text_returns_422(self):
        response = client.post("/check", json={"text": ""})
        assert response.status_code == 422

    def test_whitespace_only_text_returns_422(self):
        response = client.post("/check", json={"text": "   "})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# /check — deterministic findings
# ---------------------------------------------------------------------------

class TestDeterministicFindings:
    def test_banned_term_is_flagged(self):
        with patch.object(db, "load_rules", return_value=_RULES), \
             patch.object(db, "load_facts", return_value=[]):
            body = client.post("/check", json={"text": "Our cheap plan."}).json()
        assert any(f["kind"] == "rule" and f["ref"] == "R-DEMO" for f in body["findings"])

    def test_clean_copy_has_no_rule_findings(self):
        with patch.object(db, "load_rules", return_value=_RULES), \
             patch.object(db, "load_facts", return_value=[]):
            body = client.post("/check", json={"text": "Our affordable plan."}).json()
        assert not any(f["kind"] == "rule" for f in body["findings"])

    def test_verified_numeric_claim(self):
        with patch.object(db, "load_rules", return_value=[]), \
             patch.object(db, "load_facts", return_value=_FACTS):
            body = client.post("/check", json={"text": "Trusted by 100,000 customers."}).json()
        assert any(f["kind"] == "verified" and f["ref"] == "F-DEMO" for f in body["findings"])

    def test_conflicting_numeric_claim(self):
        with patch.object(db, "load_rules", return_value=[]), \
             patch.object(db, "load_facts", return_value=_FACTS):
            body = client.post("/check", json={"text": "Trusted by 1 million customers."}).json()
        assert any(f["kind"] == "conflict" for f in body["findings"])

    def test_findings_are_sorted_by_start_position(self):
        with patch.object(db, "load_rules", return_value=_RULES), \
             patch.object(db, "load_facts", return_value=[]):
            body = client.post(
                "/check",
                json={"text": "Our cheap plan is guaranteed."},
            ).json()
        starts = [f["start"] for f in body["findings"]]
        assert starts == sorted(starts)


# ---------------------------------------------------------------------------
# /check — AI findings
# ---------------------------------------------------------------------------

class TestAIFindings:
    def test_ai_findings_are_included_when_llm_succeeds(self):
        from models import Finding

        fake_finding = Finding(
            kind="tone",
            ref="T-DEMO",
            start=4,
            end=10,
            source="ai",
            message="Tone issue.",
        )

        with patch.object(db, "load_rules", return_value=_RULES), \
             patch.object(db, "load_facts", return_value=[]), \
             patch.object(llm, "ai_findings", return_value=[fake_finding]):
            body = client.post("/check", json={"text": "Buy now! Act fast!"}).json()

        assert body["ai_available"] is True
        assert any(f["kind"] == "tone" for f in body["findings"])

    def test_deterministic_findings_survive_ai_failure(self):
        def _fail(draft, rules):
            raise llm.AIUnavailable("Synthetic failure")

        with patch.object(db, "load_rules", return_value=_RULES), \
             patch.object(db, "load_facts", return_value=[]), \
             patch.object(llm, "ai_findings", side_effect=_fail):
            body = client.post("/check", json={"text": "Our cheap plan."}).json()

        assert body["ai_available"] is False
        assert any(f["kind"] == "rule" for f in body["findings"])

    def test_no_ai_when_no_tone_rules(self):
        ban_only = [r for r in _RULES if r["type"] != "tone"]

        with patch.object(db, "load_rules", return_value=ban_only), \
             patch.object(db, "load_facts", return_value=[]):
            body = client.post("/check", json={"text": "Our cheap plan."}).json()

        # ai_findings should never have been called; no tone rules to process.
        assert body["ai_available"] is False


# ---------------------------------------------------------------------------
# /check — data source integration (seed.json fallback)
# ---------------------------------------------------------------------------

class TestDataSourceFallback:
    def test_seed_rules_are_loaded_when_supabase_absent(self):
        """
        With no Supabase configured, load_rules() falls back to seed.json.
        seed.json R1 bans 'guaranteed'. That term should be flagged.
        """
        with patch.object(db, "_supabase", None):
            body = client.post(
                "/check",
                json={"text": "This product is guaranteed to work."},
            ).json()
        assert any(f["kind"] == "rule" for f in body["findings"])
