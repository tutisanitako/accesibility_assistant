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