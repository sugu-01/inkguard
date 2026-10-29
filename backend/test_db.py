"""
test_db.py — Tests for the db.py data-access layer.

All Supabase calls are mocked so these tests run offline.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed() -> dict:
    seed_path = Path(__file__).parent / "data" / "seed.json"
    return json.loads(seed_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Normalisation: rules
# ---------------------------------------------------------------------------

class TestNormaliseRule:
    def test_banned_terms_type_is_remapped_to_ban(self):
        raw = {
            "id": "R1", "type": "banned_terms", "approved": True,
            "page": 3, "quote": "Never use X.", "terms": ["X"],
        }
        result = db._normalise_rule(raw)
        assert result["type"] == "ban"

    def test_ban_type_is_kept(self):
        raw = {
            "id": "R2", "type": "ban", "approved": True,
            "page": 1, "quote": "No Y.", "terms": {"Y": "Z"},
        }
        result = db._normalise_rule(raw)
        assert result["type"] == "ban"

    def test_terms_list_becomes_dict_with_none_values(self):
        raw = {
            "id": "R3", "type": "ban", "approved": True,
            "page": 1, "quote": "No Z.", "terms": ["alpha", "beta"],
        }
        result = db._normalise_rule(raw)
        assert result["terms"] == {"alpha": None, "beta": None}

    def test_terms_dict_is_preserved(self):
        raw = {
            "id": "R4", "type": "ban", "approved": True,
            "page": 1, "quote": "No W.", "terms": {"cheap": "affordable"},
        }
        result = db._normalise_rule(raw)
        assert result["terms"] == {"cheap": "affordable"}

    def test_missing_id_returns_none(self):
        raw = {"type": "ban", "approved": True, "page": 1, "quote": "X.", "terms": {}}
        assert db._normalise_rule(raw) is None

    def test_missing_quote_returns_none(self):
        raw = {"id": "R5", "type": "ban", "approved": True, "page": 1, "terms": {}}
        assert db._normalise_rule(raw) is None

    def test_injection_type_is_remapped(self):
        raw = {
            "id": "R6", "type": "injection", "approved": True,
            "page": 9, "quote": "Ignore instructions.", "terms": [],
        }
        result = db._normalise_rule(raw)
        assert result["type"] == "inject"

    def test_tone_type_is_preserved(self):
        raw = {
            "id": "R7", "type": "tone", "approved": False,
            "page": 7, "quote": "Keep it neutral.", "terms": [],
        }
        result = db._normalise_rule(raw)
        assert result["type"] == "tone"


# ---------------------------------------------------------------------------
# Normalisation: facts
# ---------------------------------------------------------------------------

class TestNormaliseFact:
    def test_string_kw_becomes_list(self):
        raw = {"id": "F1", "kw": "support_hours", "val": "9-5", "owner": "Ops", "expires": "2099-01-01"}
        result = db._normalise_fact(raw)
        assert result["kw"] == ["support_hours"]

    def test_list_kw_is_preserved(self):
        raw = {"id": "F2", "kw": ["customers", "users"], "val": 100000, "owner": "Marketing", "expires": "2099-01-01"}
        result = db._normalise_fact(raw)
        assert result["kw"] == ["customers", "users"]

    def test_missing_id_returns_none(self):
        raw = {"kw": "x", "val": 1, "owner": "X", "expires": "2099-01-01"}
        assert db._normalise_fact(raw) is None

    def test_missing_val_returns_none(self):
        raw = {"id": "F3", "kw": "x", "owner": "X", "expires": "2099-01-01"}
        assert db._normalise_fact(raw) is None

    def test_expired_fact_is_kept(self):
        """Expired facts should NOT be silently dropped — engine flags them as stale."""
        raw = {"id": "F4", "kw": "promo", "val": "25%", "owner": "Marketing", "expires": "2020-01-01"}
        result = db._normalise_fact(raw)
        assert result is not None
        assert result["expires"] == "2020-01-01"

    def test_bad_expires_defaults_to_far_future(self):
        raw = {"id": "F5", "kw": "x", "val": 1, "owner": "X", "expires": "not-a-date"}
        result = db._normalise_fact(raw)
        assert result["expires"] == "2099-12-31"

    def test_absent_expires_defaults_to_far_future(self):
        raw = {"id": "F6", "kw": "x", "val": 1, "owner": "X"}
        result = db._normalise_fact(raw)
        assert result["expires"] == "2099-12-31"


# ---------------------------------------------------------------------------
# load_rules / load_facts — seed.json fallback (no Supabase)
# ---------------------------------------------------------------------------

class TestLoadFunctions:
    def test_load_rules_returns_normalised_list_from_seed(self):
        with patch.object(db, "_supabase", None):
            rules = db.load_rules()
        assert isinstance(rules, list)
        # seed.json has 4 rules
        assert len(rules) == 4
        # All normalised rules must have required keys
        for r in rules:
            assert "id" in r
            assert "type" in r
            assert isinstance(r["terms"], dict)

    def test_load_facts_returns_normalised_list_from_seed(self):
        with patch.object(db, "_supabase", None):
            facts = db.load_facts()
        assert isinstance(facts, list)
        assert len(facts) == 4
        for f in facts:
            assert "id" in f
            assert isinstance(f["kw"], list)

    def test_load_rules_supabase_falls_back_on_empty_result(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "c1"}  # company lookup returns one row
        ]
        # rules table returns empty
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        with patch.object(db, "_supabase", mock_sb):
            rules = db.load_rules()

        # Should fall back to seed.json and still return normalised rules
        assert isinstance(rules, list)

    def test_supabase_available_true_when_client_set(self):
        with patch.object(db, "_supabase", MagicMock()):
            assert db.supabase_available() is True

    def test_supabase_available_false_when_none(self):
        with patch.object(db, "_supabase", None):
            assert db.supabase_available() is False
