"""Gemini integration tested with a mocked transport (no network, no key needed)."""
import json

import pytest


def test_ai_function_sends_structured_data_and_audits(monkeypatch):
    from tradingos.ai import gemini
    captured = {}

    class FakeClient(gemini.GeminiClient):
        def generate(self, prompt, system=gemini.BASE_SYSTEM, temperature=0.3, max_output_tokens=8192):
            captured["prompt"], captured["system"] = prompt, system
            return "## Review\nLooks extended; wait."

    monkeypatch.setattr(gemini, "_CLIENT", FakeClient())
    out = gemini.trade_plan_review("ABC", {"plan": {"entry": 20.0, "stop": 19.0, "rr": float("nan")}})
    assert out.startswith("## Review")
    assert "TASK:" in captured["prompt"] and '"entry": 20.0' in captured["prompt"]
    assert '"rr": null' in captured["prompt"]           # NaN scrubbed, never invented
    assert "Never invent prices" in captured["system"]
    rep = gemini.recent_reports("trade_plan_review")
    assert rep and rep[0].subject == "ABC" and json.loads(rep[0].input_json)["plan"]["stop"] == 19.0


def test_error_mapping_401(monkeypatch):
    from google.genai import errors

    from tradingos.ai import gemini
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.setenv("GEMINI_MIN_INTERVAL_SECONDS", "0")
    c = gemini.GeminiClient()

    class Models:
        def generate_content(self, **kw):
            raise errors.ClientError(401, {"error": {"message": "bad key", "status": "UNAUTHENTICATED"}})

    class Stub:
        models = Models()

    c._client = Stub()
    with pytest.raises(gemini.GeminiError, match="rejected the API key"):
        c.generate("hi")
    assert "fake" not in str(c.cfg.gemini_model)
