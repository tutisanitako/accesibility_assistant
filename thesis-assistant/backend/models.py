# backend/models.py
"""
All shared data models.  If a shape is used in more than one file, it lives here.
"""

from pydantic import BaseModel
from typing import Optional


# ── TTC (Bus) ─────────────────────────────────────────────────────────────────

class StopSchedule(BaseModel):
    hour: int
    departures: list[str]          # ["05", "15", "25", "35", "45", "55"]


class BusStop(BaseModel):
    index: int
    name: str
    schedule: list[StopSchedule]


class BusRoute(BaseModel):
    route_number: str
    stops: list[BusStop]


# ── TKT (Concerts) ────────────────────────────────────────────────────────────

class Concert(BaseModel):
    name: str
    venue: str
    price: str
    date: str
    time: str
    url: str


# ── API request / response ────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    text: str                               # Georgian user input


class QueryResponse(BaseModel):
    intent: str
    response_text: str                      # Georgian text to be spoken back
    results: list[dict]                     # raw items for UI cards
    venue_bus_offer: Optional[str] = None   # venue name to offer bus directions for


class SynthesizeRequest(BaseModel):
    text: str
    language_code: str = "ka-GE"


class TranscribeResponse(BaseModel):
    text: str
    engine: str
    confidence: Optional[float] = None


class IntentResult(BaseModel):
    intent: str
    route: Optional[str] = None
    days: Optional[int] = None
    place: Optional[str] = None
    venue: Optional[str] = None      # ADD THIS — concert venue filter
    specific_date: Optional[str] = None  # ADD THIS — specific date like "17 აპრ"