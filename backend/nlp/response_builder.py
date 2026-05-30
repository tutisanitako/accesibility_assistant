# backend/nlp/response_builder.py
import re, os, logging, json, subprocess, sys
from datetime import datetime, date, timedelta
from pathlib import Path
from models import IntentResult

log = logging.getLogger(__name__)

_CATEGORY_LABEL = {'კონცერტი':'კონცერტი','თეატრი':'სპექტაკლი','ოპერა':'ოპერა'}

_MONTHS_SHORT = {'იან':1,'თებ':2,'მარ':3,'აპრ':4,'მაი':5,'ივნ':6,
                 'ივლ':7,'აგვ':8,'სექ':9,'ოქტ':10,'ნოე':11,'დეკ':12}
_MONTH_GEN = {1:'იანვარს',2:'თებერვალს',3:'მარტს',4:'აპრილს',5:'მაისს',6:'ივნისს',
              7:'ივლისს',8:'აგვისტოს',9:'სექტემბერს',10:'ოქტომბერს',11:'ნოემბერს',12:'დეკემბერს'}
_DAY_ORDINAL = {
    1:'პირველ',2:'ორ',3:'სამ',4:'ოთხ',5:'ხუთ',6:'ექვს',7:'შვიდ',
    8:'რვა',9:'ცხრა',10:'ათ',11:'თერთმეტ',12:'თორმეტ',13:'ცამეტ',
    14:'თოთხმეტ',15:'თხუთმეტ',16:'თექვსმეტ',17:'ჩვიდმეტ',18:'თვრამეტ',
    19:'ცხრამეტ',20:'ოც',21:'ოცდაერთ',22:'ოცდაორ',23:'ოცდასამ',
    24:'ოცდაოთხ',25:'ოცდახუთ',26:'ოცდაექვს',27:'ოცდაშვიდ',28:'ოცდარვა',
    29:'ოცდაცხრა',30:'ოცდაათ',31:'ოცდათერთმეტ',
}
_HOUR_SPOKEN = {
    0:'შუაღამეს',1:'ღამის ერთ საათზე',2:'ღამის ორ საათზე',3:'ღამის სამ საათზე',
    4:'ღამის ოთხ საათზე',5:'დილის ხუთ საათზე',6:'დილის ექვს საათზე',7:'დილის შვიდ საათზე',
    8:'დილის რვა საათზე',9:'დილის ცხრა საათზე',10:'დილის ათ საათზე',11:'დილის თერთმეტ საათზე',
    12:'შუადღის თორმეტ საათზე',13:'შუადღის პირველ საათზე',14:'ორ საათზე',15:'სამ საათზე',
    16:'ოთხ საათზე',17:'ხუთ საათზე',18:'საღამოს ექვს საათზე',19:'საღამოს შვიდ საათზე',
    20:'საღამოს რვა საათზე',21:'საღამოს ცხრა საათზე',22:'საღამოს ათ საათზე',
    23:'საღამოს თერთმეტ საათზე',
}
_NON_TBILISI = {'სენაკ','ბათუმ','ქუთაის','გორ','რუსთავ','ზუგდიდ','ფოთ',
                'ახალციხ','ამბროლაურ','ოზურგეთ','სიღნაღ','თელავ','ლანჩხუთ','ოჩამჩირ','სოხუმ'}
_PROMO_WORDS = ['თიბისი','ვიზა','ბარათ','ფასდაკლება','concept','კონცეპტ','Visa','TBC','Signature']
_DESC_WORKER = Path(__file__).parent.parent / 'scrapers' / '_desc_worker.py'


# ═══════════════════════════════════════════════════════════════
# CORE HELPERS
# ═══════════════════════════════════════════════════════════════

def _is_tbilisi(venue):
    return not any(kw in venue.lower() for kw in _NON_TBILISI)

def _parse_date(date_str):
    if ' - ' in date_str: return None
    parts = date_str.strip().split()
    if len(parts) < 2: return None
    try:
        day = int(parts[0]); month = _MONTHS_SHORT.get(parts[1][:3])
        if not month: return None
        year = datetime.now().year
        d = datetime(year, month, day).date()
        if d < datetime.now().date() - timedelta(days=1):
            d = datetime(year+1, month, day).date()
        return d
    except (ValueError, KeyError): return None

def _speakable_date(date_str):
    date_str = date_str.split(' - ')[0].strip()
    parts = date_str.split()
    if len(parts) < 2: return date_str
    try:
        day = int(parts[0]); month_num = _MONTHS_SHORT.get(parts[1][:3])
        if not month_num: return date_str
        return f"{_DAY_ORDINAL.get(day, str(day))} {_MONTH_GEN[month_num]}"
    except (ValueError, KeyError): return date_str

def _speakable_time(time_str):
    if not time_str or time_str == 'N/A': return ''
    try:
        h, m = map(int, time_str.split(':'))
        base = _HOUR_SPOKEN.get(h, f'{h} საათზე')
        return base if m == 0 else base + f' და {m} წუთი'
    except ValueError: return time_str

def _time_to_georgian(time_str: str) -> str:
    """'16:49' → 'ოთხ საათსა და ორმოცდაცხრა წუთზე'"""
    if not time_str or ':' not in time_str: return time_str
    try:
        h, m = map(int, time_str.split(':'))
        base = _HOUR_SPOKEN.get(h, f'{h} საათზე')
        if m == 0: return base
        return base.replace('ზე','სა') + f' და {_speakable_time(f"0:{m:02d}").replace("შუადღეს","").strip()}'
    except Exception: return time_str

def _clean_stop(name):
    name = re.sub(r'\s*\[\d+\]', '', name).strip()
    name = re.sub(r'^მ/ს\s*["\']?', '', name).strip()
    return name.strip('"\'')

def _expand_venue(v: str) -> str:
    if not v: return v
    v = re.sub(r'\bნ\.\s*', 'ნოდარ ', v)
    v = re.sub(r'\bა\.\s*', 'ავთანდილ ', v)
    v = re.sub(r'\bსახ\.\s*', 'სახელობის ', v)
    v = re.sub(r'\bსახ\b', 'სახელობის', v)
    v = re.sub(r'\bმ/ს\s*["\']?', 'მეტრო სადგური ', v)
    v = re.sub(r'#(\d+)', r'\1', v)
    return v.strip(' "\'')

def _expand_all(text: str) -> str:
    """Expand abbreviations in any text for TTS."""
    if not text: return text
    text = re.sub(r'\bნ\.\s*', 'ნოდარ ', text)
    text = re.sub(r'\bსახ\.\s*', 'სახელობის ', text)
    text = re.sub(r'\bმ/ს\s*["\']?', 'მეტრო სადგური ', text)
    text = re.sub(r'#(\d+)', r'\1', text)
    text = re.sub(r'(\d+[,.]?\d*)\s*კმ\b', lambda m: f'{m.group(1)} კილომეტრი', text)
    text = re.sub(r'(\d+)\s*მ\b(?!\w)', lambda m: f'{m.group(1)} მეტრი', text)
    text = re.sub(r'(\d+)\s*წთ\b', lambda m: f'{m.group(1)} წუთი', text)
    text = re.sub(r'(\d+)\s*სთ\b', lambda m: f'{m.group(1)} საათი', text)
    text = re.sub(r'\b(\d{1,2}):(\d{2})\b',
                  lambda m: _speakable_time(m.group(0)), text)
    return text

def _strip_promo(text):
    if not text: return ''
    sentences = re.split(r'(?<=[.!?])\s+', text)
    clean = [s for s in sentences
             if not any(w.lower() in s.lower() for w in _PROMO_WORDS)]
    return ' '.join(clean).strip()

def _next_deps(schedule, count=3):
    now = datetime.now(); h_now, m_now = now.hour, now.minute
    upcoming = []
    for entry in schedule:
        h = entry['hour']
        for m_str in entry['departures']:
            try: m = int(m_str)
            except ValueError: continue
            if h > h_now or (h == h_now and m > m_now):
                upcoming.append((h, m))
            if len(upcoming) >= count: return upcoming
    return upcoming

def _list_with_and(names: list) -> str:
    if not names: return ''
    if len(names) == 1: return names[0]
    if len(names) == 2: return f'{names[0]} და {names[1]}'
    return ', '.join(names[:-1]) + f' და {names[-1]}'

def _unique_names(concerts):
    seen = set(); names = []
    for c in concerts:
        n = (c.get('name') or '').strip()
        if n and n not in seen: seen.add(n); names.append(n)
    return names


# ═══════════════════════════════════════════════════════════════
# GEMINI — central LLM response generator
# ═══════════════════════════════════════════════════════════════

_SYSTEM_BASE = """შენ ხარ „თბილისის ასისტენტი" — ქართულენოვანი ხმოვანი ასისტენტი.

წესები (ყველა პასუხისთვის):
- ოფიციალური სასაუბრო ქართული — ისე, როგორც ადამიანი ელაპარაკება ადამიანს
- არასდროს შეამოკლო: ნ. = ნოდარ, სახ. = სახელობის, მ/ს = მეტრო სადგური, კმ = კილომეტრი, წთ = წუთი, სთ = საათი
- დრო ყოველთვის სიტყვებით: 19:00 = „საღამოს შვიდ საათზე", 11:05 = „დილის თერთმეტ საათსა და ხუთ წუთზე"
- არ ახსენო ბანკი, ბარათი, ფასდაკლება, TBC, Visa, კონცეპტი
- კომპაქტური — 2-5 წინადადება, არ გაიმეორო ერთი და იგივე
- დაუსრულებელი წინადადება დაუშვებელია"""


def _gemini(prompt: str, max_tokens: int = 2000) -> str | None:
    try:
        from google import genai
        from google.genai import types
        api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
        if not api_key: return None
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=types.Content(role='user', parts=[types.Part(text=prompt)]),
            config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=8192),
        )
        raw = None
        if response.text:
            raw = response.text.strip()
        elif response.candidates:
            for cand in response.candidates:
                if cand.content and cand.content.parts:
                    raw = ''.join(p.text for p in cand.content.parts if p.text).strip()
                    break
        if not raw: return None
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        return _strip_promo(raw) if raw else None
    except Exception as e:
        log.warning('Gemini failed: %s', e)
        return None


def _gemini_respond(intent_type: str, data: str, user_query: str = '',
                    max_tokens: int = 2000) -> str | None:
    """
    Central LLM response generator.
    intent_type: human description of what user asked
    data: structured data as plain text (Georgian)
    user_query: original user query for context
    """
    query_line = f'მომხმარებლის კითხვა: „{user_query}"\n\n' if user_query else ''
    prompt = f"""{_SYSTEM_BASE}

{query_line}მონაცემები:
{data}

დავალება: შეადგინე ბუნებრივი ქართული პასუხი ხმოვანი ასისტენტისთვის ({intent_type}).
- პასუხი უნდა ჟღერდეს ადამიანურად, ბუნებრივად
- ყველა დრო სიტყვებით, ყველა შემოკლება გაშლილად
- 2-4 წინადადება"""
    return _gemini(prompt, max_tokens)


# ═══════════════════════════════════════════════════════════════
# DATA SERIALISERS — convert raw data to plain Georgian text
# for passing to Gemini
# ═══════════════════════════════════════════════════════════════

def _serialize_concerts(concerts: list) -> str:
    lines = []
    seen = set()
    for c in concerts:
        name = c.get('name','')
        if name in seen: continue
        seen.add(name)
        venue = _expand_venue(c.get('venue',''))
        d = _speakable_date(c.get('date',''))
        t = _speakable_time(c.get('time','N/A'))
        price = c.get('price','')
        entry = f'• {name} — {venue}'
        if d: entry += f', {d}'
        if t: entry += f', {t}'
        if price and price not in ('N/A','გაყიდულია'): entry += f', {price}'
        lines.append(entry)
    return '\n'.join(lines)

def _serialize_route(directions: dict) -> str:
    steps = directions.get('steps', [])
    total = _expand_all(directions.get('total_duration',''))
    lines = []
    if total: lines.append(f'სულ დრო: {total}')
    for s in steps:
        if s['type'] == 'walking':
            dist = _expand_all(s.get('distance',''))
            dur  = _expand_all(s.get('duration',''))
            if not dist: continue
            try:
                raw = float(re.sub(r'[^\d.]', '', dist.split()[0].replace(',','.')))
                metres = raw * 1000 if 'კილომეტრი' in dist else raw
                if metres < 60: continue
            except: pass
            lines.append(f'ფეხით: {dist}, {dur}')
        elif s['type'] == 'transit':
            line   = s.get('line_name','')
            dep_t  = _speakable_time(s.get('departure_time',''))
            dep_s  = _expand_venue(s.get('depart_stop',''))
            arr_s  = _expand_venue(s.get('arrive_stop',''))
            arr_t  = _speakable_time(s.get('arrival_time',''))
            n      = s.get('num_stops',0)
            entry  = f'ავტობუსი №{line}: '
            if dep_t: entry += f'{dep_t}, '
            if dep_s: entry += f'{dep_s}-დან, '
            if n:     entry += f'{n} გაჩერება, '
            if arr_s: entry += f'ჩამოდი {arr_s}-ზე'
            if arr_t: entry += f' {arr_t}'
            lines.append(entry.strip(', '))
    return '\n'.join(lines)

def _serialize_stops(stops: list, route: str = '') -> str:
    lines = []
    for s in stops[:6]:
        name = _expand_venue(_clean_stop(s.get('name') or s.get('stop_name') or ''))
        r    = s.get('route_number', route)
        t    = s.get('departure_time','')
        wm   = s.get('walk_minutes') or (round(s['distance_m']/80) if s.get('distance_m') else None)
        dep_spoken = _speakable_time(t) if t else ''
        walk = f'{wm} წუთის სიარული' if wm else ''
        entry = f'• {r}-ე მარშრუტი' if r else '•'
        if dep_spoken: entry += f': {dep_spoken}'
        if name and name != r: entry += f', გაჩერება: {name}'
        if walk: entry += f' ({walk})'
        lines.append(entry)
    return '\n'.join(lines)

def _serialize_stop_names(stops: list) -> str:
    """For 'nearest stops' (names + walking time only)."""
    seen = {}
    for s in stops:
        name = _expand_venue(_clean_stop(s.get('name') or s.get('stop_name') or s.get('depart_stop') or ''))
        dist = s.get('distance_m') or 9999
        if name and name not in seen: seen[name] = dist
    lines = []
    for name, dist in sorted(seen.items(), key=lambda x: x[1])[:5]:
        wm = round(dist / 80) if dist < 9999 else None
        entry = f'• {name}'
        if wm: entry += f' — სიარულით {wm} წუთი'
        lines.append(entry)
    return '\n'.join(lines)

def _serialize_event_dates(events: list) -> str:
    date_times = []
    seen = set()
    for e in events:
        d = e.get('date',''); t = e.get('time','N/A')
        key = (d, t)
        if key not in seen and d:
            seen.add(key)
            parsed = _parse_date(d)
            date_times.append((parsed or date(9999,1,1), d, t))
    date_times.sort(key=lambda x: x[0])
    lines = []
    for _, d_str, t_str in date_times:
        entry = _speakable_date(d_str)
        ts = _speakable_time(t_str)
        if ts: entry += f', {ts}'
        lines.append(f'• {entry}')
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════
# DESCRIPTION FETCHER
# ═══════════════════════════════════════════════════════════════

def _fetch_description(event: dict) -> dict:
    url = event.get('url', '')
    if not url or url == 'N/A': return {'description':'','credits':''}
    if not _DESC_WORKER.exists(): return {'description':'','credits':''}
    try:
        proc = subprocess.run([sys.executable, str(_DESC_WORKER), url],
                              capture_output=True, timeout=25)
        if proc.returncode != 0: return {'description':'','credits':''}
        stdout = proc.stdout.strip()
        if not stdout: return {'description':'','credits':''}
        return json.loads(stdout.decode('utf-8'))
    except Exception as e:
        log.warning('_desc_worker error: %s', e)
        return {'description':'','credits':''}


# ═══════════════════════════════════════════════════════════════
# RESPONSE GENERATORS — each uses Gemini with fallback
# ═══════════════════════════════════════════════════════════════

def _format_concert_list(concerts, category=None, user_query=''):
    cat_label = _CATEGORY_LABEL.get(category,'ღონისძიება') if category else 'ღონისძიება'
    names = _unique_names(concerts)
    if not names:
        t = f'ახლო დღეებში {cat_label} ვერ მოიძებნა.'
        return t, t

    # Build numbered list for display
    numbered = '\n'.join(f'{i+1}. {n}' for i,n in enumerate(names))
    display = f'ვიპოვე {len(names)} {cat_label}:\n{numbered}\n\nგაინტერესებთ რომელიმე? შემიძლია გითხრათ სად და როდის ტარდება.'

    # TTS via Gemini
    data = f'ნაპოვნი {cat_label}ები ({len(names)} სულ):\n{_serialize_concerts(concerts[:15])}'
    tts = _gemini_respond(
        f'მომხმარებელს ვაცნობებ ნაპოვნ {cat_label}ებს, ჩამოვთვლი სახელებს და დავამთავრებ კითხვით',
        data, user_query
    )
    if not tts:
        # Fallback: natural list
        tts = (f'ვიპოვე {len(names)} {cat_label}: '
               + _list_with_and(names[:10])
               + '. გაინტერესებთ რომელიმე? შემიძლია გითხრათ სად და როდის ტარდება.')
    return display, tts


def _format_event_venue(events: list, event_name: str,
                         context_date: str = '', user_query: str = '') -> tuple[str,str]:
    """'სად ტარდება X' — just the venue."""
    if not events:
        t = f'"{event_name}"-ის შესახებ ინფორმაცია ვერ მოიძებნა.'
        return t, t
    first = events[0]
    name  = first.get('name', event_name)
    venue = _expand_venue(first.get('venue','N/A'))
    if venue in ('N/A',''):
        t = f'"{name}"-ის ადგილმდებარეობა ვერ მოიძებნა.'
        return t, t
    data = f'სპექტაკლი/ღონისძიება: {name}\nადგილი: {venue}'
    if context_date:
        data += f'\nმომხმარებელმა ითხოვა: {context_date}-ს'
    result = _gemini_respond('მომხმარებელს ვეუბნები სად ტარდება ეს ღონისძიება', data, user_query)
    if result: return result, result
    t = f'"{name}" {venue}-ში ტარდება.'
    return t, t


def _format_event_dates(events: list, event_name: str, user_query: str = '') -> tuple[str,str]:
    """'როდის ტარდება X' — all dates."""
    if not events:
        t = f'"{event_name}"-ის სეანსები ვერ მოიძებნა.'
        return t, t
    first = events[0]
    name  = first.get('name', event_name)
    venue = _expand_venue(first.get('venue','N/A'))
    dates_text = _serialize_event_dates(events)
    if not dates_text:
        t = f'"{name}"-ის სეანსების ინფორმაცია ვერ მოიძებნა.'
        return t, t
    data = f'სპექტაკლი/ღონისძიება: {name}\nადგილი: {venue}\nსეანსები:\n{dates_text}'
    result = _gemini_respond(
        'მომხმარებელს ვეუბნები ყველა სეანსის თარიღს და დროს',
        data, user_query
    )
    if result: return result, result
    # Fallback
    date_list = [ln.lstrip('• ') for ln in dates_text.splitlines()]
    t = f'"{name}" {venue}-ში ტარდება: ' + _list_with_and(date_list) + '.'
    return t, t


def _format_event_detail(events: list, event_name: str,
                          dates_only: bool = False, venue_only: bool = False,
                          context_date: str = '', user_query: str = '') -> tuple[str,str]:
    """Full event detail with description."""
    if venue_only:
        return _format_event_venue(events, event_name, context_date, user_query)
    if dates_only:
        return _format_event_dates(events, event_name, user_query)

    if not events:
        t = f'"{event_name}"-ის შესახებ ინფორმაცია ვერ მოიძებნა.'
        return t, t

    first = events[0]
    name  = first.get('name', event_name)
    venue = _expand_venue(first.get('venue','N/A'))
    price = first.get('price','N/A')

    # Collect dates
    date_times = []
    seen_dt = set()
    for e in events:
        d = e.get('date',''); t_s = e.get('time','N/A')
        key = (d, t_s)
        if key not in seen_dt and d:
            seen_dt.add(key)
            parsed = _parse_date(d)
            date_times.append((parsed or date(9999,1,1), d, t_s))
    date_times.sort(key=lambda x: x[0])
    date_lines = []
    for _, d_str, t_str in date_times[:4]:
        entry = _speakable_date(d_str)
        ts = _speakable_time(t_str)
        if ts: entry += f', {ts}'
        date_lines.append(entry)

    price_str = ''
    if price not in ('N/A','','გაყიდულია','უფასო'):
        price_str = f'ბილეთი: {price}'
    elif price == 'უფასო':
        price_str = 'შესვლა უფასოა'

    desc_data   = _fetch_description(first)
    description = _strip_promo(desc_data.get('description',''))
    credits     = desc_data.get('credits','')

    credits_note = ''
    if credits:
        pm = re.search(r'მონაწილეობენ[\s:]+([^\n]+)', credits)
        dm = re.search(r'რეჟისორი[\s:]+([^\n]+)', credits)
        if pm:   credits_note = f'მსახიობები: {pm.group(1).strip()[:100]}'
        elif dm: credits_note = f'რეჟისორი: {dm.group(1).strip()[:60]}'

    data = f'''სახელი: {name}
ადგილი: {venue}
სეანსები: {"; ".join(date_lines) if date_lines else "უცნობია"}
{price_str}
{credits_note}
{"აღწერა: " + description[:300] if description else ""}'''

    result = _gemini_respond(
        'მომხმარებელს ვაძლევ სრულ ინფორმაციას ღონისძიებაზე — სად, როდის, რაზეა, ვინ მონაწილეობს',
        data, user_query
    )
    if result: return result, result

    # Fallback
    parts = [f'"{name}" {venue}-ში.']
    if date_lines: parts.append(f'სეანსები: {"; ".join(date_lines)}.')
    if price_str: parts.append(price_str + '.')
    if description: parts.append(_strip_promo(description[:200]))
    t = ' '.join(parts)
    return t, t


def _format_route(directions: dict, dest_label: str = '', user_query: str = '') -> tuple[str,str]:
    steps = directions.get('steps', [])
    total = _expand_all(directions.get('total_duration',''))
    has_transit = any(s.get('type') == 'transit' for s in steps)

    if not has_transit:
        walk = next((s for s in steps if s.get('type') == 'walking'), None)
        dist = _expand_all(walk.get('distance','') if walk else '')
        dur  = _expand_all(walk.get('duration','') if walk else total)
        dest = f'{dest_label}მდე ' if dest_label else ''
        t = (f'{dest}ფეხით სიარული გჭირდებათ. '
             f'მანძილია {dist} და გზა დაახლოებით {dur} გაგრძელდება.')
        return t, t

    data = _serialize_route(directions)
    if dest_label:
        data = f'დანიშნულება: {dest_label}\n' + data

    result = _gemini_respond(
        'მომხმარებელს ვეუბნები სრულ მარშრუტს — ყველა გადაჯდომა, გაჩერება, საათი, ფეხით სიარული',
        data, user_query
    )
    if result: return result, result

    # Fallback: manual
    parts = []
    for i, s in enumerate(steps):
        if s['type'] == 'walking':
            dist = _expand_all(s.get('distance',''))
            dur  = _expand_all(s.get('duration',''))
            if not dist: continue
            try:
                raw = float(re.sub(r'[^\d.]','',dist.split()[0].replace(',','.')))
                m = raw*1000 if 'კილომეტრი' in dist else raw
                if m < 60: continue
            except: pass
            parts.append(f'{"ჯერ " if i==0 else "შემდეგ "}ფეხით {dist}, {dur}')
        elif s['type'] == 'transit':
            line  = s.get('line_name','')
            dep_t = _speakable_time(s.get('departure_time',''))
            dep_s = _expand_venue(s.get('depart_stop',''))
            arr_s = _expand_venue(s.get('arrive_stop',''))
            arr_t = _speakable_time(s.get('arrival_time',''))
            n     = s.get('num_stops',0)
            p = f'ჩაჯექით {line}-ე ავტობუსში'
            if dep_t: p += f' {dep_t}'
            if dep_s: p += f', {dep_s}-დან'
            if n:     p += f'. {n} გაჩერება'
            if arr_s: p += f', ჩამოდით {arr_s}-ზე'
            if arr_t: p += f' {arr_t}'
            parts.append(p)
    dest_p = f'{dest_label}ში მისასვლელად: ' if dest_label else ''
    text = dest_p + '. შემდეგ '.join(parts) + '.'
    if total: text += f' სულ: {total}.'
    return text, text


def _format_bus_at_nearest(route_number: str, stops: list,
                            gps_stops: list | None = None,
                            user_query: str = '') -> tuple[str,str]:
    if not stops and not gps_stops:
        t = (f'{route_number}-ე მარშრუტის ინფორმაცია ვერ მოიძებნა. '
             f'ხელმისაწვდომია: 299, 300, 301, 302, 305, 307, 312, 314, 315, 320.')
        return t, t

    # Prefer GPS-based nearest stop for this route
    if gps_stops:
        route_gps = [s for s in gps_stops
                     if str(s.get('route_number','')) == str(route_number)]
        if route_gps:
            s = route_gps[0]
            stop_name = _expand_venue(_clean_stop(s.get('name') or s.get('stop_name') or ''))
            wm = s.get('walk_minutes') or (round(s['distance_m']/80) if s.get('distance_m') else None)
            dep_t = s.get('departure_time','')
            data = f'{route_number}-ე ავტობუსი\nახლო გაჩერება: {stop_name}\n'
            if dep_t: data += f'მოსვლის დრო: {_speakable_time(dep_t)}\n'
            if wm: data += f'სიარული: {wm} წუთი'
            result = _gemini_respond(
                'მომხმარებელს ვეუბნები რამდენ ხანში მოვა კონკრეტული ავტობუსი ახლო გაჩერებაზე',
                data, user_query
            )
            if result: return result, result

    # TTC CSV fallback
    stop = stops[0]
    name = _expand_venue(_clean_stop(stop['name']))
    deps = _next_deps(stop['schedule'], count=3)
    if deps:
        times = ' და '.join(
            f'{_speakable_time(f"{h:02d}:{m:02d}")} ({(h*60+m)-(datetime.now().hour*60+datetime.now().minute)} წუთში)'
            for h,m in deps[:2]
        )
        data = f'{route_number}-ე ავტობუსი\nგაჩერება: {name}\nმოსვლა: {times}'
    else:
        data = f'{route_number}-ე ავტობუსი — {name} — დღის ბოლო რეისი გავიდა'

    result = _gemini_respond(
        'მომხმარებელს ვეუბნები რამდენ ხანში მოვა ავტობუსი',
        data, user_query
    )
    if result: return result, result
    t = f'{route_number}-ე ავტობუსი "{name}"-ზე: {times if deps else "დღის ბოლო რეისი გავიდა"}.'
    return t, t


def _format_bus(route_number, stops, user_query='') -> tuple[str,str]:
    if not stops:
        t = (f'{route_number}-ე მარშრუტის ინფორმაცია ვერ მოიძებნა.')
        return t, t
    data_lines = []
    for stop in stops[:3]:
        name = _expand_venue(_clean_stop(stop['name']))
        deps = _next_deps(stop['schedule'], count=3)
        if deps:
            times = ', '.join(
                f'{_speakable_time(f"{h:02d}:{m:02d}")} ({(h*60+m)-(datetime.now().hour*60+datetime.now().minute)} წუთში)'
                for h,m in deps
            )
            data_lines.append(f'გაჩერება {name}: {times}')
        else:
            data_lines.append(f'{name}: დღის ბოლო რეისი')
    data = f'{route_number}-ე მარშრუტი\n' + '\n'.join(data_lines)
    result = _gemini_respond(
        'მომხმარებელს ვეუბნები ავტობუსის განრიგს',
        data, user_query
    )
    if result: return result, result
    t = f'{route_number}-ე მარშრუტი. ' + '. '.join(data_lines) + '.'
    return t, t


def _format_nearest(stops: list, user_query='') -> tuple[str,str]:
    if not stops:
        t = 'ახლომდებარე ავტობუსი ვერ მოიძებნა.'
        return t, t
    data = _serialize_stops(stops)
    result = _gemini_respond(
        'მომხმარებელს ვეუბნები ახლო ავტობუსებს — რომელი, როდის, რამდენ ხანში',
        data, user_query
    )
    if result: return result, result
    # Fallback
    parts = []
    for s in stops[:4]:
        r = s.get('route_number','')
        t_s = _speakable_time(s.get('departure_time',''))
        wm = s.get('walk_minutes') or (round(s['distance_m']/80) if s.get('distance_m') else None)
        w = f', {wm} წუთის სიარული' if wm else ''
        if r and t_s: parts.append(f'{r}-ე: {t_s}{w}')
        elif r: parts.append(f'{r}-ე{w}')
    t = f'ახლოს {len(stops)} ავტობუსი. ' + '. '.join(parts) + '.'
    return t, t


def _format_nearest_stops(stops: list, user_query='') -> tuple[str,str]:
    if not stops:
        t = 'ახლომდებარე გაჩერება ვერ მოიძებნა.'
        return t, t
    data = _serialize_stop_names(stops)
    result = _gemini_respond(
        'მომხმარებელს ვეუბნები ახლომდებარე გაჩერებების სახელებს და სიარულის დროს',
        data, user_query
    )
    if result: return result, result
    t = f'ახლოს {len(stops)} გაჩერება. ' + data.replace('• ','').replace('\n','. ') + '.'
    return t, t


def _format_buses_at_place(place: str, results: list, user_query='') -> tuple[str,str]:
    if not results:
        t = f'"{place}"-სთან გამავალი ავტობუსის ინფორმაცია ვერ მოიძებნა.'
        return t, t
    routes = sorted({r['route_number'] for r in results})
    data = f'ადგილი: {place}\nმარშრუტები: {", ".join(routes)}'
    result = _gemini_respond(
        'მომხმარებელს ვეუბნები რომელი ავტობუსები გადის ამ ადგილთან',
        data, user_query
    )
    if result: return result, result
    t = f'"{place}"-სთან გაივლის: {", ".join(f"{r}-ე" for r in routes)} მარშრუტი.'
    return t, t


def _format_home_route(results, home_address='', directions=None, user_query='') -> tuple[str,str]:
    if directions and directions.get('steps'):
        data = f'სახლი: {home_address}\n' + _serialize_route(directions)
        result = _gemini_respond(
            'მომხმარებელს ვეუბნები სრულ მარშრუტს სახლამდე — ყველა გაჩერება, გადაჯდომა, დრო',
            data, user_query
        )
        if result: return result, result
        text, _ = _format_route(directions, 'სახლი', user_query)
        return text, text

    if not results:
        t = 'სახლთან ახლოს ავტობუსი ვერ მოიძებნა.'
        return t, t

    data_lines = []
    for r in results[:3]:
        rn = r.get('route_number','')
        deps = _next_deps(r.get('schedule',[]), count=2)
        if deps:
            times = ', '.join(_speakable_time(f'{h:02d}:{m:02d}') for h,m in deps)
            data_lines.append(f'{rn}-ე: {times}')
        else:
            data_lines.append(f'{rn}-ე: ბოლო რეისი')

    data = f'სახლი: {home_address or "შენახული მისამართი"}\nავტობუსები:\n' + '\n'.join(data_lines)
    result = _gemini_respond(
        'მომხმარებელს ვეუბნები სახლისკენ მიმავალ ავტობუსებს',
        data, user_query
    )
    if result: return result, result
    t = 'სახლში მიმავალი ავტობუსები: ' + '. '.join(data_lines) + '.'
    return t, t


def _format_unknown():
    t = ('ვერ გავიგე. შემიძლია გითხრა კონცერტებზე, სპექტაკლებზე, ოპერაზე, '
         'ან გითხრა როგორ მიხვიდე სასურველ მისამართზე.')
    return t, t


# ═══════════════════════════════════════════════════════════════
# BUILD_RESPONSE — main entry point
# ═══════════════════════════════════════════════════════════════

def build_response(intent: IntentResult, results, venue_bus_offer=None,
                   home_address='', event_detail=None, directions=None,
                   extra_context: dict | None = None) -> dict:
    display, tts = '', ''
    ctx = extra_context or {}
    uq  = ctx.get('original_text', '')

    if intent.intent == 'bus_search':
        if ctx.get('buses_at_place'):
            display, tts = _format_buses_at_place(
                intent.place or intent.venue or '', results, uq)
        elif ctx.get('nearest_for_route'):
            display, tts = _format_bus_at_nearest(
                intent.route or '?', results,
                gps_stops=ctx.get('gps_stops'), user_query=uq)
        else:
            display, tts = _format_bus(intent.route or '?', results, uq)

    elif intent.intent == 'concert_search':
        if results:
            category = results[0].get('category') if results else None
            filtered = [c for c in results
                        if c.get('price') != 'გაყიდულია' and _is_tbilisi(c.get('venue',''))]
            display, tts = _format_concert_list(filtered, category, uq)
        else:
            cat_label = _CATEGORY_LABEL.get(intent.category,'ღონისძიება') if intent.category else 'ღონისძიება'
            venue_note = f' {intent.venue}-ში' if intent.venue else ''
            date_note  = f' {intent.specific_date}-ს' if intent.specific_date else ''
            t = f'ახლო დღეებში{venue_note}{date_note} {cat_label} ვერ მოიძებნა.'
            display, tts = t, t

    elif intent.intent == 'journey_search':
        if directions and directions.get('steps'):
            display, tts = _format_route(directions, intent.place or '', uq)
        elif results:
            routes = list({r['route_number'] for r in results})
            place = intent.place or 'ადგილი'
            data = f'ადგილი: {place}\nმარშრუტები: {", ".join(routes[:5])}'
            result = _gemini_respond('მომხმარებელს ვეუბნები რომელი ავტობუსები მიდის ამ ადგილამდე', data, uq)
            t = result or f'{place}-სთან მიმავალი: {", ".join(routes[:5])}.'
            display, tts = t, t
        else:
            t = 'ამ ადგილთან მიმავალი ავტობუსი ვერ მოიძებნა.'
            display, tts = t, t

    elif intent.intent == 'home_route':
        display, tts = _format_home_route(results, home_address, directions, uq)

    elif intent.intent == 'event_detail':
        evs = (event_detail if isinstance(event_detail, list)
               else ([event_detail] if event_detail else []))
        orig = uq.lower()
        venue_only = ctx.get('venue_only', False) or any(
            kw in orig for kw in ['სად ტარდება','სად იმართება','სად არის','სად გაიმართება'])
        dates_only = ctx.get('dates_only', False) or (not venue_only and any(
            kw in orig for kw in ['რა დღეებ','რომელ დღეებ','სეანს','კვირ','განმავლობ',
                                   'გრაფიკ','განრიგ','როდის ტარდება','როდის არის',
                                   'როდის გაიმართება','როდის იქნება']))
        display, tts = _format_event_detail(
            evs, intent.event_name or '',
            dates_only=dates_only, venue_only=venue_only,
            context_date=ctx.get('context_date',''), user_query=uq,
        )

    elif intent.intent == 'nearest_stop':
        if ctx.get('stops_only'):
            display, tts = _format_nearest_stops(results or [], uq)
        else:
            display, tts = _format_nearest(results or [], uq)

    else:
        display, tts = _format_unknown()

    display = _strip_promo(display or '')
    tts     = _strip_promo(tts or '')
    return {'response_text': display, 'tts_text': tts}