#!/usr/bin/env python
"""Run from backend/: python test_gemini25.py"""
import os
from dotenv import load_dotenv
load_dotenv()

api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
print(f'API key: {api_key[:8]}...{api_key[-4:]}')

from google import genai
from google.genai import types
client = genai.Client(api_key=api_key)

# gemini-2.5-flash and gemini-2.5-pro returned NoneType.strip error
# meaning the response object was returned but r.text was None
# These are "thinking" models — response comes in parts differently

for model in ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.5-flash-preview-04-17']:
    print(f'\n--- Testing {model} ---')
    try:
        r = client.models.generate_content(
            model=model,
            contents=types.Content(role='user', parts=[types.Part(text='Say "გამარჯობა" in Georgian.')]),
            config=types.GenerateContentConfig(temperature=0, max_output_tokens=50),
        )
        print(f'r.text = {r.text!r}')
        print(f'r.candidates = {r.candidates}')
        if r.candidates:
            for c in r.candidates:
                print(f'  candidate.content = {c.content}')
                if c.content and c.content.parts:
                    for part in c.content.parts:
                        print(f'    part.text = {part.text!r}')
    except Exception as e:
        print(f'Error: {e}')

# Also try using the requests library directly to bypass SDK issues
print('\n\n--- Direct HTTP test with requests ---')
import urllib.request, json

url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}'
body = json.dumps({
    "contents": [{"parts": [{"text": "Say ok"}]}],
    "generationConfig": {"maxOutputTokens": 10}
}).encode()

try:
    req = urllib.request.Request(url, data=body,
                                  headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
        print(f'HTTP response keys: {list(data.keys())}')
        if 'candidates' in data:
            text = data['candidates'][0]['content']['parts'][0]['text']
            print(f'Text: {text!r}')
        else:
            print(json.dumps(data, indent=2)[:500])
except Exception as e:
    print(f'HTTP error: {e}')