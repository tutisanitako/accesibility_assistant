"""
backend/main.py

Thin FastAPI router. All business logic lives in services/.

Route → service mapping:
  POST /query            → services.handle_query
  POST /home-route       → inline (needs GPS from frontend)
  GET  /nearest-stop-text → inline (needs GPS)
  GET  /concerts         → scrapers.get_concerts + services.filter_concerts
  GET  /buses            → scrapers.get_available_routes
  GET  /buses/{route}    → scrapers.get_route
  GET  /nearest-stop     → maps helpers
  GET  /journey          → services.search_stops_smart + maps helpers
  POST /transcribe       → voice.stt.transcribe
  POST /synthesize       → voice.tts (edge-tts)
  POST /geocode          → maps.geocode_address
"""

import asyncio
import io
import logging
import sys
import traceback
from contextlib import asynccontextmanager
from datetime import datetime

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from config import LOG_DIR, check_env
from database import init_db
from maps import (
    geocode_address,
    get_nearby_transit_schedules,
    get_nearby_transit_stops,
    get_transit_directions,
    maps_available,
)
from models import (
    HomeRouteRequest,
    IntentResult,
    QueryRequest,
    QueryResponse,
    SynthesizeRequest,
    TranscribeResponse,
)
from nlp.response_builder import build_response, _format_nearest
from scrapers import get_available_routes, get_concerts, get_route
from scrapers.ttc_data import populate_cache_from_csv
from services import filter_concerts, handle_query, search_stops_smart
from voice.stt import transcribe

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / 'app.log', encoding='utf-8'),
    ],
)
log = logging.getLogger('main')


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = check_env()
    if missing:
        log.warning('Missing env vars: %s', missing)
    init_db()
    routes = populate_cache_from_csv()
    log.info('TTC: %d routes loaded', len(routes))
    log.info('Google Maps: %s', maps_available())
    from scrapers.tkt_scraper import warm_concert_cache
    warm_concert_cache()
    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title='თბილისის ხელმისაწვდომი ასისტენტი',
    version='2.0.0',
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


# ── Utility ───────────────────────────────────────────────────────────────────

@app.get('/', include_in_schema=False)
def root():
    return RedirectResponse('/app')


@app.get('/health')
def health():
    return {
        'status': 'ok',
        'time': datetime.now().isoformat(),
        'routes': get_available_routes(),
        'google_maps': maps_available(),
    }


@app.get('/debug/routes')
def debug_routes():
    return [
        {'path': r.path, 'methods': sorted(r.methods)}
        for r in app.routes
        if isinstance(r, APIRoute)
    ]


@app.get('/debug/filter')
async def debug_filter():
    from collections import Counter
    from database import load_concerts
    from scrapers.tkt_scraper import _filter_by_days
    cached, _ = load_concerts()
    return {
        'server_time': datetime.now().isoformat(),
        'total_cached': len(cached or []),
        'category_counts': dict(Counter(c.get('category', '?') for c in (cached or []))),
        'days_7': len(_filter_by_days(cached or [], 7)),
        'days_30': len(_filter_by_days(cached or [], 30)),
        'google_maps': maps_available(),
    }


# ── Concert endpoints ─────────────────────────────────────────────────────────

@app.get('/concerts')
async def concerts_ep(
    days: int = Query(default=7, ge=1, le=30),
    category: str = Query(default=None),
):
    try:
        raw = await get_concerts(days_ahead=days)
        return filter_concerts(raw, category=category)
    except Exception as e:
        log.error('Concerts error: %s', e)
        raise HTTPException(503, 'TKT.ge სერვისი მიუწვდომელია.')


# ── Bus endpoints ─────────────────────────────────────────────────────────────

@app.get('/buses')
def available_routes_ep():
    return {'routes': get_available_routes()}


@app.get('/buses/{route_number}')
def bus_route_ep(route_number: str):
    route = get_route(route_number)
    if not route:
        raise HTTPException(404, f'{route_number} ვერ მოიძებნა.')
    return route


# ── Nearest-stop endpoints ────────────────────────────────────────────────────

@app.get('/nearest-stop')
def nearest_stop_ep(
    lat: float = Query(...),
    lng: float = Query(...),
    limit: int = Query(default=8, ge=1, le=20),
):
    if maps_available():
        results = get_nearby_transit_schedules(lat, lng)
        if results:
            return results[:limit]
    results = get_nearby_transit_stops(lat, lng, radius_m=500, limit=limit)
    if not results:
        return {
            'stops': [],
            'needs_geocoding': not maps_available(),
            'message': 'გაჩერება ვერ მოიძებნა.',
        }
    return results


@app.get('/nearest-stop-text')
def nearest_stop_text_ep(
    lat: float = Query(...),
    lng: float = Query(...),
    limit: int = Query(default=6, ge=1, le=20),
    stops_only: int = Query(default=0),
):
    """Formatted response_text + tts_text for nearest-stop queries.
    stops_only=1 → return stop names + walk times (no bus arrivals).
    stops_only=0 → return bus arrivals with times (default).
    """
    from nlp.response_builder import _format_nearest_stops
    if maps_available():
        stops = get_nearby_transit_schedules(lat, lng) or \
                get_nearby_transit_stops(lat, lng, radius_m=500, limit=limit)
    else:
        stops = get_nearby_transit_stops(lat, lng, radius_m=500, limit=limit)

    if stops_only:
        display, tts = _format_nearest_stops(stops[:limit])
    else:
        display, tts = _format_nearest(stops[:limit])
    return {'response_text': display, 'tts_text': tts}


# ── Home-route endpoint ───────────────────────────────────────────────────────

@app.post('/home-route')
def home_route_ep(body: HomeRouteRequest):
    log.info(
        'home-route: home=(%.5f,%.5f) cur=(%.5f,%.5f)',
        body.home_lat, body.home_lng, body.current_lat, body.current_lng,
    )

    directions = None
    if maps_available():
        directions = get_transit_directions(
            body.current_lat, body.current_lng,
            body.home_lat, body.home_lng,
        )

    home_stops = get_nearby_transit_stops(body.home_lat, body.home_lng, limit=5)
    cur_stops  = get_nearby_transit_stops(body.current_lat, body.current_lng, limit=5)

    # Mark which home stops are reachable from current location
    if home_stops and cur_stops:
        cur_routes = {s.get('route_number', '') for s in cur_stops}
        for s in home_stops:
            s['serves_current_location'] = s.get('route_number', '') in cur_routes

    direct_routes = sorted(
        {s.get('route_number', '') for s in home_stops}
        & {s.get('route_number', '') for s in cur_stops}
    ) if home_stops and cur_stops else []

    if not home_stops and not directions:
        msg = 'GPS ფუნქცია მიუწვდომელია.'
        return {
            'home_stops': [], 'current_stops': [], 'direct_routes': [],
            'directions': None, 'needs_geocoding': not maps_available(),
            'response_text': msg, 'tts_text': msg, 'source': 'none',
        }

    resp = build_response(
        IntentResult(intent='home_route'),
        results=home_stops,
        home_address='',
        directions=directions,
    )

    return {
        'home_stops': home_stops,
        'current_stops': cur_stops,
        'direct_routes': direct_routes,
        'directions': directions,
        'needs_geocoding': False,
        'source': 'google_maps' if directions else 'ttc_csv',
        'response_text': resp['response_text'],
        'tts_text': resp['tts_text'],
    }


# ── Journey endpoint ──────────────────────────────────────────────────────────

@app.get('/journey')
def journey_ep(
    q: str = Query(...),
    lat: float = Query(default=None),
    lng: float = Query(default=None),
):
    if lat is not None and lng is not None and maps_available():
        dest = geocode_address(q)
        if dest:
            directions = get_transit_directions(lat, lng, dest[0], dest[1])
            if directions:
                return {
                    'place_query': q, 'route_numbers': [], 'stops': [],
                    'directions': directions, 'source': 'google_maps',
                }

    results = search_stops_smart(q)
    if not results:
        raise HTTPException(404, f"'{q}' — ავტობუსი ვერ მოიძებნა.")

    routes_map: dict[str, list[str]] = {}
    for r in results:
        routes_map.setdefault(r['route_number'], []).append(r['stop_name'])

    return {
        'place_query': q,
        'route_numbers': list(routes_map.keys()),
        'stops': results,
        'source': 'ttc_csv',
    }


# ── Geocode endpoint ──────────────────────────────────────────────────────────

@app.post('/geocode')
async def geocode_ep(address: str = Query(...)):
    result = geocode_address(address)
    if not result:
        raise HTTPException(404, f'მისამართი ვერ მოიძებნა: {address}')
    return {'lat': result[0], 'lng': result[1], 'address': address}


# ── Main query endpoint ───────────────────────────────────────────────────────

@app.post('/query', response_model=QueryResponse)
async def query_ep(body: QueryRequest):
    """Delegates entirely to services.handle_query."""
    return await handle_query(body)


# ── Voice endpoints ───────────────────────────────────────────────────────────

@app.post('/transcribe', response_model=TranscribeResponse)
async def transcribe_ep(
    audio: UploadFile = File(...),
    engine: str = Query(default='google', pattern='^(whisper|google)$'),
):
    try:
        return transcribe(await audio.read(), engine=engine)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f'STT ვერ მოხერხდა: {e}')


@app.post('/synthesize')
async def synthesize_ep(body: SynthesizeRequest):
    """
    Run edge-tts in a dedicated thread with its own event loop
    (required on Windows to avoid ProactorEventLoop conflicts).
    """
    import concurrent.futures
    import edge_tts

    text = str(body.text)

    def _run() -> bytes:
        import asyncio as _asyncio
        if sys.platform == 'win32':
            _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        try:
            async def _go() -> bytes:
                buf = io.BytesIO()
                async for chunk in edge_tts.Communicate(text, 'ka-GE-EkaNeural').stream():
                    if chunk['type'] == 'audio':
                        buf.write(chunk['data'])
                return buf.getvalue()
            return loop.run_until_complete(_go())
        finally:
            loop.close()

    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            audio = await loop.run_in_executor(pool, _run)
        if not audio:
            raise RuntimeError('edge-tts returned empty audio.')
        return Response(
            content=audio,
            media_type='audio/mpeg',
            headers={'Content-Length': str(len(audio)), 'Cache-Control': 'no-cache'},
        )
    except Exception as e:
        raise HTTPException(500, f'TTS ვერ მოხერხდა: {e}')


# ── Static frontend ───────────────────────────────────────────────────────────

app.mount('/app', StaticFiles(directory='../frontend', html=True), name='frontend')


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='127.0.0.1', port=8001, reload=True)