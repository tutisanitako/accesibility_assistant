"""backend/services/concert_service.py"""
import re, logging
from datetime import datetime, timedelta, date

log = logging.getLogger(__name__)

_MONTHS_SHORT = {'იან':1,'თებ':2,'მარ':3,'აპრ':4,'მაი':5,'ივნ':6,
                 'ივლ':7,'აგვ':8,'სექ':9,'ოქტ':10,'ნოე':11,'დეკ':12}

_GEO_SUFFIXES = re.compile(
    r'(?:ში|ზე|ად|ს|თვის|სთვის|ისთვის|სთან|ისთან|დან|იდან|ამდე|ისამდე|ობა|ებ|ებში|ური|ურ|ში|ვე)$'
)
_GEO_STOP_WORDS = {
    'ახლა','ახლო','ყველა','ვინმე','ვინც','ხდება','შეიძლება','ამბობს','ყველა',
    'ეს','ის','ამ','ამის','ამისათვის','ამაში','ასეთ','ასეთი','თვითონ',
}

def _parse_date(date_str: str):
    """Parse 'DD MMM' style date string → date object."""
    if not date_str: return None
    if ' - ' in date_str: return None
    parts = date_str.strip().split()
    if len(parts) < 2: return None
    try:
        day   = int(parts[0])
        month = _MONTHS_SHORT.get(parts[1][:3])
        if not month: return None
        year  = datetime.now().year
        d     = datetime(year, month, day).date()
        if d < datetime.now().date() - timedelta(days=1):
            d = datetime(year+1, month, day).date()
        return d
    except (ValueError, KeyError): return None


def _parse_time(time_str: str):
    """Parse 'HH:MM' → (h, m) or None."""
    if not time_str or time_str == 'N/A': return None
    try:
        h, m = map(int, time_str.split(':'))
        return (h, m)
    except Exception: return None


def _strip_geo_suffix(word: str) -> str:
    """Strip common Georgian declension suffixes for fuzzy matching."""
    if word in _GEO_STOP_WORDS: return ''
    w = word.lower()
    for _ in range(2):
        stripped = _GEO_SUFFIXES.sub('', w)
        if stripped and stripped != w:
            w = stripped
        else:
            break
    return w if len(w) >= 3 else ''


def filter_concerts(concerts: list, category: str | None = None,
                    specific_date: str | None = None,
                    venue_filter: str | None = None,
                    days_ahead: int | None = 7) -> list:
    """
    Filter concerts by category, date, venue, and days window.

    days_ahead=0 → TODAY only (also filters out events whose time has passed).
    days_ahead=1 → TOMORROW only.
    days_ahead=N → within N days from tomorrow.
    specific_date → exact match on date string.
    """
    now      = datetime.now()
    today    = now.date()
    now_hm   = (now.hour, now.minute)
    results  = []

    for c in concerts:
        # Category filter
        cat = (c.get('category') or '').lower()
        if category and category.lower() not in cat:
            continue

        # Venue filter (fuzzy)
        if venue_filter:
            venue = (c.get('venue') or '').lower()
            stems = [_strip_geo_suffix(w) for w in venue_filter.lower().split()]
            if not any(s and s in venue for s in stems if s):
                continue

        # Date parsing
        event_date = _parse_date(c.get('date',''))
        event_time = _parse_time(c.get('time',''))

        # specific_date match (DD MMM format)
        if specific_date:
            sd = specific_date.strip()
            if re.match(r'\d{1,2}\s+\w+', sd):
                target = _parse_date(sd)
                if not target or event_date != target:
                    continue
            elif sd in ('ხვალ','tomorrow'):
                target = today + timedelta(days=1)
                if event_date != target:
                    continue
            elif sd in ('დღეს','today'):
                if event_date != today:
                    continue
                # Also filter out events that have already passed today
                if event_time and event_time <= now_hm:
                    continue
            else:
                if str(event_date) != sd and c.get('date','') != sd:
                    continue

        # days_ahead window (only applied when specific_date not set)
        elif days_ahead is not None:
            if event_date is None:
                continue
            if days_ahead == 0:
                # TODAY: must be today AND not yet passed
                if event_date != today:
                    continue
                if event_time and event_time <= now_hm:
                    continue  # event already started/ended
            elif days_ahead == 1:
                # TOMORROW only
                tomorrow = today + timedelta(days=1)
                if event_date != tomorrow:
                    continue
            else:
                # Within next N days
                if event_date < today or event_date > today + timedelta(days=days_ahead):
                    continue

        results.append(c)

    return results


def find_events_by_name(event_name: str) -> list:
    """
    Fuzzy-match event_name against all cached concerts.
    Returns sorted list — exact matches first, then partial matches.
    """
    if not event_name: return []
    from database import load_concerts
    cached, _ = load_concerts()
    if not cached: return []

    query_stems = [_strip_geo_suffix(w) for w in event_name.split()]
    query_stems = [s for s in query_stems if s and len(s) >= 2]
    if not query_stems: return []

    exact   = []
    partial = []

    for c in cached:
        name = c.get('name','').lower()
        if not name: continue

        # Exact (after lowercasing)
        if event_name.lower() in name or name in event_name.lower():
            exact.append((0, c)); continue

        # Stem-level matching
        name_stems = [_strip_geo_suffix(w) for w in name.split()]
        name_stems = [s for s in name_stems if s and len(s) >= 2]
        hits = sum(1 for qs in query_stems if any(qs in ns for ns in name_stems))
        if hits > 0:
            score = hits / max(len(query_stems), 1)
            partial.append((1 - score, c))  # lower score = better match

    combined = sorted(exact, key=lambda x: x[0]) + sorted(partial, key=lambda x: x[0])
    seen = set(); out = []
    for _, c in combined:
        k = (c.get('name',''), c.get('date',''), c.get('time',''), c.get('venue',''))
        if k not in seen: seen.add(k); out.append(c)
    return out


def get_first_venue(concerts: list) -> str | None:
    for c in concerts:
        v = c.get('venue','')
        if v and v != 'N/A': return v
    return None