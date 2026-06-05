# backend/services/bus_service.py

"""

Bus / transit service layer.

_search_stops_smart was previously defined in main.py, called from
both the /query endpoint and the /journey endpoint. Extracted here
so both callers share one implementation.
"""

import re
import logging
from scrapers import search_routes_by_stop
from maps import get_transit_directions, maps_available

log = logging.getLogger(__name__)


def search_stops_smart(place: str) -> list[dict]:
    """
    Multi-strategy stop name search.

    Pass 1 — try each Georgian word in `place`, longest first.
    Pass 2 — try stems (drop last 2 chars) for each long-enough word.

    Returns combined results from the first pass that yields anything.
    """
    words = re.findall(r'[\u10D0-\u10FF]+', place)
    tried: set[str] = set()

    # Pass 1: full words
    for term in sorted(words, key=len, reverse=True):
        if term in tried or len(term) < 3:
            continue
        tried.add(term)
        results = search_routes_by_stop(term)
        if results:
            log.info('search_stops_smart %r → match on %r (%d results)', place, term, len(results))
            return results

    # Pass 2: stems
    for term in sorted(words, key=len, reverse=True):
        if len(term) < 5:
            continue
        stem = term[:-2]
        if stem in tried:
            continue
        tried.add(stem)
        results = search_routes_by_stop(stem)
        if results:
            log.info('search_stops_smart %r → stem match on %r (%d results)', place, stem, len(results))
            return results

    log.info('search_stops_smart %r → no results', place)
    return []


def get_bus_arrival_from_maps(route_number: str, lat: float, lng: float) -> list[dict]:
    """
    Uses the Google Maps API to find the next arrival for a specific route.
    """
    if not maps_available():
        return []

    dest_lat = lat + 0.005
    dest_lng = lng + 0.005

    # Using the string format that matched your previous working logic
    directions = get_transit_directions(f"{lat},{lng}", f"{dest_lat},{dest_lng}")

    if directions and 'routes' in directions and len(directions['routes']) > 0:
        arrivals = []
        for route in directions['routes']:
            for leg in route.get('legs', []):
                for step in leg.get('steps', []):
                    transit = step.get('transit_details', {})
                    line = transit.get('line', {})
                    if str(line.get('short_name')) == str(route_number):
                        arrival_val = transit.get('arrival_time', {}).get('value')
                        stop_name = transit.get('departure_stop', {}).get('name')
                        arrivals.append({
                            'route_number': route_number,
                            'departure_time': arrival_val,
                            'stop_name': stop_name
                        })
        return arrivals
    return []