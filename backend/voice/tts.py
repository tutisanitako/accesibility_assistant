from __future__ import annotations
# backend/voice/tts.py
"""
Text-to-Speech using Microsoft Edge TTS (edge-tts).
Voice: ka-GE-EkaNeural — real Georgian neural voice, no API key needed.
Returns MP3 bytes.
"""

import io
import logging

log = logging.getLogger(__name__)

VOICE = "ka-GE-EkaNeural"


async def synthesize_async(text: str) -> bytes:
    """Async version — call this directly from async FastAPI endpoints."""
    import edge_tts
    buf = io.BytesIO()
    async for chunk in edge_tts.Communicate(text, VOICE).stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    mp3 = buf.getvalue()
    if not mp3:
        raise RuntimeError("edge-tts returned no audio.")
    log.info("TTS: %d MP3 bytes", len(mp3))
    return mp3


def synthesize(text: str, language_code: str = "ka-GE") -> bytes:
    """Sync version — runs the async function in a new thread with its own loop."""
    import asyncio
    import concurrent.futures

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(synthesize_async(text))
        finally:
            loop.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_run).result()