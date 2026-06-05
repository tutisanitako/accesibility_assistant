"""
backend/services/query_service.py
All query orchestration.
"""
import asyncio, re, logging
from models import IntentResult, QueryRequest, QueryResponse
from scrapers import get_concerts, get_route
from nlp import parse_intent, build_response
from maps import (get_transit_directions, get_nearby_transit_schedules,
                  geocode_address, maps_available)
from .concert_service import filter_concerts, find_events_by_name, get_first_venue
from .bus_service import search_stops_smart

log = logging.getLogger(__name__)

_HOME_DEST_PATTERNS  = ['სახლამდე','სახლში მივი','სახლისკენ','სახლთან მისასვლელ','სახლში']
_STOPS_ONLY_KW       = ['ყველაზე ახლო გაჩერება','ახლო გაჩერებ','ახლომდებარე გაჩერება',
                         'უახლოეს გაჩერება','nearest stop','nearest bus stop',
                         'გაჩერებები მითხარი','ახლო გაჩერებები']
_NEAREST_ROUTE_KW    = ['რამდენ ხანში მოვა','რამდენ ხანში','როდის მოვა']
# When user asks "what buses come to X" or "when does X bus come to Y"
_BUSES_AT_NAMED_KW   = ['რა ავტობუსები მოვა','რა ავტობუსები ჩავა','რა ავტობუსები გაივლის',
                         'which buses','what buses']
_BUS_AT_PLACE_KW     = ['სთან მოვა','სთან ჩავა','სთან გამოდის','სტანდე მოვა']
_DATES_KW            = ['რა დღეებ','რომელ დღეებ','სეანს','კვირ','განმავლობ','გრაფიკ','განრიგ']
_VENUE_ONLY_KW       = ['სად ტარდება','სად იმართება','სად არის','სად გაიმართება']
_EVENT_AND_ROUTE_KW  = ['და როგორ მივიდე','და მისასვლელი','და გზა']
_REPEAT_KW           = ['გაიმეორე','გაიმეორეთ','repeat','კიდევ ერთხელ',
                         'ვერ გავიგე, გაიმეორე','ვერ გავიგე გაიმეორე']

_ALL_CATEGORIES      = ['კონცერტი','თეატრი','ოპერა']
_PER_CATEGORY_LIMIT  = 4


async def handle_query(body: QueryRequest) -> QueryResponse:
    intent = parse_intent(body.text)
    lower  = body.text.lower()
    log.info('Intent=%-20s date=%r cat=%r venue=%r event=%r',
             intent.intent, intent.specific_date, intent.category,
             intent.venue, intent.event_name)

    # ── REPEAT ───────────────────────────────────────────────────────────────
    if any(kw in lower for kw in _REPEAT_KW):
        # Signal frontend to repeat last response
        return QueryResponse(
            intent='repeat',
            response_text='',
            tts_text='',
            results=[],
        )

    results         = []
    venue_bus_offer = None
    event_detail    = None
    directions      = None

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

        if body.context_date and all_matches:
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
        # Determine if a named place was mentioned
        # Use intent.place — but ONLY if it looks like a real place name
        # (not something injected by context enrichment)
        place_raw = (intent.place or '').strip()
        # Guard: if place contains stop-name fragments (>4 Georgian words), it's polluted — ignore
        geo_words = re.findall(r'[\u10D0-\u10FF]+', place_raw)
        place_clean = place_raw if len(geo_words) <= 6 else ''

        has_named_place = bool(place_clean and len(place_clean) > 2 and maps_available())

        if intent.route and has_named_place:
            # "რამდენ ხანში მოვა X-სთან 305" — schedule near named place for this route
            dest = geocode_address(place_clean)
            if dest:
                schedules = get_nearby_transit_schedules(dest[0], dest[1])
                results = [s for s in schedules
                           if str(s.get('route_number','')) == str(intent.route)]
                if not results: results = schedules[:3]
        elif intent.route:
            route = get_route(intent.route)
            if route: results = route['stops'][:5]
        elif has_named_place:
            # "რა ავტობუსები მოვა X-სთან" — all buses near X
            dest = geocode_address(place_clean)
            if dest:
                schedules = get_nearby_transit_schedules(dest[0], dest[1])
                if schedules:
                    results = schedules[:8]

    # ── ARRIVAL PLANNING ──────────────────────────────────────────────────────
    elif intent.intent == 'arrival_planning':
        place_clean = (intent.place or '').strip()
        if place_clean and maps_available():
            dest_coords = geocode_address(place_clean)
            if dest_coords:
                origin_lat = body.lat or 41.6941
                origin_lng = body.lng or 44.8337
                directions = get_transit_directions(
                    origin_lat, origin_lng, dest_coords[0], dest_coords[1],
                    )

    # ── JOURNEY SEARCH ────────────────────────────────────────────────────────
    elif intent.intent == 'journey_search':
        place_clean = (intent.place or '').strip()
        # Guard against polluted place from context enrichment
        geo_words = re.findall(r'[\u10D0-\u10FF]+', place_clean)
        if len(geo_words) > 6:
            log.warning('journey_search: place looks polluted %r — clearing', place_clean)
            place_clean = ''

        if any(p in place_clean.lower() for p in _HOME_DEST_PATTERNS):
            return QueryResponse(
                intent='home_route',
                response_text='სახლში მიმავალ მარშრუტს ვეძებ...',
                tts_text='სახლში მიმავალ მარშრუტს ვეძებ...',
                results=[], venue_bus_offer=None,
            )
        if place_clean and len(place_clean) > 1 and maps_available():
            dest_coords = geocode_address(place_clean)
            if dest_coords:
                origin_lat = body.lat or 41.6941
                origin_lng = body.lng or 44.8337
                origin_resolved = _resolve_origin(body, intent)
                if origin_resolved:
                    origin_lat, origin_lng = origin_resolved
                directions = get_transit_directions(
                    origin_lat, origin_lng, dest_coords[0], dest_coords[1])
        if not directions:
            results = search_stops_smart(place_clean)
        intent = intent.model_copy(update={'place': place_clean})

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
        extra_context = _build_extra_context(intent, body, lower)
        if extra_context.get('stops_only'):
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

    # Mark combined event+route
    if intent.intent == 'event_detail' and any(kw in lower for kw in _EVENT_AND_ROUTE_KW):
        extra_context['event_with_route'] = True

    # Mark bus-at-named-place variants
    if intent.intent == 'bus_search':
        place_raw = (intent.place or '').strip()
        geo_words = re.findall(r'[\u10D0-\u10FF]+', place_raw)
        place_clean = place_raw if len(geo_words) <= 6 else ''
        if intent.route and place_clean and results:
            extra_context['bus_at_named_place'] = True
            intent = intent.model_copy(update={'place': place_clean})
        elif not intent.route and place_clean and results:
            extra_context['buses_at_named_place'] = True
            intent = intent.model_copy(update={'place': place_clean})

    resp = build_response(
        intent, results,
        venue_bus_offer=venue_bus_offer,
        event_detail=event_detail,
        directions=directions,
        extra_context=extra_context,
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


def _build_extra_context(intent: IntentResult, body: QueryRequest, lower: str) -> dict:
    ctx: dict = {
        'original_text': body.text,
        'context_date':  body.context_date or '',
    }
    if intent.intent == 'nearest_stop':
        if any(kw in lower for kw in _STOPS_ONLY_KW):
            ctx['stops_only'] = True
    if intent.intent == 'bus_search' and intent.route:
        place_raw = (intent.place or '').strip()
        geo_words = re.findall(r'[\u10D0-\u10FF]+', place_raw)
        has_clean_place = bool(place_raw and len(geo_words) <= 6)
        if any(kw in lower for kw in _NEAREST_ROUTE_KW) and not has_clean_place:
            # "რამდენ ხანში მოვა 330 ავტობუსი" (no place) → find near user
            ctx['nearest_for_route'] = True
            if body.lat and body.lng and maps_available():
                ctx['gps_stops'] = get_nearby_transit_schedules(body.lat, body.lng)
    if intent.intent == 'event_detail':
        if any(kw in lower for kw in _VENUE_ONLY_KW):
            ctx['venue_only'] = True
        elif any(kw in lower for kw in _DATES_KW):
            ctx['dates_only'] = True
    return ctx