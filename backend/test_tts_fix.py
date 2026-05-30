"""
Run from backend/: python test_tts_fix.py
"""
import os, struct, io
from dotenv import load_dotenv
load_dotenv()

from google import genai
from google.genai import types

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# Test 1: plain Georgian with TTS prefix
print("Test 1: Georgian with TTS: prefix...")
try:
    r = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=types.Content(
            role="user",
            parts=[types.Part(text="TTS: გამარჯობა, მე ვარ თბილისის ასისტენტი.")],
        ),
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
        ),
    )
    pcm = bytes(r.candidates[0].content.parts[0].inline_data.data)
    print(f"  OK — {len(pcm)} bytes = {len(pcm)/(24000*2):.1f}s")

    def wav(pcm):
        n=len(pcm); b=io.BytesIO()
        b.write(b"RIFF"); b.write(struct.pack("<I",36+n))
        b.write(b"WAVE"); b.write(b"fmt ")
        b.write(struct.pack("<I",16)); b.write(struct.pack("<H",1))
        b.write(struct.pack("<H",1)); b.write(struct.pack("<I",24000))
        b.write(struct.pack("<I",48000)); b.write(struct.pack("<H",2))
        b.write(struct.pack("<H",16)); b.write(b"data")
        b.write(struct.pack("<I",n)); b.write(pcm)
        return b.getvalue()

    with open("test_georgian.wav","wb") as f:
        f.write(wav(pcm))
    print("  Saved test_georgian.wav — open it to hear Georgian audio")
except Exception as e:
    print(f"  FAILED: {e}")

# Test 2: try with say() style prompt
print("\nTest 2: 'Say aloud:' prefix...")
try:
    r = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=types.Content(
            role="user",
            parts=[types.Part(text="Say aloud: გამარჯობა")],
        ),
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                )
            ),
        ),
    )
    pcm = bytes(r.candidates[0].content.parts[0].inline_data.data)
    print(f"  OK — {len(pcm)} bytes = {len(pcm)/(24000*2):.1f}s")
except Exception as e:
    print(f"  FAILED: {e}")

print("\nDone.")