import asyncio, sys
import traceback

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging, re
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from config import check_env, LOG_DIR
from database import init_db
from models import QueryRequest, QueryResponse, TranscribeResponse, SynthesizeRequest, HomeRouteRequest
from scrapers import get_concerts, get_route, search_routes_by_stop, get_available_routes
from scrapers.ttc_data import populate_cache_from_csv
from nlp import parse_intent, build_response
from voice.stt import transcribe
from maps import (get_nearby_transit_stops, get_transit_directions,
                  get_nearby_transit_schedules, geocode_address, maps_available)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / 'app.log', encoding='utf-8'),
    ],
)
log = logging.getLogger('main')

_NON_TBILISI = {'სენაკ','ბათუმ','კუთაის','გორ','რუსთავ','ზუგდიდ','ქუთაის','ფოთ',
                'ახალციხ','ამბროლაურ','ოზურგეთ','სიღნაღ','თელავ','ლანჩხუთ','ოჩამჩირ','სოხუმ'}

_VENUE_NOISE = {'თეატრი','თეატრ','სახელობის','სახ','სახელობ','და','ან','ის','ში','ზე',
                'opera','theatre','theater','the'}

def _is_tbilisi(venue): return not any(kw in venue.lower() for kw in _NON_TBILISI)


def _venue_matches(query_venue: str, stored_venue: str) -> bool:
    import re
    q = query_venue.lower()
    s = stored_venue.lower()
    SUFFIXES = ['სთანაც','ასთანაც','ისთვის','სთან','ასთან','ებში','ებზე',
                'ებს','ისკენ','ისგან','იდან','ში','ზე','ად','ით','სკენ','ის','ს']
    VENUE_NOISE = {'თეატრი','თეატრ','სახელობის','სახ','და','ან','ის','ში','ზე'}
    words_raw = [w for w in re.split(r'[\s/.,;()\[\]]+', q) if len(w) >= 3]
    stems = set()
    for w in words_raw:
        if w in VENUE_NOISE:
            continue
        stems.add(w)
        for suf in SUFFIXES:
            if w.endswith(suf) and len(w) > len(suf) + 2:
                stems.add(w[:-len(suf)])
                break
    return any(len(stem) >= 3 and stem in s for stem in stems)


def _search_stops_smart(place):
    words = re.findall(r'[\u10D0-\u10FF]+', place)
    tried = set()
    for term in sorted(words, key=len, reverse=True):
        if term in tried or len(term) < 3: continue
        tried.add(term)
        r = search_routes_by_stop(term)
        if r: return r
    for term in sorted(words, key=len, reverse=True):
        if len(term) < 5: continue
        stem = term[:-2]
        if stem in tried: continue
        tried.add(stem)
        r = search_routes_by_stop(stem)
        if r: return r
    return []


def _find_all_events_in_cache(event_name: str) -> list[dict]:
    from database import load_concerts
    cached, _ = load_concerts()
    if not cached or not event_name: return []
    name_lower = event_name.lower()
    exact = [c for c in cached if name_lower in c.get('name','').lower()]
    if exact: return exact
    words = [w for w in name_lower.split() if len(w) > 2]
    if not words: return []
    scored = {}
    for c in cached:
        cname = c.get('name','').lower()
        score = sum(1 for w in words if w in cname)
        if score > 0:
            if cname not in scored:
                scored[cname] = {'score': score, 'events': []}
            scored[cname]['events'].append(c)
    if not scored: return []
    best = max(scored.items(), key=lambda x: x[1]['score'])
    return best[1]['events']


@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = check_env()
    if missing: log.warning('Missing env: %s', missing)
    init_db()
    routes = populate_cache_from_csv()
    log.info('TTC: %d routes', len(routes))
    log.info('Google Maps: %s', maps_available())
    from scrapers.tkt_scraper import warm_concert_cache
    warm_concert_cache()
    yield

app = FastAPI(title='თბილისის ხელმისაწვდომი ასისტენტი', version='1.9.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

@app.get('/', include_in_schema=False)
def root(): return RedirectResponse('/app')

@app.get('/health')
def health():
    return {'status':'ok','time':datetime.now().isoformat(),
            'routes':get_available_routes(),'google_maps':maps_available()}

@app.get('/debug/routes')
def debug_routes():
    return [{'path':r.path,'methods':sorted(r.methods)}
            for r in app.routes if isinstance(r, APIRoute)]

@app.get('/concerts')
async def concerts_ep(days: int = Query(default=7, ge=1, le=30),
                      category: str = Query(default=None)):
    try:
        results = await get_concerts(days_ahead=days)
        if category:
            results = [c for c in results if c.get('category') == category]
        return [c for c in results
                if c.get('price') != 'გაყიდულია' and _is_tbilisi(c.get('venue',''))]
    except Exception as e:
        log.error('Concerts: %s', e)
        raise HTTPException(503, 'TKT.ge სერვისი მიუწვდომელია.')

@app.get('/buses')
def available_routes(): return {'routes': get_available_routes()}

@app.get('/buses/{route_number}')
def bus_route(route_number: str):
    route = get_route(route_number)
    if not route: raise HTTPException(404, f"{route_number} ვერ მოიძებნა.")
    return route

@app.get('/nearest-stop')
def nearest_stop(lat: float = Query(...), lng: float = Query(...),
                 limit: int = Query(default=8, ge=1, le=20)):
    if maps_available():
        results = get_nearby_transit_schedules(lat, lng)
        if results:
            return results[:limit]
    results = get_nearby_transit_stops(lat, lng, radius_m=500, limit=limit)
    if not results:
        return {'stops': [], 'needs_geocoding': not maps_available(),
                'message': 'გაჩერება ვერ მოიძებნა.'}
    return results

@app.get('/nearest-stop-text')
def nearest_stop_text(lat: float = Query(...), lng: float = Query(...),
                      limit: int = Query(default=6, ge=1, le=20)):
    """Returns formatted response_text + tts_text for nearest stops."""
    from nlp.response_builder import _format_nearest
    if maps_available():
        results = get_nearby_transit_schedules(lat, lng)
        if results:
            stops = results[:limit]
        else:
            stops = get_nearby_transit_stops(lat, lng, radius_m=500, limit=limit)
    else:
        stops = get_nearby_transit_stops(lat, lng, radius_m=500, limit=limit)

    display, tts = _format_nearest(stops)
    return {'response_text': display, 'tts_text': tts}


@app.post('/home-route')
def home_route(body: HomeRouteRequest):
    log.info('home-route: home=(%.5f,%.5f) cur=(%.5f,%.5f)',
             body.home_lat, body.home_lng, body.current_lat, body.current_lng)

    # ── 1. Try Google Maps transit directions ──────────────────
    directions = None
    if maps_available():
        directions = get_transit_directions(
            body.current_lat, body.current_lng,
            body.home_lat, body.home_lng,
        )

    # ── 2. Find stops near home and near current location ──────
    home_stops = get_nearby_transit_stops(body.home_lat, body.home_lng, limit=5)
    cur_stops = get_nearby_transit_stops(body.current_lat, body.current_lng, limit=5)

    # ── 3. Find routes that serve both locations ───────────────
    common = set()
    if home_stops and cur_stops:
        home_routes = {s.get('route_number', '') for s in home_stops}
        cur_routes = {s.get('route_number', '') for s in cur_stops}
        common = home_routes & cur_routes

    for s in home_stops:
        s['serves_current_location'] = s.get('route_number', '') in common

    # ── 4. Reverse-geocode home coords to get a readable address
    home_address = ''
    try:
        from maps import _nominatim_geocode
        pass
    except Exception:
        pass

    # ── 5. Build response text via response_builder ───────────
    from nlp.response_builder import build_response
    from models import IntentResult

    intent_obj = IntentResult(intent='home_route')

    resp = build_response(
        intent=intent_obj,
        results=home_stops,
        home_address=home_address,
        directions=directions,
    )

    # ── 6. Return everything the frontend needs ────────────────
    if not home_stops and not directions:
        return {
            'home_stops': [],
            'current_stops': [],
            'direct_routes': [],
            'directions': None,
            'needs_geocoding': not maps_available(),
            'message': 'GPS ფუნქცია მიუწვდომელია.',
            'response_text': 'GPS ფუნქცია მიუწვდომელია.',
            'tts_text': 'GPS ფუნქცია მიუწვდომელია.',
            'source': 'none',
        }

    return {
        'home_stops': home_stops,
        'current_stops': cur_stops,
        'direct_routes': sorted(common),
        'directions': directions,
        'needs_geocoding': False,
        'source': 'google_maps' if directions else 'ttc_csv',
        'response_text': resp['response_text'],
        'tts_text': resp['tts_text'],
    }

@app.post('/geocode')
async def geocode_ep(address: str = Query(...)):
    result = geocode_address(address)
    if not result: raise HTTPException(404, f'მისამართი ვერ მოიძებნა: {address}')
    return {'lat': result[0], 'lng': result[1], 'address': address}

@app.get('/journey')
def journey_ep(q: str = Query(...),
               lat: float = Query(default=None),
               lng: float = Query(default=None)):
    directions = None
    if lat is not None and lng is not None:
        dest = geocode_address(q)
        if dest:
            directions = get_transit_directions(lat, lng, dest[0], dest[1])
            if directions:
                return {'place_query':q,'route_numbers':[],'stops':[],
                        'directions':directions,'source':'google_maps'}
    results = _search_stops_smart(q)
    if not results:
        raise HTTPException(404, f"'{q}' — ავტობუსი ვერ მოიძებნა.")
    routes_map = {}
    for r in results:
        routes_map.setdefault(r['route_number'],[]).append(r['stop_name'])
    return {'place_query':q,'route_numbers':list(routes_map.keys()),
            'stops':results,'source':'ttc_csv'}


@app.post('/query', response_model=QueryResponse)
async def query_ep(body: QueryRequest):
    intent = parse_intent(body.text)
    log.info('Intent=%-18s date=%r cat=%r venue=%r event=%r',
             intent.intent, intent.specific_date, intent.category,
             intent.venue, intent.event_name)
    print(f'>>> INTENT={intent.intent} cat={intent.category!r} '
          f'date={intent.specific_date!r} venue={intent.venue!r} '
          f'event={intent.event_name!r}', flush=True)

    results, venue_bus_offer, event_detail, directions = [], None, None, None

    if intent.intent == 'concert_search':
        days = intent.days if intent.days is not None else 7
        results = await get_concerts(days_ahead=days)
        results = [c for c in results
                   if c.get('price') != 'გაყიდულია' and _is_tbilisi(c.get('venue',''))]

        if intent.category:
            results = [c for c in results if c.get('category') == intent.category]

        if intent.specific_date:
            df = intent.specific_date.strip()
            parts = df.split()
            if len(parts) == 2:
                day_s = parts[0].lstrip('0')
                mon_s = parts[1][:3]
                results = [c for c in results
                           if c.get('date','').split()[0].lstrip('0') == day_s
                           and mon_s in c.get('date','')]
            else:
                results = [c for c in results if df.lower() in c.get('date','').lower()]

        if intent.venue:
            results = [c for c in results
                       if _venue_matches(intent.venue, c.get('venue',''))
                       or _venue_matches(intent.venue, c.get('name',''))]
            log.info('After venue filter %r: %d results', intent.venue, len(results))

        venues = list({c['venue'] for c in results[:10]
                       if c.get('venue') and c['venue'] != 'N/A'
                       and _is_tbilisi(c.get('venue',''))})
        if venues: venue_bus_offer = venues[0]

    elif intent.intent == 'event_detail':
        from database import load_concerts
        import asyncio as _asyncio
        cached, _ = load_concerts()
        if not cached:
            log.info('Cache empty — waiting for scrape (max 90s)')
            for _ in range(18):
                await _asyncio.sleep(5)
                cached, _ = load_concerts()
                if cached:
                    log.info('Cache ready: %d events', len(cached))
                    break
        all_matches = _find_all_events_in_cache(intent.event_name or '')
        log.info('event_detail: %r → %d matches', intent.event_name, len(all_matches))
        if all_matches:
            names = list({c.get('name','') for c in all_matches})
            log.info('Matched: %s', names)
        event_detail = all_matches
        results = all_matches[:10]

        if getattr(body, 'context_date', None) and event_detail:
            # Filter events to only those matching the context date
            from scrapers.tkt_scraper import _parse_date
            ctx_dt = _parse_date(body.context_date)
            if ctx_dt:
                filtered_ed = [e for e in event_detail
                               if _parse_date(e.get('date','')) == ctx_dt]
                if filtered_ed:
                    event_detail = filtered_ed
                    results = filtered_ed[:10]

    elif intent.intent == 'bus_search':
        lower_text = body.text.lower()
        if any(kw in lower_text for kw in {'ახლო გაჩერება', 'უახლოეს', 'ახლომდებარე'}) and maps_available():
            return QueryResponse(
                intent='nearest_stop',
                response_text=f'GPS-ით {intent.route or ""}-ე ავტობუსის ახლო გაჩერებებს ვეძებ...',
                results=[], venue_bus_offer=None)
        if intent.route:
            route = get_route(intent.route)
            if route: results = route['stops'][:5]

        if not intent.route:
            # No route number — user asked about buses at a place
            # (Fallback if not caught by extra_context intent modification)
            place_text = intent.place or _extract_place_from_text(body.text) if hasattr(sys.modules[__name__], '_extract_place_from_text') else intent.place
            if place_text and maps_available():
                dest = geocode_address(place_text)
                if dest:
                    schedules = get_nearby_transit_schedules(dest[0], dest[1])
                    if schedules:
                        results = schedules[:8]
                        intent = intent.model_copy(update={'intent': 'nearest_stop'})

    elif intent.intent == 'arrival_planning':
        place_clean = (intent.place or '').strip()
        if place_clean:
            dest_coords = geocode_address(place_clean)
            if dest_coords and maps_available():
                origin_lat = body.lat or 41.6941
                origin_lng = body.lng or 44.8337
                directions = get_transit_directions(origin_lat, origin_lng, dest_coords[0], dest_coords[1])


    elif intent.intent == 'journey_search':
        place_clean = (intent.place or '').strip()

        HOME_DEST_PATTERNS = [
            'სახლამდე', 'სახლში მივი', 'სახლისკენ',
            'სახლთან მისასვლელ', 'სახლში',
        ]
        place_lower = place_clean.lower()
        is_home_dest = any(p in place_lower for p in HOME_DEST_PATTERNS)
        if not is_home_dest and intent.place:
            is_home_dest = any(p in (intent.place or '').lower() for p in HOME_DEST_PATTERNS)

        if is_home_dest:
            # Treat as home_route — just redirect intent
            intent = intent.model_copy(update={'intent': 'home_route'})
            return QueryResponse(intent='home_route',
                                 response_text='სახლში მიმავალ მარშრუტს ვეძებ...',
                                 tts_text='სახლში მიმავალ მარშრუტს ვეძებ...',
                                 results=[], venue_bus_offer=None)

        if place_clean and len(place_clean) > 1:
            dest_coords = geocode_address(place_clean)
            if dest_coords and maps_available():
                origin_lat = body.lat or 41.6941
                origin_lng = body.lng or 44.8337

                if intent.origin and intent.origin not in {'სახლი', 'ჩემი', 'აქ', 'იქ'}:
                    origin_coords = geocode_address(intent.origin)
                    if origin_coords:
                        origin_lat, origin_lng = origin_coords
                        log.info('Origin (Gemini) %r → %s', intent.origin, origin_coords)
                elif not body.lat:
                    origin_match = re.search(r'([\u10D0-\u10FF]{3,})იდან', body.text)
                    if origin_match:
                        origin_word = origin_match.group(1)
                        if origin_word not in {'სახლ', 'ჩემ', 'იქ', 'აქ', 'მათ', 'ამ'}:
                            origin_coords = geocode_address(origin_word)
                            if origin_coords:
                                origin_lat, origin_lng = origin_coords
                                log.info('Origin (regex) %r → %s', origin_word, origin_coords)

                directions = get_transit_directions(origin_lat, origin_lng, dest_coords[0], dest_coords[1])
                log.info('Journey %r → Maps: %s', place_clean, 'ok' if directions else 'failed')
            if not directions:
                results = _search_stops_smart(place_clean)
            intent = intent.model_copy(update={'place': place_clean})

    elif intent.intent == 'home_route':
        return QueryResponse(intent='home_route',
                             response_text='სახლში მისასვლელ ავტობუსებს ვეძებ...',
                             results=[], venue_bus_offer=None)

    elif intent.intent == 'nearest_stop':
        return QueryResponse(
            intent='nearest_stop',
            response_text='ახლომდებარე ავტობუსებს ვეძებ...',
            results=[], venue_bus_offer=None)

    # ── Build extra_context for response_builder ──────────────────
    lower_text = body.text.lower()
    extra_context = {
        'original_text': body.text,
        'context_date':  getattr(body, 'context_date', None) or '',
    }

    # "ახლო გაჩერებები" vs "ახლო ავტობუსები"
    STOPS_ONLY_KW = ['გაჩერებ','სადგურ','stop','station',
                     'ახლო გაჩერება','უახლოეს გაჩერება','ახლომდებარე გაჩერება']
    if intent.intent == 'nearest_stop':
        if any(kw in lower_text for kw in STOPS_ONLY_KW):
            extra_context['stops_only'] = True

    # "რამდენ ხანში მოვა 305" — find nearest stop of specific route
    NEAREST_ROUTE_KW = ['რამდენ ხანში მოვა','რამდენ ხანში',
                        'როდის მოვა','მოვა ავტობუს','მოვა მარშრუტ']
    if intent.intent == 'bus_search' and intent.route:
        if any(kw in lower_text for kw in NEAREST_ROUTE_KW):
            extra_context['nearest_for_route'] = True
            # Get GPS-based nearby stops for this route
            if body.lat and body.lng and maps_available():
                from maps import get_nearby_transit_schedules
                gps_stops = get_nearby_transit_schedules(body.lat, body.lng)
                extra_context['gps_stops'] = gps_stops

    # "რა ავტობუსები გაივლის X" — list routes at a place
    BUSES_AT_KW = ['გაივლის','გაივლ','გადის','გაივლიან',
                   'ივლის','რა ავტობუს','which bus','what bus']
    if intent.intent in ('journey_search', 'bus_search', 'nearest_stop'):
        if any(kw in lower_text for kw in BUSES_AT_KW):
            extra_context['buses_at_place'] = True
            if intent.intent != 'bus_search':
                intent = intent.model_copy(update={'intent': 'bus_search',
                                                    'place': intent.place or intent.venue})

    # event_detail mode detection
    DATES_KW = ['რა დღეებ','რომელ დღეებ','სეანს','კვირ',
                'განმავლობ','გრაფიკ','განრიგ']
    VENUE_KW  = ['სად ტარდება','სად იმართება','სად არის','სად გაიმართება']
    if intent.intent == 'event_detail':
        if any(kw in lower_text for kw in DATES_KW):
            extra_context['dates_only'] = True
        elif any(kw in lower_text for kw in VENUE_KW):
            extra_context['venue_only'] = True

    resp = build_response(
        intent,
        results,
        venue_bus_offer=venue_bus_offer,
        event_detail=event_detail,
        directions=directions,
        extra_context=extra_context,
    )
    print(f'>>> RESPONSE ({len(resp["response_text"])} chars): {resp["response_text"][:200]!r}', flush=True)

    return QueryResponse(
        intent=intent.intent,
        response_text=resp['response_text'],
        tts_text=resp['tts_text'],
        results=[dict(r) if hasattr(r, '__dict__') else r for r in results[:10]],
        venue_bus_offer=venue_bus_offer,
        directions=directions,
    )


@app.post('/transcribe', response_model=TranscribeResponse)
async def transcribe_ep(audio: UploadFile = File(...),
                        engine: str = Query(default='google', pattern='^(whisper|google)$')):
    try:
        return transcribe(await audio.read(), engine=engine)
    except Exception as e:
        traceback.print_exc()  # <--- THIS IS THE NEW LINE
        raise HTTPException(500, f'STT ვერ მოხერხდა: {e}')

@app.post('/synthesize')
async def synthesize_ep(body: SynthesizeRequest):
    try:
        import concurrent.futures, io
        text = str(body.text)
        def _run():
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            try:
                import edge_tts
                async def _go():
                    buf = io.BytesIO()
                    async for chunk in edge_tts.Communicate(text, 'ka-GE-EkaNeural').stream():
                        if chunk['type'] == 'audio': buf.write(chunk['data'])
                    return buf.getvalue()
                return loop.run_until_complete(_go())
            finally: loop.close()
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            audio = await loop.run_in_executor(pool, _run)
        if not audio: raise RuntimeError('No audio.')
        return Response(content=audio, media_type='audio/mpeg',
                        headers={'Content-Length':str(len(audio)),'Cache-Control':'no-cache'})
    except Exception as e:
        raise HTTPException(500, f'TTS ვერ მოხერხდა: {e}')

@app.get('/debug/filter')
async def debug_filter():
    from database import load_concerts
    from scrapers.tkt_scraper import _filter_by_days
    from collections import Counter
    cached, _ = load_concerts()
    return {
        'server_time': datetime.now().isoformat(),
        'total_cached': len(cached or []),
        'category_counts': dict(Counter(c.get('category','?') for c in (cached or []))),
        'days_7': len(_filter_by_days(cached or [], 7)),
        'days_30': len(_filter_by_days(cached or [], 30)),
        'google_maps': maps_available(),
    }

app.mount('/app', StaticFiles(directory='../frontend', html=True), name='frontend')

if __name__ == '__main__':
    import uvicorn
    uvicorn.run('main:app', host='127.0.0.1', port=8001, reload=True)