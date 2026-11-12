"""Tests for Deepgram speech backend (REST API via httpx)."""

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import TranscriptionResult
from openjarvis.speech.deepgram import DeepgramSpeechBackend


@pytest.fixture(autouse=True)
def _register_deepgram():
    """Re-register after any registry clear."""
    if not SpeechRegistry.contains("deepgram"):
        SpeechRegistry.register_value("deepgram", DeepgramSpeechBackend)


def test_deepgram_registers():
    assert SpeechRegistry.contains("deepgram")


def test_deepgram_transcribe():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {
        "metadata": {"duration": 1.8},
        "results": {
            "channels": [
                {
                    "detected_language": "en",
                    "alternatives": [
                        {"transcript": "Hello from Deepgram", "confidence": 0.92}
                    ],
                }
            ]
        },
    }

    with patch("openjarvis.speech.deepgram.httpx.post", return_value=mock_resp) as post:
        backend = DeepgramSpeechBackend(api_key="test-key")
        result = backend.transcribe(b"fake audio", format="webm")

    assert isinstance(result, TranscriptionResult)
    assert result.text == "Hello from Deepgram"
    assert result.confidence == 0.92
    assert result.language == "en"
    assert result.duration_seconds == 1.8
    kwargs = post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Token test-key"
    assert kwargs["headers"]["Content-Type"] == "audio/webm"
    assert kwargs["content"] == b"fake audio"


def test_deepgram_transcribe_requires_key():
    backend = DeepgramSpeechBackend(api_key="")
    with pytest.raises(RuntimeError):
        backend.transcribe(b"x")


def test_deepgram_health():
    backend = DeepgramSpeechBackend(api_key="test-key")
    assert backend.health() is True


def test_deepgram_health_no_key():
    backend = DeepgramSpeechBackend.__new__(DeepgramSpeechBackend)
    backend._client = None
    backend._api_key = ""
    assert backend.health() is False
