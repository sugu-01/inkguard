
from fastapi.testclient import TestClient

import api
import llm

client = TestClient(api.app)


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_check_returns_response_model():
    response = client.post(
        "/check",
        json={"text": "Trusted by 1 million customers."},
    )

    assert response.status_code == 200
    body = response.json()
    assert "findings" in body
    assert "ai_available" in body


def test_deterministic_findings_survive_ai_failure(monkeypatch):
    api.RULES = [
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
            "page": 1,
            "quote": "Use a professional tone.",
            "terms": {},
        },
    ]

    def fail_ai(draft, rules):
        raise llm.AIUnavailable("Synthetic failure")

    monkeypatch.setattr(llm, "ai_findings", fail_ai)

    response = client.post(
        "/check",
        json={"text": "Our cheap product is available."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ai_available"] is False
    assert any(item["kind"] == "rule" for item in body["findings"])

    # Restore the demo state for other tests.
    api.RULES = []
    api.FACTS = []
