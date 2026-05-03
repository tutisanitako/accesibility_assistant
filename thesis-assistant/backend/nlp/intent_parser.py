# backend/nlp/intent_parser.py
"""
Intent parser for Georgian text.

Primary: Gemini API (free, understands any Georgian phrasing)
Fallback: Rule-based (instant, offline)
"""

import re
import os
import json
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import IntentResult

log = logging.getLogger(__name__)


# ── Gemini-based parser ───────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an intent parser for a Georgian voice assistant app called "თბილისის ასისტენტი" (Tbilisi Assistant).

The app helps users with two things:
1. Finding concerts and events in Tbilisi (from TKT.ge)
2. Finding bus routes and schedules in Tbilisi (TTC buses)

Analyze the user's Georgian text and return a JSON object.

Possible intents:
- "concert_search": user wants concerts, events, shows, tickets, performances
- "bus_search": user asks about a specific bus route number or bus stop schedule
- "journey_search": user asks how to get somewhere, which bus goes to a place
- "unknown": anything else

JSON format:
{
  "intent": "concert_search" | "bus_search" | "journey_search" | "unknown",
  "days": <number, only for concert_search: days ahead, default 3>,
  "route": <string, only for bus_search: route number if mentioned, else null>,
  "place": <string, only for journey_search: destination WITHOUT case suffixes>,
  "venue": <string, only for concert_search: venue/hall name if user asks about specific place, else null>,
  "specific_date": <string, only for concert_search: specific date mentioned like "17 აპრ", "28 აპრილს", else null>
}

Examples:
- "ფილარმონიაში კონცერტები" → venue: "ფილარმონია"
- "17 აპრილს კონცერტები" → specific_date: "17 აპრ"
- "ამ შაბათს კონცერტები" → days: 7, specific_date: null
- "დედაენის ბარში კონცერტები" → venue: "დედაენის ბარი"

Days rules: "დღეს" → 0, "ხვალ" → 1, "ზეგ" → 2, "კვირაში" → 7, "თვეში" → 30, default → 3

Return ONLY valid JSON, no explanation, no markdown."""


def _parse_with_gemini(text: str) -> IntentResult | None:
    try:
        from google import genai
        from google.genai import types

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return None

        client = genai.Client(api_key=api_key)
        prompt = f"{_SYSTEM_PROMPT}\n\nUser text: {text}"

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=types.Content(
                role="user",
                parts=[types.Part(text=prompt)],
            ),
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=600 ,
            ),
        )

        raw = response.text.strip()
        print(f"RAW: {repr(raw[:200])}", flush=True)  # ADD THIS
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        parsed = json.loads(raw)

        intent = parsed.get("intent", "unknown")
        return IntentResult(
            intent=intent,
            days=parsed.get("days", 3) if intent == "concert_search" else None,
            route=str(parsed["route"]) if parsed.get("route") else None,
            place=parsed.get("place") if intent in ("journey_search", "bus_search") else None,
            venue=parsed.get("venue") if intent == "concert_search" else None,
            specific_date=parsed.get("specific_date") if intent == "concert_search" else None,
        )

    except Exception as e:
        log.warning("Gemini intent parse failed: %s", e)
        return None

# ── Rule-based fallback ───────────────────────────────────────────────────────

_CONCERT_KW = {
    "კონცერტი", "კონცერტები", "კონცერტზე", "კონცერტის", "კონცერტებს",
    "ბილეთი", "ბილეთები", "ბილეთის", "ბილეთზე",
    "შოუ", "სპექტაკლი", "სპექტაკლები", "სპექტაკლის",
    "ღონისძიება", "ღონისძიებები", "ღონისძიებაზე",
    "წარმოდგენა", "წარმოდგენები", "ფესტივალი", "ფესტივალები",
    "კინო", "თეატრი", "ივენთი", "ივენტი", "ტკეტი",
    "tkt", "concert", "show", "event", "festival", "ticket",
}

_BUS_KW = {
    "ავტობუსი", "ავტობუსები", "ავტობუსის", "ავტობუსზე",
    "მარშრუტი", "მარშრუტები", "მარშრუტის", "მარშრუტზე",
    "გაჩერება", "გაჩერებაზე", "გაჩერებები",
    "ტრანსპორტი", "მინიბუსი", "მიკროავტობუსი",
    "ttc", "bus", "route",
}

_JOURNEY_KW = {
    "მივიდე", "მივიდეთ", "მიდის", "მისვლა",
    "მისასვლელი", "მისასვლელად",
    "წავიდე", "წავიდეთ", "გადავიდე", "გადასვლა",
    "ჩავიდე", "ჩასვლა", "ჩავაღწიო", "ჩავაღწიოთ",
    "მივაღწიო", "მივაღწიოთ", "მოვხვდე",
    "how to get", "which bus",
}

_DAY_MAP = {
    "დღეს": 0, "ახლა": 0, "ხვალ": 1, "ზეგ": 2,
    "ამ კვირაში": 7, "ამ კვირას": 7, "კვირაში": 7,
    "კვირის": 7, "შაბათს": 7, "კვირას": 7,
    "ამ თვეში": 30, "თვეში": 30, "თვის": 30,
    "today": 0, "tomorrow": 1, "this week": 7,
    "weekend": 7, "this month": 30,
}


def _extract_route(text: str) -> str | None:
    m = re.search(r"\b(\d{3})\b", text)
    if m: return m.group(1)
    m = re.search(r"\b(\d{2})\b", text)
    return m.group(1) if m else None


def _extract_days(text: str) -> int:
    lower = text.lower()
    for phrase in sorted(_DAY_MAP.keys(), key=len, reverse=True):
        if phrase in lower:
            return _DAY_MAP[phrase]
    m = re.search(r"(\d+)\s*(დღეში|დღეს|დღე|days?)", lower)
    if m:
        return max(1, min(int(m.group(1)), 30))
    return 3


def _extract_place(text: str) -> str:
    matches = re.findall(r'([\u10D0-\u10FF]+)(?:ში|ზე|თან)\b', text)
    noise = {"მივიდე", "მივიდეთ", "ჩავიდე", "წავიდე", "გადავიდე",
             "ავტობუსი", "მარშრუტი", "როგორ", "რომელი", "სად",
             "ჩავაღწიო", "მივაღწიო", "მოვხვდე"}
    for place in reversed(matches):
        if place not in noise and len(place) > 2:
            return place
    m = re.search(r'\bto\s+([A-Za-z\s]+)', text, re.IGNORECASE)
    if m: return m.group(1).strip()
    return text.strip()


def _contains_any(text_lower: str, keywords: set) -> bool:
    return any(kw in text_lower for kw in keywords)


def _rule_based_parse(text: str) -> IntentResult:
    lower = text.lower()
    if _contains_any(lower, _JOURNEY_KW):
        route = _extract_route(text)
        if not route:
            return IntentResult(intent="journey_search", place=_extract_place(text))
    route = _extract_route(text)
    if route:
        return IntentResult(intent="bus_search", route=route)
    if _contains_any(lower, _BUS_KW):
        return IntentResult(intent="bus_search", route=None)
    if _contains_any(lower, _CONCERT_KW):
        return IntentResult(intent="concert_search", days=_extract_days(lower))
    return IntentResult(intent="unknown")


# ── Public API ────────────────────────────────────────────────────────────────

def parse_intent(text: str) -> IntentResult:
    """
    Parse Georgian user input into a structured intent.
    Tries Gemini API first (handles any phrasing), falls back to rule-based.
    """
    result = _parse_with_gemini(text)
    if result:
        log.info("Intent (Gemini): %s | %r", result.intent, text)
        return result

    result = _rule_based_parse(text)
    log.info("Intent (rules): %s | %r", result.intent, text)
    return result