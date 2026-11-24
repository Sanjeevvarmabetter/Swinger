"""Tests for Groq AI provider integration."""
from unittest.mock import MagicMock, patch
import pytest

from tradingos.ai import gemini


def test_groq_mock_generate(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    gemini._CLIENT = None

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "## Analysis\nLooks bullish."}}]
    }

    with patch("requests.post", return_value=mock_resp) as mock_post:
        c = gemini.GeminiClient()
        res = c.generate("Evaluate TSLA", system="Be concise.")
        assert res == "## Analysis\nLooks bullish."
        assert "groq/openai/gpt-oss-120b" in c.active_model
        assert mock_post.called
        call_json = mock_post.call_args[1]["json"]
        assert call_json["model"] == "openai/gpt-oss-120b"
        assert call_json["messages"][0]["content"] == "Be concise."


def _sse(*pieces, done=True):
    lines = [f'data: {{"choices":[{{"delta":{{"content":{__import__("json").dumps(p)}}}}}]}}' for p in pieces]
    return lines + (["data: [DONE]"] if done else [])


def test_groq_mock_chat_streams(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    gemini._CLIENT = None
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = _sse("## Gold\n", "Gold rose ", "+1.2%.")
    with patch("requests.post", return_value=mock_resp) as post:
        c = gemini.GeminiClient()
        pieces = list(c.chat_stream([{"role": "user", "text": "earlier"}, {"role": "error", "text": "x"}],
                                    "Why is gold moving?", {"gold": {"1D %": 1.2}}))
        assert "".join(pieces) == "## Gold\nGold rose +1.2%."
        sent = post.call_args[1]["json"]
        assert sent["stream"] is True
        roles = [m["role"] for m in sent["messages"]]
        assert roles == ["system", "user", "user"]            # error entries are never sent back to the model
        assert '"1D %": 1.2' in sent["messages"][0]["content"]  # context embedded in the system prompt


def test_groq_falls_back_to_next_model_before_first_token(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    bad, good = MagicMock(status_code=503, text="overloaded"), MagicMock(status_code=200)
    good.iter_lines.return_value = _sse("ok")
    with patch("requests.post", side_effect=[bad, good]):
        c = gemini.GeminiClient()
        assert c.chat([], "q") == "ok"
        assert c.active_model.startswith("groq/") and c.active_model != f"groq/{c.cfg.groq_model}"


def test_groq_bad_key_is_clear(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    with patch("requests.post", return_value=MagicMock(status_code=401, text="invalid")):
        with pytest.raises(gemini.GeminiError, match="rejected the API key"):
            gemini.GeminiClient().chat([], "q")


def test_groq_rate_limit_message(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    with patch("requests.post", return_value=MagicMock(status_code=429, text="rate")):
        with pytest.raises(gemini.GeminiError, match="rate limit"):
            gemini.GeminiClient().chat([], "q")


def test_stream_interrupted_mid_answer_raises_not_splices(monkeypatch):
    """A failure after tokens were shown must surface as an error, never be silently replaced."""
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "g")

    def lines():
        yield _sse("partial ", done=False)[0]
        raise ConnectionError("reset")
    resp = MagicMock(status_code=200)
    resp.iter_lines.return_value = lines()
    with patch("requests.post", return_value=resp):
        c = gemini.GeminiClient()
        got = []
        with pytest.raises(gemini.GeminiError, match="interrupted"):
            for p in c.chat_stream([], "q"):
                got.append(p)
        assert got == ["partial "]


def test_test_groq_connection(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "OK"}}]
    }
    with patch("requests.post", return_value=mock_resp):
        ok, msg = gemini.test_groq_connection()
        assert ok is True
        assert "Connected to Groq" in msg


def test_groq_stream_decodes_utf8(monkeypatch):
    """Regression: SSE responses carry no charset; decoding must be UTF-8 (₹, —, ’ were garbled before)."""
    import requests as rq
    monkeypatch.setenv("GROQ_API_KEY", "k")
    body = ('data: {"choices":[{"delta":{"content":"₹92.71 — India’s"}}]}\n\ndata: [DONE]\n\n').encode("utf-8")
    resp = rq.Response()
    resp.status_code = 200
    resp.raw = __import__("io").BytesIO(body)
    resp.headers["Content-Type"] = "text/event-stream"
    with patch("requests.post", return_value=resp):
        assert gemini.GeminiClient().chat([], "q") == "₹92.71 — India’s"
