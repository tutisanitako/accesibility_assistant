"""
backend/services/concert_service.py
Venue matching, event lookup, concert filtering — single source of truth.
"""
import re
import logging
from datetime import datetime, timedelta, date as date_type
from database import load_concerts

log = logging.getLogger(__name__)

_NON_TBILISI = {
    'სენაკ','ბათუმ','ქუთაის','გორ','რუსთავ','ზუგდიდ','ფოთ',
    'ახალციხ','ამბროლაურ','ოზურგეთ','სიღნაღ','თელავ',
    'ლანჩხუთ','ოჩამჩირ','სოხუმ',
}
_VENUE_SUFFIXES = [
    'სთანაც','ასთანაც','ისთვის','სთან','ასთან',
    'ებში','ებზე','ებს','ისკენ','ისგან','იდან',
    'ში','ზე','ად','ით','სკენ','ის','ს',
]
_VENUE_NOISE = {'თეატრი','თეატრ','სახელობის','სახ','სახელობ','და','ან','ის','ში','ზე',
                'opera','theatre','theater','the'}

_MONTHS_SHORT = {'იან':1,'თებ':2,'მარ':3,'აპრ':4,'მაი':5,'ივნ':6,
                 'ივლ':7,'აგვ':8,'სექ':9,'ოქტ':10,'ნოე':11,'დეკ':12}


def is_tbilisi(venue: str) -> bool:
    return not any(kw in venue.lower() for kw in _NON_TBILISI)


def venue_matches(query_venue: str, stored_venue: str) -> bool:
    q = query_venue.lower()
    s = stored_venue.lower()
    words_raw = [w for w in re.split(r'[\s/.,;()\[\]]+', q) if len(w) >= 3]
    stems: set[str] = set()
    for w in words_raw:
        if w in _VENUE_NOISE:
            continue
        stems.add(w)
        for suf in _VENUE_SUFFIXES:
            if w.endswith(suf) and len(w) > len(suf) + 2:
                stems.add(w[:-len(suf)])
                break
    return any(len(stem) >= 3 and stem in s for stem in stems)


def _parse_concert_date(date_str: str):
    """Parse 'DD მაი' or 'DD მაი - DD მაი' → date object or None."""
    if not date_str:
        return None
    # Take first part of a range
    first = date_str.split(' - ')[0].strip()
    parts = first.split()
    if len(parts) < 2:
        return None
    try:
        day   = int(parts[0])
        month = _MONTHS_SHORT.get(parts[1][:3])
        if not month:
            return None
        year = datetime.now().year
        d = datetime(year, month, day).date()
        if d < datetime.now().date() - timedelta(days=1):
            d = datetime(year + 1, month, day).date()
        return d
    except (ValueError, KeyError):
        return None


def filter_concerts(
    concerts: list[dict],
    category: str | None = None,
    specific_date: str | None = None,
    venue: str | None = None,
    days_ahead: int | None = None,
) -> list[dict]:
    """
    Apply all filters:
      1. Remove sold-out + non-Tbilisi
      2. Category
      3. specific_date (exact date string match OR days_ahead window)
      4. Venue fuzzy match

    Note: tkt_scraper._filter_by_days already filters by days_ahead before
    results reach here, so days_ahead is only used when we need to re-filter
    (e.g. "ხვალ" where days=1 means tomorrow only, not today).
    """
    results = [
        c for c in concerts
        if c.get('price') != 'გაყიდულია' and is_tbilisi(c.get('venue', ''))
    ]

    if category:
        results = [c for c in results if c.get('category') == category]

    if specific_date:
        # specific_date is "DD მაი" format — match against event date
        df = specific_date.strip()
        parts = df.split()
        if len(parts) == 2:
            day_s = parts[0].lstrip('0')
            mon_s = parts[1][:3]
            results = [
                c for c in results
                if c.get('date', '').split()[0].lstrip('0') == day_s
                and mon_s in c.get('date', '')
            ]
        else:
            results = [c for c in results if df.lower() in c.get('date', '').lower()]

    elif days_ahead is not None:
        # Re-filter to exact window — needed when days=1 (tomorrow only)
        now     = datetime.now()
        today   = now.replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = today + timedelta(days=days_ahead - (1 if days_ahead > 0 else 0))
        window_end   = today + timedelta(days=days_ahead)

        # For days=0 → today; days=1 → tomorrow only; days=7 → within 7 days
        if days_ahead <= 1:
            target_date = (today + timedelta(days=days_ahead)).date()
            filtered = []
            for c in results:
                d = _parse_concert_date(c.get('date', ''))
                if d and d == target_date:
                    filtered.append(c)
            results = filtered
        # days > 1: tkt_scraper already applied the window, pass through

    if venue:
        before = len(results)
        results = [
            c for c in results
            if venue_matches(venue, c.get('venue', ''))
            or venue_matches(venue, c.get('name', ''))
        ]
        log.info('Venue filter %r: %d → %d', venue, before, len(results))

    return results


def find_events_by_name(event_name: str) -> list[dict]:
    cached, _ = load_concerts()
    if not cached or not event_name:
        return []
    name_lower = event_name.lower()
    exact = [c for c in cached if name_lower in c.get('name', '').lower()]
    if exact:
        return exact
    words = [w for w in name_lower.split() if len(w) > 2]
    if not words:
        return []
    scored: dict[str, dict] = {}
    for c in cached:
        cname = c.get('name', '').lower()
        score = sum(1 for w in words if w in cname)
        if score > 0:
            if cname not in scored:
                scored[cname] = {'score': score, 'events': []}
            scored[cname]['events'].append(c)
    if not scored:
        return []
    best = max(scored.items(), key=lambda x: x[1]['score'])
    log.info('find_events_by_name %r → best=%r score=%d count=%d',
             event_name, best[0], best[1]['score'], len(best[1]['events']))
    return best[1]['events']


def get_first_venue(concerts: list[dict]) -> str | None:
    for c in concerts[:10]:
        v = c.get('venue', '')
        if v and v != 'N/A' and is_tbilisi(v):
            return v
    return None