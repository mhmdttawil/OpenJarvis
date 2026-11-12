"""Deepgram cloud speech-to-text backend.

Talks to Deepgram's pre-recorded REST API directly over ``httpx`` instead of
the ``deepgram-sdk`` package, whose public API changed incompatibly between
major versions (v3 ``PrerecordedOptions`` / v4+ ``DeepgramClient.listen.v1``)
and left this backend silently unusable. Requires ``DEEPGRAM_API_KEY``.
"""

from __future__ import annotations

import os
from typing import List, Optional

import httpx

from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import SpeechBackend, TranscriptionResult

_API_URL = "https://api.deepgram.com/v1/listen"
_MIME = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
    "webm": "audio/webm",
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
}


@SpeechRegistry.register("deepgram")
class DeepgramSpeechBackend(SpeechBackend):
    """Cloud speech-to-text using Deepgram's REST API."""

    backend_id = "deepgram"

    def __init__(self, api_key: Optional[str] = None, *, model: str = "") -> None:
        self._api_key = api_key or os.environ.get("DEEPGRAM_API_KEY", "")
        self._model = model or os.environ.get("DEEPGRAM_MODEL", "nova-3")
        # Kept for backward compatibility with callers that checked ``_client``.
        self._client = object() if self._api_key else None

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        if not self._api_key:
            raise RuntimeError("Deepgram API key not configured (DEEPGRAM_API_KEY)")

        params = {"model": self._model, "smart_format": "true", "punctuate": "true"}
        if language:
            params["language"] = language
        else:
            params["detect_language"] = "true"

        resp = httpx.post(
            _API_URL,
            params=params,
            content=audio,
            headers={
                "Authorization": f"Token {self._api_key}",
                "Content-Type": _MIME.get(format, "audio/wav"),
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()

        channels = (data.get("results") or {}).get("channels") or []
        text, confidence, detected = "", None, None
        if channels:
            alts = channels[0].get("alternatives") or []
            if alts:
                text = alts[0].get("transcript", "") or ""
                confidence = alts[0].get("confidence")
            detected = channels[0].get("detected_language")
        duration = float((data.get("metadata") or {}).get("duration") or 0.0)

        return TranscriptionResult(
            text=text,
            language=detected,
            confidence=confidence,
            duration_seconds=duration,
            segments=[],
        )

    def health(self) -> bool:
        return bool(self._api_key)

    def supported_formats(self) -> List[str]:
        return list(_MIME.keys())
