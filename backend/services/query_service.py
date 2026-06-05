"""backend/services/query_service.py"""
import asyncio, re, logging
from datetime import datetime, timedelta
from models import IntentResult, QueryRequest, QueryResponse
from scrapers import get_concerts, get_route
from nlp import parse_intent, build_response
from maps import (get_transit_directions, get_nearby_transit_schedules,
                  geocode_address, maps_available)
from .concert_service import filter_concerts, find_events_by_name, get_first_venue
from .bus_service import search_stops_smart

log = logging.getLogger(__name__)

_HOME_DEST_PATTERNS  = ['სახლამდე','სახლში მივი','სახლისკენ','სახლთან','სახლში']
_STOPS_ONLY_KW       = ['ყველაზე ახლო გაჩერება','ახლო გაჩერებ','ახლომდებარე გაჩერება',
                         'უახლოეს გაჩერება','ახლო გაჩერებები','გაჩერებები მითხარი']
_NEAREST_ROUTE_KW    = ['რამდენ ხანში','როდის მოვა']
_DATES_KW            = ['რა დღეებ','რომელ დღეებ','სეანს','კვირ','განმავლობ','გრაფიკ','განრიგ']
_VENUE_ONLY_KW       = ['სად ტარდება','სად იმართება','სად არის','სად გაიმართება',
                         'რომელ თეატრ','რომელ თეატრში']
_EVENT_AND_ROUTE_KW  = ['და როგორ მივიდე','და მისასვლელი','და გზა']
# "X-სთან" — location indicator for bus queries
_AT_PLACE_SUFFIX_RE  = re.compile(r'([\u10D0-\u10FF\s\d-]{3,}?)(?:სთან|სტან|თან)\s+')
# Repeat triggers — include common typos/variants
_REPEAT_KW           = [
    'გაიმეორე','გაიმეორეთ','გაიმეოარე','გაიმორე','გამეორე',
    'კვლავ','ახლიდან თქვი','ახლიდან','repeat','კიდევ ერთხელ',
    'ვერ გავიგე გაიმეორე','ვერ გავიგე, გაიმეორე',
    'ვერ გავიგე გაიმორე','ვერ გავიგე, გაიმორე',
]

_ALL_CATEGORIES      = ['კონცერტი','თეატრი','ოპერა']
_PER_CATEGORY_LIMIT  = 4


def _extract_place_at(text: str) -> str | None:
    """
    Extract place from patterns like 'X-სთან', 'X-სთანაც', 'X-ის მეტრო'.
    Used when Gemini doesn't extract intent.place for bus-at-place queries.
    """
    lower = text.lower()
    # Match "Xსთან" pattern
    m = _AT_PLACE_SUFFIX_RE.search(lower)
    if m:
        raw = m.group(1).strip(' -')
        # Restore case from original text (best-effort)
        idx = lower.index(raw)
        return text[idx:idx+len(raw)].strip()
    return None


def _smart_time(time_str: str, context_date: str = '') -> int | None:
    """
    Convert 'HH:MM' arrival time to Unix timestamp, smart AM/PM:
    If the target hour is already past today, use tomorrow.
    If context_date indicates ხვალ/tomorrow, use tomorrow.
    Returns Unix timestamp (int) or None.
    """
    if not time_str or ':' not in time_str:
        return None
    try:
        h, m = map(int, time_str.split(':'))
        now  = datetime.now()
        # If context says tomorrow, or the time has passed today → use tomorrow
        use_tomorrow = 'ხვალ' in (context_date or '').lower()
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        elif use_tomorrow:
            candidate += timedelta(days=1)
        # Subtract 10 min so user arrives 10 min early
        arrival = candidate - timedelta(minutes=10)
        return int(arrival.timestamp())
    except Exception:
        return None


async def handle_query(body: QueryRequest) -> QueryResponse:
    intent = parse_intent(body.text)
    lower  = body.text.lower()
    log.info('Intent=%-20s date=%r cat=%r venue=%r event=%r',
             intent.intent, intent.specific_date, intent.category,
             intent.venue, intent.event_name)

    # ── REPEAT ───────────────────────────────────────────────────────────────
    # Check before everything else — if any repeat keyword is in the text, signal repeat
    if any(kw in lower for kw in _REPEAT_KW):
        return QueryResponse(intent='repeat', response_text='', tts_text='', results=[])

    results         = []
    venue_bus_offer = None
    event_detail    = None
    directions      = None
    full_destination_name = None

    # ── SAVE HOME LOCATION ────────────────────────────────────────────────────
    if intent.intent == 'save_home_location':
        if intent.place and maps_available():
            coords = geocode_address(intent.place)
            if coords:
                return QueryResponse(
                    intent='save_home_location',
                    response_text='სახლის მისამართი შეინახა.',
                    tts_text='სახლის მისამართი შეინახა.',
                    results=[{'lat': coords[0], 'lng': coords[1], 'address': intent.place}],
                )
        return QueryResponse(
            intent='save_home_location',
            response_text='სახლის მისამართი შეინახა.',
            tts_text='სახლის მისამართი შეინახა.',
            results=[],
        )

    # ── CONCERT SEARCH ────────────────────────────────────────────────────────
    if intent.intent == 'concert_search':
        if intent.venue:
            intent.venue = _normalize_location(intent.venue)
        days = intent.days if intent.days is not None else 7
        raw  = await get_concerts(days_ahead=days)
        if intent.category:
            results = filter_concerts(raw, intent.category, intent.specific_date,
                                      intent.venue,
                                      days_ahead=days if not intent.specific_date else None)
        else:
            mixed = []
            for cat in _ALL_CATEGORIES:
                cat_r = filter_concerts(raw, cat, intent.specific_date, intent.venue,
                                        days_ahead=days if not intent.specific_date else None)
                seen: set[str] = set(); count = 0
                for c in cat_r:
                    n = c.get('name','')
                    if n not in seen:
                        seen.add(n); mixed.append(c); count += 1
                    if count >= _PER_CATEGORY_LIMIT: break
            results = mixed
        venue_bus_offer = get_first_venue(results)

    # ── EVENT DETAIL ──────────────────────────────────────────────────────────
    elif intent.intent == 'event_detail':
        from database import load_concerts
        cached, _ = load_concerts()
        if not cached:
            for _ in range(18):
                await asyncio.sleep(5)
                cached, _ = load_concerts()
                if cached: break

        all_matches = find_events_by_name(intent.event_name or '')
        log.info('event_detail: %r → %d matches', intent.event_name, len(all_matches))

        # Only filter by context_date if it looks like "DD MM" format, NOT "ხვალ" etc.
        if body.context_date and all_matches and re.match(r'\d{1,2}\s+\w+', body.context_date or ''):
            from scrapers.tkt_scraper import _parse_date
            ctx_dt = _parse_date(body.context_date)
            if ctx_dt:
                filtered = [e for e in all_matches if _parse_date(e.get('date','')) == ctx_dt]
                if filtered: all_matches = filtered

        event_detail = all_matches
        results      = all_matches[:10]

        # Combined: "როდისაა X და როგორ მივიდე"
        if any(kw in lower for kw in _EVENT_AND_ROUTE_KW) and event_detail:
            venue_name = event_detail[0].get('venue','') if event_detail else ''
            if venue_name and venue_name != 'N/A' and maps_available():
                dest_coords = geocode_address(venue_name)
                if dest_coords:
                    origin_lat = body.lat or 41.6941
                    origin_lng = body.lng or 44.8337
                    directions = get_transit_directions(
                        origin_lat, origin_lng, dest_coords[0], dest_coords[1])

    # ── BUS SEARCH ────────────────────────────────────────────────────────────
    elif intent.intent == 'bus_search':
        # Determine clean place name — guard against polluted context strings
        place_raw = (intent.place or '').strip()
        gw = re.findall(r'[\u10D0-\u10FF]+', place_raw)
        place_clean = place_raw if len(gw) <= 7 else ''

        # If Gemini didn't extract place, try regex extraction from raw text
        if not place_clean:
            place_clean = _extract_place_at(body.text) or ''

        has_named_place = bool(place_clean and len(place_clean) > 2 and maps_available())

        if intent.route and has_named_place:
            # "305 მოვა X-სთან" — schedule at named place for this route
            dest = geocode_address(place_clean)
            if dest:
                schedules = get_nearby_transit_schedules(dest[0], dest[1])
                results = [s for s in schedules
                           if str(s.get('route_number','')) == str(intent.route)]
                if not results: results = schedules[:5]
        elif intent.route:
            route = get_route(intent.route)
            if route: results = route['stops'][:5]
        elif has_named_place:
            # "რა ავტობუსები მოვა X-სთან"
            dest = geocode_address(place_clean)
            if dest:
                schedules = get_nearby_transit_schedules(dest[0], dest[1])
                if schedules: results = schedules[:10]

    # ── ARRIVAL PLANNING ──────────────────────────────────────────────────────
    elif intent.intent == 'arrival_planning':
        place_clean = (intent.place or '').strip()
        gw = re.findall(r'[\u10D0-\u10FF]+', place_clean)
        if len(gw) > 7: place_clean = ''
        if place_clean and maps_available():
            dest_coords = geocode_address(place_clean)
            if dest_coords:
                origin_lat = body.lat or 41.6941
                origin_lng = body.lng or 44.8337
                # Compute target departure timestamp (10 min before desired arrival)
                target_ts = _smart_time(intent.specific_date or '', body.context_date or '')
                directions = get_transit_directions(
                    origin_lat, origin_lng, dest_coords[0], dest_coords[1],
                    departure_time=target_ts)

    # ── JOURNEY SEARCH ────────────────────────────────────────────────────────
    elif intent.intent == 'journey_search':
        place_clean = (intent.place or '').strip()
        gw = re.findall(r'[\u10D0-\u10FF]+', place_clean)
        if len(gw) > 8:
            log.warning('journey_search: place polluted %r — clearing', place_clean)
            place_clean = ''

        if any(p in place_clean.lower() for p in _HOME_DEST_PATTERNS):
            return QueryResponse(
                intent='home_route',
                response_text='სახლში მიმავალ მარშრუტს ვეძებ...',
                tts_text='სახლში მიმავალ მარშრუტს ვეძებ...',
                results=[], venue_bus_offer=None,
            )

        # IMPROVEMENT: Use the explicit venue name if we are following up on an event
        target_place = place_clean
        if intent.venue:
            target_place = intent.venue

        if target_place and len(target_place) > 1 and maps_available():
            # 1. Try exact venue name
            search_query = target_place if "თეატრ" in target_place else f"{target_place} თეატრი"
            dest_coords = geocode_address(search_query)

            # 2. FALLBACK: If venue search fails, try searching for the theater name alone
            if not dest_coords and "თეატრი" in search_query:
                log.info("Geocoding failed for %r, trying generic name", search_query)
                dest_coords = geocode_address("მოზარდმაყურებელთა თეატრი")

            if dest_coords:
                # ... (rest of your logic remains the same)
                origin_lat = body.lat or 41.6941
                origin_lng = body.lng or 44.8337
                origin_resolved = _resolve_origin(body, intent)
                if origin_resolved:
                    origin_lat, origin_lng = origin_resolved

                dep_ts = _extract_time_from_text(body.text)
                directions = get_transit_directions(
                    origin_lat, origin_lng, dest_coords[0], dest_coords[1],
                    departure_time=dep_ts)

        if not directions:
            results = search_stops_smart(target_place)
        intent = intent.model_copy(update={'place': target_place})

    # ── HOME ROUTE ────────────────────────────────────────────────────────────
    elif intent.intent == 'home_route':
        return QueryResponse(
            intent='home_route',
            response_text='სახლში მისასვლელ ავტობუსებს ვეძებ...',
            tts_text='სახლში მისასვლელ ავტობუსებს ვეძებ...',
            results=[], venue_bus_offer=None,
        )

    # ── NEAREST STOP ─────────────────────────────────────────────────────────
    elif intent.intent == 'nearest_stop':
        extra_ctx = _build_extra_context(intent, body, lower)
        if extra_ctx.get('stops_only'):
            return QueryResponse(
                intent='nearest_stop',
                response_text='ახლომდებარე გაჩერებებს ვეძებ...',
                tts_text='ახლომდებარე გაჩერებებს ვეძებ...',
                results=[{'stops_only': True}], venue_bus_offer=None,
            )
        return QueryResponse(
            intent='nearest_stop',
            response_text='ახლომდებარე ავტობუსებს ვეძებ...',
            tts_text='ახლომდებარე ავტობუსებს ვეძებ...',
            results=[], venue_bus_offer=None,
        )

    # ── extra_context + response ──────────────────────────────────────────────
    extra_context = _build_extra_context(intent, body, lower)

    if intent.intent == 'event_detail' and any(kw in lower for kw in _EVENT_AND_ROUTE_KW):
        extra_context['event_with_route'] = True

    # Mark bus-at-named-place
    if intent.intent == 'bus_search':
        place_raw = (intent.place or '').strip() or (_extract_place_at(body.text) or '')
        gw = re.findall(r'[\u10D0-\u10FF]+', place_raw)
        place_for_ctx = place_raw if len(gw) <= 7 else ''
        if intent.route and place_for_ctx and results:
            extra_context['bus_at_named_place'] = True
            intent = intent.model_copy(update={'place': place_for_ctx})
        elif not intent.route and place_for_ctx and results:
            extra_context['buses_at_named_place'] = True
            intent = intent.model_copy(update={'place': place_for_ctx})

    resp = build_response(
        intent, results,
        venue_bus_offer=venue_bus_offer,
        event_detail=event_detail,
        directions=directions,
        extra_context=extra_context,
        dest_label=full_destination_name,
    )
    log.info('Response (%d chars): %s', len(resp['response_text']), resp['response_text'][:120])

    return QueryResponse(
        intent=intent.intent,
        response_text=resp['response_text'],
        tts_text=resp['tts_text'],
        results=[dict(r) if hasattr(r, '__dict__') else r for r in results[:10]],
        venue_bus_offer=venue_bus_offer,
        directions=directions,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _resolve_origin(body: QueryRequest, intent: IntentResult):
    _SELF_REF = {'სახლი','ჩემი','აქ','იქ'}
    if intent.origin and intent.origin.lower() in ('სახლი','home','სახლ'):
        if body.home_lat and body.home_lng:
            return body.home_lat, body.home_lng
    if intent.origin and intent.origin not in _SELF_REF and maps_available():
        coords = geocode_address(intent.origin)
        if coords: return coords
    if not body.lat and maps_available():
        m = re.search(r'([\u10D0-\u10FF]{3,})იდან', body.text)
        if m:
            word = m.group(1)
            if word not in {'სახლ','ჩემ','იქ','აქ','მათ','ამ'}:
                coords = geocode_address(word)
                if coords: return coords
    return None


def _extract_time_from_text(text: str) -> int | None:
    """
    Look for explicit time in query like 'საღამოს 10 საათზე', '22:00-ზე'.
    Returns Unix timestamp (for today or tomorrow as appropriate), or None.
    """
    # "HH:MM" literal
    m = re.search(r'(\d{1,2}):(\d{2})', text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        dt = datetime.now().replace(hour=h, minute=mn, second=0, microsecond=0)
        if dt <= datetime.now(): dt += timedelta(days=1)
        return int(dt.timestamp())
    # Georgian hour words with prefix
    prefix_map = {'დილის': 'am', 'საღამოს': 'pm', 'ღამის': 'night', 'შუადღის': 'noon'}
    hour_words = {
        'ერთ':1,'ორ':2,'სამ':3,'ოთხ':4,'ხუთ':5,'ექვს':6,'შვიდ':7,
        'რვა':8,'ცხრა':9,'ათ':10,'თერთმეტ':11,'თორმეტ':12,
    }
    lower = text.lower()
    for prefix, period in prefix_map.items():
        if prefix in lower:
            for word, h in hour_words.items():
                if word in lower and 'საათ' in lower[lower.index(word):lower.index(word)+10]:
                    if period == 'pm' and h < 12: h += 12
                    elif period == 'night' and h < 6: h += 0  # keep as is
                    dt = datetime.now().replace(hour=h, minute=0, second=0, microsecond=0)
                    if 'ხვალ' in lower: dt += timedelta(days=1)
                    elif dt <= datetime.now(): dt += timedelta(days=1)
                    return int(dt.timestamp())
    return None


def _build_extra_context(intent: IntentResult, body: QueryRequest, lower: str) -> dict:
    ctx: dict = {'original_text': body.text, 'context_date': body.context_date or ''}

    if intent.intent == 'nearest_stop':
        if any(kw in lower for kw in _STOPS_ONLY_KW):
            ctx['stops_only'] = True

    if intent.intent == 'bus_search' and intent.route:
        # Determine if a named place was specified
        place_raw = (intent.place or '').strip() or (_extract_place_at(body.text) or '')
        gw = re.findall(r'[\u10D0-\u10FF]+', place_raw)
        has_clean_place = bool(place_raw and len(gw) <= 7)
        if any(kw in lower for kw in _NEAREST_ROUTE_KW) and not has_clean_place:
            # "რამდენ ხანში მოვა 330" (no place) → find near user GPS
            ctx['nearest_for_route'] = True
            ctx['use_minutes'] = True
            if body.lat and body.lng and maps_available():
                ctx['gps_stops'] = get_nearby_transit_schedules(body.lat, body.lng)
        elif any(kw in lower for kw in _NEAREST_ROUTE_KW) and has_clean_place:
            # "რამდენ ხანში მოვა X-სთან 305" → use minutes for named-place too
            ctx['use_minutes'] = True

    if intent.intent == 'event_detail':
        if any(kw in lower for kw in _VENUE_ONLY_KW):
            ctx['venue_only'] = True
        elif any(kw in lower for kw in _DATES_KW):
            ctx['dates_only'] = True

    return ctx

def _normalize_location(place: str) -> str:
    """Normalize colloquial venue names to formal names."""
    mapping = {
        "ოპერა": "ზაქარია ფალიაშვილის სახელობის ოპერისა და ბალეტის თეატრი",
        "ოპერაში": "ზაქარია ფალიაშვილის სახელობის ოპერისა და ბალეტის თეატრი",
        "მოზარდმაყურებელთა": "ნოდარ დუმბაძის სახელობის მოზარდმაყურებელთა თეატრი"
    }
    # Check if the place matches or ends with the colloquial term
    clean_place = place.strip().lower()
    if clean_place in mapping:
        return mapping[clean_place]
    return place