# backend/models.py
from pydantic import BaseModel
from typing import Optional


class StopSchedule(BaseModel):
    hour: int
    departures: list[str]

class BusStop(BaseModel):
    index: int
    name: str
    schedule: list[StopSchedule]

class BusRoute(BaseModel):
    route_number: str
    stops: list[BusStop]

class Concert(BaseModel):
    name: str
    venue: str
    price: str
    date: str
    time: str
    category: str = 'კონცერტი'
    url: str

class QueryRequest(BaseModel):
    text: str
    # Optional GPS — frontend sends these when available so journey search works
    lat: Optional[float] = None
    lng: Optional[float] = None
    context_date: Optional[str] = None

class QueryResponse(BaseModel):
    intent: str
    response_text: str
    tts_text: str = ''
    results: list[dict]
    venue_bus_offer: Optional[str] = None
    directions: Optional[dict] = None   # Google Maps directions if available

class SynthesizeRequest(BaseModel):
    text: str
    language_code: str = 'ka-GE'

class TranscribeResponse(BaseModel):
    text: str
    engine: str
    confidence: Optional[float] = None

class IntentResult(BaseModel):
    intent: str
    route: Optional[str] = None
    days: Optional[int] = None
    place: Optional[str] = None
    venue: Optional[str] = None
    specific_date: Optional[str] = None
    category: Optional[str] = None
    event_name: Optional[str] = None
    origin: Optional[str] = None

class LocationRequest(BaseModel):
    lat: float
    lng: float

class HomeRouteRequest(BaseModel):
    current_lat: float
    current_lng: float
    home_lat: float
    home_lng: float