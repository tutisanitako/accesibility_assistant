# backend/voice/stt.py
"""
Speech-to-Text: Whisper (local) and Google Cloud (API).

Both engines share the same interface:
    transcribe(audio_bytes, engine) → TranscribeResponse

Whisper is the default — it runs fully offline and handles Georgian well
on the 'medium' model. Google is used for the comparative evaluation.
"""

import tempfile
import os
from pathlib import Path

from models import TranscribeResponse
from config import WHISPER_MODEL

# Lazy-loaded so startup isn't slow when voice isn't used
_whisper_model = None

def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("medium", device="cpu", compute_type="float32")
    return _whisper_model

def _transcribe_whisper(audio_bytes: bytes) -> TranscribeResponse:
    model = _get_whisper()

    if audio_bytes[:4] == b'RIFF':
        suffix = ".wav"
    elif audio_bytes[:3] == b'ID3' or audio_bytes[:2] == b'\xff\xfb':
        suffix = ".mp3"
    else:
        suffix = ".webm"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        segments, _ = model.transcribe(tmp_path, language="ka", beam_size=5)
        text = "".join(s.text for s in segments).strip()
        return TranscribeResponse(text=text, engine="whisper", confidence=None)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ── Google Cloud STT ──────────────────────────────────────────────────────────

def _transcribe_google(audio_bytes: bytes) -> TranscribeResponse:
    from google.cloud import speech

    client = speech.SpeechClient()
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.WEBM_OPUS,
        sample_rate_hertz=48000,
        language_code="ka-GE",
        alternative_language_codes=["en-US"],
        enable_automatic_punctuation=True,
    )
    response = client.recognize(
        config=config,
        audio=speech.RecognitionAudio(content=audio_bytes),
    )
    if response.results:
        alt = response.results[0].alternatives[0]
        return TranscribeResponse(
            text=alt.transcript.strip(),
            engine="google",
            confidence=round(alt.confidence, 3),
        )
    return TranscribeResponse(text="", engine="google", confidence=0.0)


# ── Public API ────────────────────────────────────────────────────────────────

def transcribe(audio_bytes: bytes, engine: str = "whisper") -> TranscribeResponse:
    """
    Transcribe audio bytes.
    engine: "whisper" (default, local) | "google" (Cloud API)
    """
    if engine == "google":
        return _transcribe_google(audio_bytes)
    return _transcribe_whisper(audio_bytes)