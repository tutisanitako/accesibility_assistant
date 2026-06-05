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
    lat: Optional[float] = None        # current GPS
    lng: Optional[float] = None
    context_date: Optional[str] = None
    home_lat: Optional[float] = None   # saved home coords — sent by frontend
    home_lng: Optional[float] = None

class QueryResponse(BaseModel):
    intent: str
    response_text: str
    tts_text: str = ''
    results: list[dict]
    venue_bus_offer: Optional[str] = None
    directions: Optional[dict] = None

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