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
from google.api_core.client_options import ClientOptions

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


# ── Google Cloud STT (V2 API for Chirp 3) ─────────────────────────────────────

def _transcribe_google(audio_bytes: bytes) -> TranscribeResponse:
    from google.cloud.speech_v2 import SpeechClient
    from google.cloud.speech_v2.types import cloud_speech

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        import google.auth
        _, project_id = google.auth.default()
        if not project_id:
            raise ValueError("Could not determine Google Cloud Project ID. Please set GOOGLE_CLOUD_PROJECT.")

    # FIX 1: Point the client to the Europe endpoint
    client = SpeechClient(
        client_options=ClientOptions(api_endpoint="europe-west3-speech.googleapis.com")
    )

    config = cloud_speech.RecognitionConfig(
        auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
        language_codes=["ka-GE", "en-US"],
        model="chirp_3",
        features=cloud_speech.RecognitionFeatures(
            enable_automatic_punctuation=True,
        ),
    )

    # FIX 2: Route the recognizer through europe-west4 instead of global
    request = cloud_speech.RecognizeRequest(
        recognizer=f"projects/{project_id}/locations/europe-west3/recognizers/_",
        config=config,
        content=audio_bytes,
    )

    response = client.recognize(request=request)

    if response.results:
        alt = response.results[0].alternatives[0]
        return TranscribeResponse(
            text=alt.transcript.strip(),
            engine="google",
            confidence=round(alt.confidence, 3) if alt.confidence else 0.0,
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