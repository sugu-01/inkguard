from engine import check
RULES = [{"id": "R-01", "type": "ban", "approved": True, "page": 4, "quote": "Never use cheap.", "terms": {"cheap": "affordable"}}]
FACTS = [{"id": "F-012", "kw": ["customers"], "val": 100000, "owner": "Marketing", "expires": "2099-01-01"}]

def test_conflict():
    assert any(f.kind == "conflict" and f.ref == "F-012" for f in check("Trusted by 1 million customers.", RULES, FACTS))

def test_verified():
    assert any(f.kind == "verified" for f in check("Trusted by 100,000 customers.", RULES, FACTS))

def test_missing_evidence_is_not_false():
    assert all(f.kind != "conflict" for f in check("We have 5 offices.", RULES, FACTS))

def test_banned_term():
    assert any(f.kind == "rule" for f in check("Our cheap plan.", RULES, FACTS))
