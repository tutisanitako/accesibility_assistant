# backend/nlp/response_builder.py
"""
Builds natural Georgian response text using Gemini API.
Falls back to template-based responses if API fails.
"""

import re
import os
import json
import logging
from datetime import datetime
from models import IntentResult

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_stop_name(name: str) -> str:
    """Remove stop codes like [2293] and metro prefixes like მ/ს from stop names."""
    name = re.sub(r'\s*\[\d+\]', '', name).strip()
    name = re.sub(r'^მ/ს\s*["\']?', '', name).strip()
    name = name.strip('"\'')
    return name


def _minutes_until(h: int, m: int) -> int:
    now = datetime.now()
    return (h * 60 + m) - (now.hour * 60 + now.minute)


def _next_departures(schedule: list[dict], count: int = 3) -> list[tuple]:
    now = datetime.now()
    h_now, m_now = now.hour, now.minute
    upcoming = []
    for entry in schedule:
        h = entry["hour"]
        for m_str in entry["departures"]:
            try:
                m = int(m_str)
            except ValueError:
                continue
            if h > h_now or (h == h_now and m > m_now):
                upcoming.append((h, m))
            if len(upcoming) >= count:
                return upcoming
    return upcoming


def _departure_phrase(h: int, m: int) -> str:
    mins = _minutes_until(h, m)
    time_str = f"{h:02d}:{m:02d}"
    if mins <= 2:
        return f"{time_str} (ახლავე)"
    elif mins <= 10:
        return f"{time_str} ({mins} წუთში)"
    elif mins <= 30:
        return f"{time_str} (~{mins} წუთში)"
    else:
        return time_str


# ── Gemini response builder ───────────────────────────────────────────────────

def _build_with_gemini(prompt: str) -> str | None:
    try:
        from google import genai
        from google.genai import types

        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return None

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=types.Content(
                role="user",
                parts=[types.Part(text=prompt)],
            ),
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=10000,
            ),
        )
        raw = response.text.strip()
        print(f"GEMINI RAW: {repr(raw[:200])}", flush=True)
        # Strip thinking tags from reasoning models
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        # Return None if empty after stripping
        return raw if raw else None
    except Exception as e:
        log.warning("Gemini response build failed: %s", e)
        return None


# ── Bus response ──────────────────────────────────────────────────────────────

def _format_bus(route_number: str, stops: list[dict]) -> str:
    if not stops:
        return (
            f"{route_number}-ე მარშრუტის ინფორმაცია ვერ მოიძებნა. "
            f"ხელმისაწვდომი მარშრუტებია: 299, 300, 301, 302, 305, 307, 312, 314, 315, 320."
        )

    # Build structured data for Gemini
    stop_data = []
    for stop in stops[:4]:
        name = _clean_stop_name(stop["name"])
        departures = _next_departures(stop["schedule"], count=3)
        if departures:
            times = [_departure_phrase(h, m) for h, m in departures]
            stop_data.append(f"{name}: {', '.join(times)}")
        else:
            stop_data.append(f"{name}: დღის ბოლო რეისი გავიდა")

    stops_text = "\n".join(stop_data)
    prompt = f"""შეადგინე მოკლე, ბუნებრივი ქართული პასუხი ხმოვანი ასისტენტისთვის.
მომხმარებელი კითხულობს {route_number}-ე ავტობუსის გრაფიკს.

მონაცემები:
{stops_text}

წესები:
- 2-3 წინადადება მაქსიმუმ
- ბუნებრივი ქართული მეტყველება
- მხოლოდ ყველაზე მნიშვნელოვანი ინფორმაცია
- არ გამოიყენო ნომრები სიების სახით
- დროები გამოაქვეყნე ბუნებრივად ("10 წუთში მოვა" და ა.შ.)"""

    result = _build_with_gemini(prompt)
    if result:
        return result

    # Fallback
    parts = [f"{route_number}-ე მარშრუტი."]
    for line in stop_data[:2]:
        parts.append(line + ".")
    return " ".join(parts)


# ── Concert response ──────────────────────────────────────────────────────────

def _format_date(date_str: str, time_str: str) -> str:
    if " - " in date_str:
        date_str = date_str.split(" - ")[0].strip()
    if time_str and time_str != "N/A":
        return f"{date_str}-ს {time_str}-ზე"
    return f"{date_str}-ს"


def _format_concerts(concerts: list[dict], venue_bus_offer: str | None, venue_filter: str | None = None, date_filter: str | None = None) -> str:
    if not concerts:
        if venue_filter:
            return f"{venue_filter}-ში ახლო დღეებში კონცერტები ვერ მოიძებნა."
        if date_filter:
            return f"{date_filter}-ს კონცერტები ვერ მოიძებნა."
        return "ახლო დღეებში კონცერტები ვერ მოიძებნა. სცადეთ: 'ამ კვირაში კონცერტები'."

    concert_list = []
    for c in concerts[:4]:
        name = c.get("name", "")
        venue = c.get("venue", "N/A")
        price = c.get("price", "")
        when = _format_date(c.get("date", ""), c.get("time", ""))

        entry = f"{when}: {name}"
        if venue and venue != "N/A" and not venue_filter:
            entry += f" ({venue}"
            if price and price not in ("N/A", ""):
                entry += f", {price}"
            entry += ")"
        elif price and price not in ("N/A", ""):
            entry += f" — {price}"
        concert_list.append(entry)

    concerts_text = "\n".join(concert_list)
    total = len(concerts)

    context = ""
    if venue_filter:
        context = f" ადგილი/დარბაზი: {venue_filter}."
    if date_filter:
        context += f" თარიღი: {date_filter}."

    prompt = f"""შეადგინე მოკლე, ბუნებრივი ქართული პასუხი ხმოვანი ასისტენტისთვის.
მომხმარებელი ეძებს კონცერტებს.{context} სულ ნაპოვნია {total} კონცერტი.

პირველი {min(4, total)}:
{concerts_text}

წესები:
- 2-4 წინადადება
- ბუნებრივი ქართული სასაუბრო მეტყველება
- თუ კონკრეტული ადგილია მოთხოვნილი, დაიწყე "X-ში ვიპოვე Y კონცერტი"-ით
- თუ კონკრეტული თარიღია მოთხოვნილი, დაიწყე "X-ს ვიპოვე Y კონცერტი"-ით
- სხვა შემთხვევაში დაიწყე "ვიპოვე X კონცერტი"-ით
- მოკლედ ჩამოთვალე კონცერტები სახელი და ფასი
- ბოლოს შესთავაზე ავტობუსის ინფო თუ venue_bus_offer არის: {venue_bus_offer or "არ არის"}"""

    result = _build_with_gemini(prompt)
    if result:
        return result

    # Fallback
    intro = f"ვიპოვე {total} კონცერტი. "
    details = []
    for c in concerts[:2]:
        when = _format_date(c.get("date", ""), c.get("time", ""))
        details.append(f"{when} — {c.get('name', '')}")
    return intro + ". ".join(details) + "."


# ── Journey response ──────────────────────────────────────────────────────────

def _format_journey(place: str, results: list[dict]) -> str:
    if not results:
        return (
            f"{place}-ის მახლობლად ავტობუსის გაჩერება ვერ მოიძებნა. "
            "სცადეთ ადგილის სხვა სახელი."
        )

    schedule_lines = []
    for r in results[:4]:
        rn = r["route_number"]
        stop_name = _clean_stop_name(r["stop_name"])
        schedule = r.get("schedule")
        if schedule:
            departures = _next_departures(schedule, count=2)
            if departures:
                times = [_departure_phrase(h, m) for h, m in departures]
                schedule_lines.append(f"{rn}-ე მარშრუტი: {', '.join(times)}")
            else:
                schedule_lines.append(f"{rn}-ე მარშრუტი: დღის ბოლო რეისი გავიდა")
        else:
            schedule_lines.append(f"{rn}-ე მარშრუტი, გაჩერება: {stop_name}")

    routes_text = "\n".join(schedule_lines)

    prompt = f"""შეადგინე მოკლე, ბუნებრივი ქართული პასუხი ხმოვანი ასისტენტისთვის.
მომხმარებელი კითხულობს {place}-სთან ახლოს ავტობუსის მოსვლის დროს.

მონაცემები:
{routes_text}

წესები:
- 2-3 წინადადება მაქსიმუმ
- ბუნებრივი ქართული სასაუბრო მეტყველება
- თითოეული მარშრუტისთვის თქვი რამდენ წუთში მოვა
- გამოიყენე "X-ე ავტობუსი Y წუთში მოვა" ფორმა"""

    result = _build_with_gemini(prompt)
    if result:
        return result

    # Fallback
    parts = []
    for line in schedule_lines[:3]:
        parts.append(line)
    return f"{place}-სთან: " + ". ".join(parts) + "."
# ── Unknown intent ────────────────────────────────────────────────────────────

def _format_unknown() -> str:
    return (
        "ვერ გავიგე კითხვა. "
        "შემიძლია დაგეხმაროთ კონცერტების პოვნაში ან ავტობუსის გრაფიკში. "
        "მაგალითად: 'რა კონცერტებია ხვალ?' ან 'როგორ მივიდე ფილარმონიაში?'"
    )


# ── Public API ────────────────────────────────────────────────────────────────

def build_response(
    intent: IntentResult,
    results: list,
    venue_bus_offer: str | None = None,
) -> str:
    if intent.intent == "bus_search":
        return _format_bus(intent.route or "?", results)
    if intent.intent == "concert_search":
        return _format_concerts(
            results,
            venue_bus_offer,
            venue_filter=intent.venue,
            date_filter=intent.specific_date,
        )
    if intent.intent == "journey_search":
        return _format_journey(intent.place or "ადგილი", results)
    return _format_unknown()