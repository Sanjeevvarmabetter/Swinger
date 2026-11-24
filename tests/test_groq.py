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


def test_groq_mock_chat(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    gemini._CLIENT = None

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "AAPL is at $225."}}]
    }

    with patch("requests.post", return_value=mock_resp):
        c = gemini.GeminiClient()
        ans = c.chat([{"role": "user", "text": "What is AAPL price?"}], "Repeat price.")
        assert ans == "AAPL is at $225."


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
