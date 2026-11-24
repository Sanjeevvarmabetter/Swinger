"""Gemini fallback is quota-aware: daily-exhausted models are skipped (persisted), others tried in order."""
import pytest
from google.genai import errors

DAILY_429 = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message":
             "Quota exceeded for metric: generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash, "
             "description: Generate content requests per day limit exceeded on Free Tier. Please retry in 15h58m56.3s."}}
OVERLOAD = {"error": {"code": 503, "status": "UNAVAILABLE", "message": "This model is currently experiencing high demand."}}


class FakeModels:
    def __init__(self, behaviour):
        self.behaviour, self.calls = behaviour, []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        b = self.behaviour.get(model, "ok")
        if b == "daily":
            raise errors.ClientError(429, DAILY_429)
        if b == "503":
            raise errors.ServerError(503, OVERLOAD)
        if b == "404":
            raise errors.ClientError(404, {"error": {"code": 404, "message": "not found"}})
        return type("R", (), {"text": f"answer from {model}"})()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setattr("time.sleep", lambda s: None)
    from tradingos.ai import gemini

    def make(behaviour):
        c = gemini.GeminiClient()
        fake = FakeModels(behaviour)
        c._client = type("C", (), {"models": fake})()
        return c, fake
    return make


def test_daily_quota_falls_back_and_is_remembered(client):
    from tradingos.ai import gemini
    c, fake = client({"gemini-3.8-flash": "daily", "gemini-3.7-flash": "503"})
    assert c.generate("hi") == "answer from gemini-3.6-flash"
    assert fake.calls == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.7-flash", "gemini-3.6-flash"]
    assert c.active_model == "gemini-3.6-flash"
    assert [q["model"] for q in gemini.quota_status()] == ["gemini-3.8-flash"]
    # second call (could be another process): the exhausted model is not even attempted
    c2, fake2 = client({"gemini-3.7-flash": "503"})
    c2.generate("again")
    assert "gemini-3.8-flash" not in fake2.calls


def test_all_fail_message_is_specific(client):
    from tradingos.ai import gemini
    behaviour = {m: "daily" for m in gemini.FALLBACK_MODELS}
    behaviour["gemini-3.5-flash"] = "503"
    c, _ = client(behaviour)
    with pytest.raises(gemini.GeminiError) as ei:
        c.generate("hi")
    msg = str(ei.value)
    assert "daily quota used" in msg and "overloaded (HTTP 503)" in msg and "free tier" in msg


def test_404_skips_model(client):
    c, fake = client({"gemini-3.8-flash": "404"})
    assert c.generate("hi") == "answer from gemini-3.7-flash"
    assert fake.calls.count("gemini-3.8-flash") == 1
