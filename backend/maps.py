# backend/maps.py
"""
Google Maps integration for transit features.

Replaces the geocoded-CSV approach with:
  - Places API (Nearby Search) → find transit stops near a coordinate
  - Directions API (transit mode) → "take me home" / "how do I get to X"

Falls back to TTC CSV data if GOOGLE_MAPS_API_KEY is not set.

Cost estimate (Google $200/month free credit):
  - Nearby Search:   $0.032 / request  → ~6,250 free/month
  - Directions:      $0.010 / request  → ~20,000 free/month
  For a thesis demo this is effectively free.

Setup:
  1. Go to console.cloud.google.com
  2. Enable: "Places API", "Directions API", "Maps JavaScript API"
  3. Create an API key, add to .env as GOOGLE_MAPS_API_KEY=...
"""

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime

log = logging.getLogger(__name__)

_MAPS_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')


def _maps_key_available() -> bool:
    return bool(_MAPS_KEY and _MAPS_KEY != 'YOUR_KEY_HERE')


# ── Nearby transit stops ──────────────────────────────────────────────────────

def get_nearby_transit_stops(lat: float, lng: float, radius_m: int = 500, limit: int = 8) -> list[dict]:
    """
    Find transit stops near a coordinate using Google Places Nearby Search.
    Returns list of {name, lat, lng, place_id, distance_m} sorted by distance.
    Falls back to TTC CSV if no Maps key.
    """
    if not _maps_key_available():
        log.warning('GOOGLE_MAPS_API_KEY not set — using TTC CSV fallback')
        return _ttc_csv_fallback_nearest(lat, lng, limit)

    url = (
        'https://maps.googleapis.com/maps/api/place/nearbysearch/json'
        f'?location={lat},{lng}'
        f'&radius={radius_m}'
        f'&type=transit_station|bus_station|subway_station'
        f'&key={_MAPS_KEY}'
    )
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'TbilisiAssistant/1.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())

        if data.get('status') not in ('OK', 'ZERO_RESULTS'):
            log.error('Places API error: %s', data.get('status'))
            return _ttc_csv_fallback_nearest(lat, lng, limit)

        results = []
        for place in data.get('results', [])[:limit]:
            ploc = place['geometry']['location']
            dist = _haversine(lat, lng, ploc['lat'], ploc['lng'])
            results.append({
                'name':       place['name'],
                'lat':        ploc['lat'],
                'lng':        ploc['lng'],
                'place_id':   place['place_id'],
                'distance_m': round(dist),
                'schedule':   [],  # Maps API doesn't give schedules
                'route_number': '',
                'source':     'google_maps',
            })

        results.sort(key=lambda x: x['distance_m'])
        log.info('Places API: %d stops near (%.4f, %.4f)', len(results), lat, lng)
        return results

    except Exception as e:
        log.error('Places API failed: %s', e)
        return _ttc_csv_fallback_nearest(lat, lng, limit)


# ── Transit directions ────────────────────────────────────────────────────────

def get_transit_directions(
    origin_lat: float, origin_lng: float,
    dest_lat: float, dest_lng: float,
    language: str = 'ka',
) -> dict | None:
    """
    Get transit directions between two coordinates.
    Returns a dict with steps, duration, departure_time etc.
    Returns None if unavailable.
    """
    if not _maps_key_available():
        return None

    url = (
        'https://maps.googleapis.com/maps/api/directions/json'
        f'?origin={origin_lat},{origin_lng}'
        f'&destination={dest_lat},{dest_lng}'
        f'&mode=transit'
        f'&transit_mode=bus'
        f'&language={language}'
        f'&departure_time=now'
        f'&key={_MAPS_KEY}'
    )
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'TbilisiAssistant/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        if data.get('status') != 'OK':
            log.warning('Directions API: %s', data.get('status'))
            return None

        route = data['routes'][0]
        leg   = route['legs'][0]

        steps = []
        for step in leg.get('steps', []):
            if step.get('travel_mode') == 'TRANSIT':
                td = step.get('transit_details', {})
                line = td.get('line', {})
                dep  = td.get('departure_stop', {})
                arr  = td.get('arrival_stop', {})
                dep_time = td.get('departure_time', {}).get('text', '')
                arr_time = td.get('arrival_time', {}).get('text', '')
                steps.append({
                    'type':          'transit',
                    'line_name':     line.get('short_name') or line.get('name', ''),
                    'vehicle':       line.get('vehicle', {}).get('name', 'bus'),
                    'depart_stop':   dep.get('name', ''),
                    'arrive_stop':   arr.get('name', ''),
                    'departure_time': dep_time,
                    'arrival_time':  arr_time,
                    'num_stops':     td.get('num_stops', 0),
                    'duration':      step.get('duration', {}).get('text', ''),
                })
            elif step.get('travel_mode') == 'WALKING':
                steps.append({
                    'type':          'walking',
                    'duration':      step.get('duration', {}).get('text', ''),
                    'distance':      step.get('distance', {}).get('text', ''),
                    'instructions':  re.sub(r'<[^>]+>', '', step.get('html_instructions', '')),
                })

        return {
            'total_duration': leg.get('duration', {}).get('text', ''),
            'departure_time': leg.get('departure_time', {}).get('text', ''),
            'arrival_time':   leg.get('arrival_time', {}).get('text', ''),
            'steps':          steps,
            'source':         'google_maps',
        }

    except Exception as e:
        log.error('Directions API failed: %s', e)
        return None


def format_directions_georgian(directions: dict) -> str:
    """Turn a directions dict into a natural Georgian voice response."""
    if not directions:
        return ''

    lines = []
    total = directions.get('total_duration', '')
    dep   = directions.get('departure_time', '')
    arr   = directions.get('arrival_time', '')

    if total:
        lines.append(f'სულ დრო: {total}.')
    if dep and arr:
        lines.append(f'{dep}-ზე გასვლით {arr}-ზე მიხვალ.')

    for step in directions.get('steps', []):
        if step['type'] == 'walking':
            lines.append(f'ფეხით {step["distance"]} ({step["duration"]}).')
        elif step['type'] == 'transit':
            line = step['line_name']
            n    = step['num_stops']
            dep_s = step['depart_stop']
            arr_s = step['arrive_stop']
            dep_t = step['departure_time']
            lines.append(
                f'{dep_t}-ზე ავტობუსი {line}, '
                f'{dep_s}-დან, {n} გაჩერება, '
                f'{arr_s}-მდე.'
            )

    return ' '.join(lines)


# ── Geocode a text address ────────────────────────────────────────────────────

def geocode_address(address: str, region: str = 'ge') -> tuple[float, float] | None:
    """
    Convert a text address to (lat, lng) using Google Geocoding API.
    Returns None if not found or no key.
    Falls back to Nominatim (free, no key) if Maps key unavailable.
    """
    if _maps_key_available():
        url = (
            'https://maps.googleapis.com/maps/api/geocode/json'
            f'?address={urllib.parse.quote(address + ", Tbilisi, Georgia")}'
            f'&region={region}'
            f'&key={_MAPS_KEY}'
        )
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'TbilisiAssistant/1.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            if data.get('status') == 'OK':
                loc = data['results'][0]['geometry']['location']
                return loc['lat'], loc['lng']
        except Exception as e:
            log.warning('Google Geocoding failed: %s', e)

    # Fallback: Nominatim (free, no key, 1 req/sec limit)
    return _nominatim_geocode(address)


def _nominatim_geocode(address: str) -> tuple[float, float] | None:
    query = urllib.parse.urlencode({
        'q':            address + ', Tbilisi',
        'format':       'json',
        'limit':        1,
        'countrycodes': 'ge',
        'viewbox':      '44.6,41.6,45.1,41.8',
        'bounded':      1,
    })
    url = f'https://nominatim.openstreetmap.org/search?{query}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'TbilisiAssistant/1.0'})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception as e:
        log.warning('Nominatim geocode failed: %s', e)
    return None


# ── Nearby transit WITH real departure times ─────────────────────────────────

def get_nearby_transit_schedules(lat: float, lng: float) -> list[dict]:
    """
    Get nearby buses WITH real departure times using ONE Directions API call.
    Calls Directions from user location to Tbilisi Liberty Square.
    Parses all transit steps to find buses departing near the user.
    Returns list sorted by departure time.
    """
    if not _maps_key_available():
        return []

    # Tbilisi Liberty Square — good central destination that all buses pass through
    dest_lat, dest_lng = 41.6934, 44.8015

    url = (
        'https://maps.googleapis.com/maps/api/directions/json'
        f'?origin={lat},{lng}'
        f'&destination={dest_lat},{dest_lng}'
        f'&mode=transit'
        f'&transit_mode=bus'
        f'&alternatives=true'
        f'&departure_time=now'
        f'&language=ka'
        f'&key={_MAPS_KEY}'
    )

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'TbilisiAssistant/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        if data.get('status') != 'OK':
            log.warning('Transit schedules API: %s', data.get('status'))
            return []

        stops = []
        seen_keys = set()

        for route in data.get('routes', []):
            for leg in route.get('legs', []):
                steps = leg.get('steps', [])
                walk_step = None
                transit_step = None

                for step in steps:
                    if step.get('travel_mode') == 'WALKING' and walk_step is None:
                        walk_step = step
                    if step.get('travel_mode') == 'TRANSIT' and transit_step is None:
                        transit_step = step
                        break

                if not transit_step:
                    continue

                td        = transit_step.get('transit_details', {})
                line      = td.get('line', {})
                line_name = line.get('short_name') or line.get('name', '')
                dep_stop  = td.get('departure_stop', {})
                dep_time  = td.get('departure_time', {})
                stop_loc  = dep_stop.get('location', {})
                headsign  = td.get('headsign', '')

                key = (line_name, dep_stop.get('name', ''))
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                walk_dist = walk_step.get('distance', {}).get('text', '') if walk_step else ''
                walk_dur  = walk_step.get('duration', {}).get('text', '') if walk_step else ''
                walk_secs = walk_step.get('duration', {}).get('value', 0) if walk_step else 0
                dist_m    = walk_step.get('distance', {}).get('value', 0) if walk_step else 0

                stops.append({
                    'name':              dep_stop.get('name', ''),
                    'lat':               stop_loc.get('lat'),
                    'lng':               stop_loc.get('lng'),
                    'route_number':      line_name,
                    'departure_time':    dep_time.get('text', ''),
                    'departure_time_value': dep_time.get('value', 0),
                    'headsign':          headsign,
                    'walk_distance':     walk_dist,
                    'walk_duration':     walk_dur,
                    'walk_minutes':      max(1, round(walk_secs / 60)),
                    'distance_m':        int(dist_m),
                    'num_stops':         td.get('num_stops', 0),
                    'source':            'google_maps',
                    'schedule':          [],  # empty — we have departure_time instead
                })

        stops.sort(key=lambda x: x.get('departure_time_value', 0))
        log.info('Transit schedules: %d buses found near (%.4f,%.4f)', len(stops), lat, lng)
        return stops

    except Exception as e:
        log.error('Transit schedules failed: %s', e)
        return []


# ── Haversine ─────────────────────────────────────────────────────────────────

def _haversine(lat1, lng1, lat2, lng2) -> float:
    import math
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(p1) * math.cos(p2)
         * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── TTC CSV fallback ──────────────────────────────────────────────────────────

def _ttc_csv_fallback_nearest(lat: float, lng: float, limit: int) -> list[dict]:
    """Use geocoded TTC CSV data if available, otherwise empty list."""
    try:
        from database import get_all_cached_routes, load_bus_route
        candidates = []
        for rn in get_all_cached_routes():
            stops, _ = load_bus_route(rn)
            if not stops:
                continue
            for stop in stops:
                slat, slng = stop.get('lat'), stop.get('lng')
                if slat is None or slng is None:
                    continue
                dist = _haversine(lat, lng, slat, slng)
                candidates.append({
                    'route_number': rn,
                    'name':         stop['name'],
                    'stop_name':    stop['name'],
                    'stop_index':   stop['index'],
                    'lat':          slat,
                    'lng':          slng,
                    'distance_m':   round(dist),
                    'schedule':     stop.get('schedule', []),
                    'source':       'ttc_csv',
                })
        candidates.sort(key=lambda x: x['distance_m'])
        return candidates[:limit]
    except Exception as e:
        log.error('TTC CSV fallback failed: %s', e)
        return []


def maps_available() -> bool:
    return _maps_key_available()