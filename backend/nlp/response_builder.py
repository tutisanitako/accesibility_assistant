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
# Stem forms for locative: nominative → locative stem (drop terminal ი → empty, ა → ა, etc.)
# Hours — stem form used in "X საათსა და Y წუთზე"
_HOUR_STEM = {
    0:'შუაღამ',1:'ერთ',2:'ორ',3:'სამ',4:'ოთხ',5:'ხუთ',6:'ექვს',
    7:'შვიდ',8:'რვა',9:'ცხრა',10:'ათ',11:'თერთმეტ',12:'თორმეტ',
    13:'ერთ',14:'ორ',15:'სამ',16:'ოთხ',17:'ხუთ',18:'ექვს',
    19:'შვიდ',20:'რვა',21:'ცხრა',22:'ათ',23:'თერთმეტ',
}
_MIN_STEM = {
    1:'ერთ',2:'ორ',3:'სამ',4:'ოთხ',5:'ხუთ',6:'ექვს',7:'შვიდ',
    8:'რვა',9:'ცხრა',10:'ათ',11:'თერთმეტ',12:'თორმეტ',13:'ცამეტ',
    14:'თოთხმეტ',15:'თხუთმეტ',16:'თექვსმეტ',17:'ჩვიდმეტ',18:'თვრამეტ',
    19:'ცხრამეტ',20:'ოც',21:'ოცდაერთ',22:'ოცდაორ',23:'ოცდასამ',
    24:'ოცდაოთხ',25:'ოცდახუთ',26:'ოცდაექვს',27:'ოცდაშვიდ',
    28:'ოცდარვა',29:'ოცდაცხრა',30:'ოცდაათ',31:'ოცდათერთმეტ',
    32:'ოცდათორმეტ',33:'ოცდაცამეტ',34:'ოცდათოთხმეტ',35:'ოცდათხუთმეტ',
    36:'ოცდათექვსმეტ',37:'ოცდაჩვიდმეტ',38:'ოცდათვრამეტ',39:'ოცდაცხრამეტ',
    40:'ორმოც',41:'ორმოცდაერთ',42:'ორმოცდაორ',43:'ორმოცდასამ',
    44:'ორმოცდაოთხ',45:'ორმოცდახუთ',46:'ორმოცდაექვს',47:'ორმოცდაშვიდ',
    48:'ორმოცდარვა',49:'ორმოცდაცხრა',50:'ორმოცდაათ',51:'ორმოცდათერთმეტ',
    52:'ორმოცდათორმეტ',53:'ორმოცდაცამეტ',54:'ორმოცდათოთხმეტ',
    55:'ორმოცდათხუთმეტ',56:'ორმოცდათექვსმეტ',57:'ორმოცდაჩვიდმეტ',
    58:'ორმოცდათვრამეტ',59:'ორმოცდაცხრამეტ',
}
_HOUR_PREFIX = {
    (0,):   'შუაღამ',
    (1,2,3,4): 'ღამის',
    (5,6,7,8,9,10,11): 'დილის',
    (12,):  'შუადღ',
    (13,14,15,16,17): '',
    (18,19,20,21,22,23): 'საღამოს',
}

_NON_TBILISI = {'სენაკ','ბათუმ','ქუთაის','გორ','რუსთავ','ზუგდიდ','ფოთ',
                'ახალციხ','ამბროლაურ','ოზურგეთ','სიღნაღ','თელავ','ლანჩხუთ','ოჩამჩირ','სოხუმ'}
_PROMO_WORDS = ['თიბისი','ვიზა','ბარათ','ფასდაკლება','concept','კონცეპტ','Visa','TBC','Signature']
_AGE_RESTRICT_RE = re.compile(
    r'ბილეთი\s+ესაჭიროება[^.]+\.'
    r'|\d+\s+წლ[იდ]\w*\s+მაყურებელს[^.]*\.'
    r'|ასაკობრივი\s+შეზღუდ[^.]*\.',
    re.IGNORECASE
)
_DESC_WORKER = Path(__file__).parent.parent / 'scrapers' / '_desc_worker.py'


# ── Time helpers ──────────────────────────────────────────────────────────────

def _get_prefix(h: int) -> str:
    for hs, p in _HOUR_PREFIX.items():
        if h in hs: return p
    return ''

def _time_to_georgian(time_str: str) -> str:
    """
    '16:49' → 'ოთხ საათსა და ორმოცდაცხრა წუთზე'
    '14:00' → 'ორ საათზე'
    Uses stem (locative) forms throughout.
    """
    if not time_str or ':' not in time_str: return time_str
    try:
        h, m = map(int, time_str.split(':'))
        prefix = _get_prefix(h)
        # 13-23 display as 1-11
        hd = h if h <= 12 else h - 12
        h_stem = _HOUR_STEM.get(hd, str(hd))
        if h in (0, 12):
            hour_part = 'შუაღამეს' if h == 0 else 'შუადღეს'
            if m == 0: return hour_part
            m_stem = _MIN_STEM.get(m, str(m))
            return f'{hour_part[:-1]}ს და {m_stem} წუთზე'
        hour_spoken = f'{prefix} {h_stem}'.strip() if prefix else h_stem
        if m == 0:
            return f'{hour_spoken} საათზე'
        m_stem = _MIN_STEM.get(m, str(m))
        return f'{hour_spoken} საათსა და {m_stem} წუთზე'
    except Exception:
        return time_str

def _speakable_time(time_str: str) -> str:
    return _time_to_georgian(time_str) if time_str and time_str != 'N/A' else ''

def _speakable_date(date_str: str) -> str:
    date_str = date_str.split(' - ')[0].strip()
    parts = date_str.split()
    if len(parts) < 2: return date_str
    try:
        day = int(parts[0]); month_num = _MONTHS_SHORT.get(parts[1][:3])
        if not month_num: return date_str
        return f'{_DAY_ORDINAL.get(day, str(day))} {_MONTH_GEN[month_num]}'
    except (ValueError, KeyError): return date_str


# ── Georgian noun case helpers ────────────────────────────────────────────────

def _geo_genitive(phrase: str) -> str:
    """
    Convert last word of phrase to genitive (-ის suffix).
    "131-ე საჯარო სკოლა" → "131-ე საჯარო სკოლის"
    "ნუგზარ საჯაიას ქუჩა" → "ნუგზარ საჯაიას ქუჩის"
    "თავისუფლების მოედანი" → "თავისუფლების მოედნის"  (approx)
    """
    if not phrase: return phrase
    words = phrase.split()
    last = words[-1]
    if re.search(r'[0-9]', last):
        # Numeric/mixed: append -ის
        words[-1] = last + 'ის' if not last.endswith('ის') else last
    elif last.endswith('ი'):
        words[-1] = last[:-1] + 'ის'
    elif last.endswith('ა'):
        words[-1] = last[:-1] + 'ის'
    elif last.endswith('ე') or last.endswith('ო'):
        words[-1] = last + 'ს'
    elif last.endswith('ის') or last.endswith('ს'):
        pass  # already genitive
    else:
        words[-1] = last + 'ის'
    return ' '.join(words)

def _geo_locative(phrase: str) -> str:
    """
    Convert phrase to locative (-ში constructions).
    "თავისუფალი თეატრი" → "თავისუფალ თეატრში"
    "რუსთაველის მეტრო" → "რუსთაველის მეტროში"
    "131-ე საჯარო სკოლა" → "131-ე საჯარო სკოლაში"
    """
    if not phrase: return phrase
    words = phrase.split()
    # Each adjective (pure Georgian, ending ი, not last word): drop ი
    for i in range(len(words) - 1):
        w = words[i]
        if (re.match(r'^[\u10D0-\u10FF]+$', w)
                and w.endswith('ი') and len(w) > 3):
            words[i] = w[:-1]
    # Last word
    last = words[-1]
    if last.endswith('ი'):
        words[-1] = last[:-1] + 'ში'
    elif last.endswith('ა') or last.endswith('ო') or last.endswith('ე') or last.endswith('უ'):
        words[-1] = last + 'ში'
    elif last.endswith('ში'):
        pass  # already locative
    else:
        words[-1] = last + 'ში'
    return ' '.join(words)


# ── Core helpers ──────────────────────────────────────────────────────────────

def _is_tbilisi(venue: str) -> bool:
    return not any(kw in venue.lower() for kw in _NON_TBILISI)

def _parse_date(date_str: str):
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

def _clean_stop(name: str) -> str:
    name = re.sub(r'\s*\[\d+\]', '', name).strip()
    name = re.sub(r'^მ/ს\s*["\']?', '', name).strip()
    return name.strip('"\'')

def _expand_stop(s: str) -> str:
    if not s: return s
    s = re.sub(r'\bნ\.\s*', 'ნოდარ ', s)
    s = re.sub(r'\bა\.\s*', 'ავთანდილ ', s)
    s = re.sub(r'\bსახ\.\s*', 'სახელობის ', s)
    s = re.sub(r'\bსახ\b', 'სახელობის', s)
    s = re.sub(r'\bმ/ს\s*["\']?', 'მეტრო სადგური ', s)
    s = re.sub(r'\bშ\.\s*', 'შესახვევი ', s)
    s = re.sub(r'#(\d+)', r'\1', s)
    return s.strip(' "\'')

def _stop_name(raw: str) -> str:
    """Clean + expand a stop name."""
    return _expand_stop(_clean_stop(raw))

def _strip_promo(text: str) -> str:
    if not text: return ''
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return ' '.join(s for s in sentences
                    if not any(w.lower() in s.lower() for w in _PROMO_WORDS)).strip()

def _strip_age_restriction(text: str) -> str:
    """Remove generic child-ticket sentences; keep 18+/16+ warnings."""
    if not text: return ''
    def _keep(sentence: str) -> bool:
        if _AGE_RESTRICT_RE.search(sentence):
            return bool(re.search(r'18\+?|16\+?|სრულწლოვ', sentence))
        return True
    parts = re.split(r'(?<=[.!?])\s+', text)
    return ' '.join(p for p in parts if _keep(p)).strip()

def _next_deps(schedule: list, count: int = 3) -> list:
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

def _dep_spoken(h: int, m: int) -> str:
    mins = (h*60+m) - (datetime.now().hour*60 + datetime.now().minute)
    t = _time_to_georgian(f'{h:02d}:{m:02d}')
    if mins <= 2:  return f'{t} (ახლავე)'
    if mins <= 10: return f'{t} ({mins} წუთში)'
    if mins <= 30: return f'{t} (~{mins} წუთში)'
    return t

def _expand_dur(d: str) -> str:
    if not d: return ''
    d = re.sub(r'(\d+)\s*წთ\b', r'\1 წუთი', d)
    d = re.sub(r'(\d+)\s*სთ\b', r'\1 საათი', d)
    return d

def _list_with_and(names: list) -> str:
    if not names: return ''
    if len(names) == 1: return names[0]
    if len(names) == 2: return f'{names[0]} და {names[1]}'
    return ', '.join(names[:-1]) + f' და {names[-1]}'

def _unique_names(concerts: list) -> list:
    seen = set(); names = []
    for c in concerts:
        n = (c.get('name') or '').strip()
        if n and n not in seen: seen.add(n); names.append(n)
    return names

def _walk_min(s: dict) -> int | None:
    wm = s.get('walk_minutes')
    if wm: return wm
    dm = s.get('distance_m')
    return round(dm / 80) if dm else None


# ── Gemini ────────────────────────────────────────────────────────────────────

def _gemini(prompt: str) -> str | None:
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
        if response.text: raw = response.text.strip()
        elif response.candidates:
            for cand in response.candidates:
                if cand.content and cand.content.parts:
                    raw = ''.join(p.text for p in cand.content.parts if p.text).strip(); break
        if not raw: return None
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        return _strip_promo(raw) if raw else None
    except Exception as e:
        log.warning('Gemini failed: %s', e); return None

def _fetch_description(event: dict) -> dict:
    url = event.get('url','')
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
        log.warning('_desc_worker error: %s', e); return {'description':'','credits':''}


# ── Concert list ──────────────────────────────────────────────────────────────

def _format_concert_list(concerts: list, category: str | None = None) -> tuple:
    cat_label = _CATEGORY_LABEL.get(category, 'ღონისძიება') if category else 'ღონისძიება'
    names = _unique_names(concerts)[:12]
    if not names:
        t = f'ახლო დღეებში {cat_label} ვერ მოიძებნა.'
        return t, t
    followup = 'გაინტერესებთ რომელიმე? შემიძლია გითხრათ სად და როდის ტარდება.'
    numbered = '\n'.join(f'{i+1}. {n}' for i, n in enumerate(names))
    display = f'ვიპოვე {len(names)} {cat_label}:\n{numbered}\n\n{followup}'
    # TTS: each name ends with period for pause
    tts = f'ვიპოვე {len(names)} {cat_label}. ' + '. '.join(names) + f'. {followup}'
    return display, tts


# ── Event detail ──────────────────────────────────────────────────────────────

def _format_event_venue(events: list, event_name: str) -> tuple:
    if not events:
        t = f'"{event_name}"-ის ადგილმდებარეობა ვერ მოიძებნა.'
        return t, t
    first = events[0]; name = first.get('name', event_name)
    venue = _expand_stop(first.get('venue',''))
    if not venue or venue == 'N/A':
        t = f'"{name}"-ის ადგილი ვერ მოიძებნა.'
        return t, t
    t = f'"{name}" {_geo_locative(venue)}-ში ტარდება.'
    return t, t

def _format_event_dates(events: list, event_name: str) -> tuple:
    if not events:
        t = f'"{event_name}"-ის სეანსები ვერ მოიძებნა.'
        return t, t
    first = events[0]; name = first.get('name', event_name)
    venue = _expand_stop(first.get('venue',''))

    date_times = []
    seen = set()
    for e in events:
        d = e.get('date',''); ts = e.get('time','N/A')
        if (d, ts) not in seen and d:
            seen.add((d, ts))
            parsed = _parse_date(d)
            date_times.append((parsed or date(9999,1,1), d, ts))
    date_times.sort(key=lambda x: x[0])

    if not date_times:
        t = f'"{name}"-ის სეანსების ინფორმაცია ვერ მოიძებნა.'
        return t, t

    lines = []; spoken = []
    for _, d_str, t_str in date_times:
        sd = _speakable_date(d_str); st = _speakable_time(t_str)
        entry = f'{sd}, {st}' if st else sd
        lines.append(entry); spoken.append(entry)

    numbered = '\n'.join(f'{i+1}. {l}' for i,l in enumerate(lines))
    venue_note = f' {_geo_locative(venue)}' if venue and venue != 'N/A' else ''
    display = f'"{name}"{venue_note} ტარდება:\n{numbered}'
    tts     = f'"{name}"{venue_note} ტარდება: ' + '. '.join(spoken) + '.'
    return display, tts

def _format_event_detail(events: list, event_name: str,
                          dates_only: bool = False, venue_only: bool = False,
                          context_date: str = '', user_query: str = '') -> tuple:
    if venue_only: return _format_event_venue(events, event_name)
    if dates_only: return _format_event_dates(events, event_name)

    if not events:
        t = f'"{event_name}"-ის შესახებ ინფორმაცია ვერ მოიძებნა.'
        return t, t

    first = events[0]; name = first.get('name', event_name)
    venue = _expand_stop(first.get('venue','')); price = first.get('price','')

    date_times = []
    seen = set()
    for e in events:
        d = e.get('date',''); ts = e.get('time','N/A')
        if (d, ts) not in seen and d:
            seen.add((d, ts)); parsed = _parse_date(d)
            date_times.append((parsed or date(9999,1,1), d, ts))
    date_times.sort(key=lambda x: x[0])
    date_lines = []
    for _, d_str, t_str in date_times[:4]:
        sd = _speakable_date(d_str); st = _speakable_time(t_str)
        date_lines.append(f'{sd}, {st}' if st else sd)

    price_str = ''
    if price not in ('N/A','','გაყიდულია','უფასო'): price_str = f'ბილეთი: {price}'
    elif price == 'უფასო': price_str = 'შესვლა უფასოა'
    venue_note = f'{_geo_locative(venue)}' if venue and venue != 'N/A' else ''
    dates_str  = '; '.join(date_lines) if date_lines else 'თარიღი უცნობია'

    desc_data   = _fetch_description(first)
    description = _strip_promo(desc_data.get('description',''))
    credits     = desc_data.get('credits','')

    credits_note = ''
    if credits:
        pm = re.search(r'მონაწილეობენ[\s:]+([^\n]+)', credits)
        dm = re.search(r'რეჟისორი[\s:]+([^\n]+)', credits)
        if pm:   credits_note = f'მსახიობები: {pm.group(1).strip()[:100]}.'
        elif dm: credits_note = f'რეჟისორი: {dm.group(1).strip()[:60]}.'

    if description:
        prompt = (
            f'შეადგინე მოკლე ქართული პასუხი ხმოვანი ასისტენტისთვის, '
            f'ოფიციალური სასაუბრო სტილით. მაქსიმუმ 4 წინადადება.\n\n'
            f'"{name}", {venue_note}, სეანსები: {dates_str}. {price_str}.\n'
            f'{credits_note}\nაღწერა: {description[:300]}\n\n'
            f'წესები:\n- 4 წინადადება\n'
            f'- 1: სახელი (სრული), ადგილი (სრული), ახლო სეანსი, ფასი\n'
            f'- 2-3: მოკლე აღწერა\n'
            f'- ნუ ახსენებ ბანკს, ბარათს, ფასდაკლებას\n'
            f'- ასაკობრივი შეზღუდვა მხოლოდ 18+ ან 16+ შემთხვევაში'
        )
        result = _gemini(prompt)
        if result:
            return _strip_age_restriction(result), _strip_age_restriction(result)

    parts = [f'"{name}"']
    if venue_note: parts.append(venue_note)
    parts.append(f'სეანსები: {dates_str}.')
    if price_str: parts.append(price_str + '.')
    if description: parts.append(_strip_promo(description[:200]))
    if credits_note: parts.append(credits_note)
    t = _strip_age_restriction(' '.join(parts))
    return t, t


# ── Route / directions ────────────────────────────────────────────────────────

def _format_route(directions: dict, dest_label: str = '') -> tuple:
    """
    Natural Georgian transit directions.

    Format:
      [dest-ში მისასვლელად] ფეხით იარეთ X წუთი [first_stop]-ის გაჩერებამდე.
      გაყევით N ავტობუსს [time]-ზე. [k] გაჩერება, ჩამოდით [arr_stop]-ის გაჩერებაზე.
      [ფეხით X წუთი.]
      სრული მგზავრობის დროა T.
    """
    steps       = directions.get('steps', [])
    total       = directions.get('total_duration','')
    has_transit = any(s.get('type') == 'transit' for s in steps)

    if not has_transit:
        walk_step = next((s for s in steps if s.get('type') == 'walking'), None)
        dur = _expand_dur(walk_step.get('duration','') if walk_step else total)
        dest_part = f'{_geo_locative(dest_label)}-ში მისასვლელად ' if dest_label else ''
        t = f'{dest_part}ფეხით {dur} გჭირდებათ.'
        return t, t

    parts: list[str] = []

    # Pre-compute: find first transit stop name for look-ahead
    first_transit_stop = ''
    for s in steps:
        if s.get('type') == 'transit':
            first_transit_stop = _stop_name(s.get('depart_stop',''))
            break

    for i, s in enumerate(steps):
        stype = s.get('type')

        if stype == 'walking':
            dur = _expand_dur(s.get('duration',''))
            if not dur: continue
            try:
                dist_raw = s.get('distance','')
                raw = float(re.sub(r'[^\d.]','', dist_raw.split()[0].replace(',','.')))
                metres = raw*1000 if 'კმ' in dist_raw or 'km' in dist_raw.lower() else raw
                if metres < 70: continue
            except Exception: pass

            # Look ahead: if next step is transit, mention its stop name
            next_transit = None
            for ns in steps[i+1:]:
                if ns.get('type') == 'transit':
                    next_transit = _stop_name(ns.get('depart_stop',''))
                    break

            if i == 0:
                if next_transit:
                    parts.append(f'ფეხით იარეთ {dur} {_geo_genitive(next_transit)}-ის გაჩერებამდე')
                else:
                    parts.append(f'ფეხით {dur}')
            else:
                parts.append(f'გაიარეთ ფეხით {dur}')

        elif stype == 'transit':
            line    = s.get('line_name','')
            dep_t   = s.get('departure_time','')
            arr_s   = _stop_name(s.get('arrive_stop',''))
            n_stops = s.get('num_stops', 0)

            # "გაყევით 305 ავტობუსს ორ საათზე"
            p = f'გაყევით {line} ავტობუსს'
            if dep_t: p += f' {_time_to_georgian(dep_t)}'
            parts.append(p)

            # "იმგზავრეთ N გაჩერება, ჩამოდით X-ის გაჩერებაზე"
            if n_stops or arr_s:
                q = ''
                if n_stops: q += f'იმგზავრეთ {n_stops} გაჩერება'
                if arr_s:
                    arr_gen = _geo_genitive(arr_s)
                    if q: q += f', ჩამოდით {arr_gen}-ის გაჩერებაზე'
                    else: q = f'ჩამოდით {arr_gen}-ის გაჩერებაზე'
                parts.append(q)

    if not parts:
        t = 'მარშრუტი ვერ მოიძებნა.'
        return t, t

    total_part = f'სრული მგზავრობის დროა {_expand_dur(total)}.' if total else ''

    # Prefix with destination
    dest_prefix = f'{_geo_locative(dest_label)}-ში მისასვლელად ' if dest_label else ''
    text = dest_prefix + '. '.join(parts) + '. ' + total_part
    text = text.rstrip('. ').rstrip() + ('.' if total_part else '.')
    text = re.sub(r'\.\s*\.', '.', text)  # clean double dots
    return text, text


# ── Bus ───────────────────────────────────────────────────────────────────────

def _format_buses_at_named_place(place: str, schedules: list) -> tuple:
    """All buses arriving at a named place within reasonable time."""
    if not schedules:
        t = f'{place}-სთან ახლომდებარე ავტობუსი ვერ მოიძებნა.'
        return t, t
    now_mins = datetime.now().hour * 60 + datetime.now().minute
    parts = []
    for s in schedules[:8]:
        r   = s.get('route_number','')
        dep = s.get('departure_time','')
        if not r or not dep: continue
        # Parse dep time → minutes
        try:
            h, m = map(int, dep.split(':'))
            diff = h*60 + m - now_mins
            if diff < 0 or diff > 30: continue  # only within 30 min
        except Exception: pass
        parts.append(f'{r}-ე ავტობუსი {_time_to_georgian(dep)}')
    if not parts:
        # Fallback: just list the first few regardless
        for s in schedules[:5]:
            r = s.get('route_number','')
            dep = s.get('departure_time','')
            if r and dep: parts.append(f'{r}-ე ავტობუსი {_time_to_georgian(dep)}')
    if not parts:
        t = f'{place}-სთან ახლომდებარე ავტობუსი ვერ მოიძებნა.'
        return t, t
    loc = _geo_locative(place)
    t = f'{loc} ახლოს: ' + '. '.join(parts) + '.'
    return t, t

def _format_route_bus_at_named_place(route_number: str, place: str, schedules: list) -> tuple:
    """When does specific route arrive at a named place."""
    if not schedules:
        t = f'{route_number}-ე ავტობუსი {_geo_locative(place)}-სთან ვერ მოიძებნა.'
        return t, t
    s    = schedules[0]
    stop = _stop_name(s.get('name') or s.get('stop_name') or s.get('depart_stop') or '')
    dep  = s.get('departure_time','')
    loc  = _geo_locative(place)
    if dep and stop:
        stop_gen = _geo_genitive(stop)
        t = f'{route_number}-ე ავტობუსი {loc}-სთან {stop_gen}-ის გაჩერებაზე {_time_to_georgian(dep)} მოვა.'
    elif dep:
        t = f'{route_number}-ე ავტობუსი {loc}-სთან {_time_to_georgian(dep)} მოვა.'
    else:
        t = f'{route_number}-ე ავტობუსი {loc}-სთან — ინფორმაცია ვერ მოიძებნა.'
    return t, t

def _format_bus_at_nearest(route_number: str, stops: list, gps_stops=None) -> tuple:
    if gps_stops:
        route_gps = [s for s in gps_stops if str(s.get('route_number','')) == str(route_number)]
        if route_gps:
            s = route_gps[0]
            stop  = _stop_name(s.get('name') or s.get('stop_name') or '')
            wm    = _walk_min(s)
            dep   = s.get('departure_time','')
            walk  = f' გაჩერებამდე {wm} წუთის სავალია.' if wm else '.'
            if dep and stop:
                t = f'{route_number}-ე ავტობუსი {_time_to_georgian(dep)} მოვა {_geo_genitive(stop)}-ის გაჩერებაზე.{walk}'
            elif dep:
                t = f'{route_number}-ე ავტობუსი {_time_to_georgian(dep)} მოვა.{walk}'
            else:
                t = f'{route_number}-ე ავტობუსი {_geo_genitive(stop)}-ის გაჩერებაზე გაივლის.{walk}'
            return t, t

    if not stops:
        t = (f'{route_number}-ე მარშრუტის ინფორმაცია ვერ მოიძებნა. '
             f'ხელმისაწვდომია: 299, 300, 301, 302, 305, 307, 312, 314, 315, 320.')
        return t, t
    stop = stops[0]; name = _stop_name(stop['name'])
    deps = _next_deps(stop['schedule'], count=2)
    if deps:
        times = ' და '.join(_dep_spoken(h,m) for h,m in deps)
        t = f'{route_number}-ე ავტობუსი {_geo_genitive(name)}-ის გაჩერებაზე {times} მოვა.'
    else:
        t = f'{route_number}-ე ავტობუსი "{name}" — დღის ბოლო რეისი გავიდა.'
    return t, t

def _format_bus(route_number: str, stops: list) -> tuple:
    if not stops:
        t = (f'{route_number}-ე მარშრუტის ინფორმაცია ვერ მოიძებნა. '
             f'ხელმისაწვდომია: 299, 300, 301, 302, 305, 307, 312, 314, 315, 320.')
        return t, t
    parts = []
    for stop in stops[:2]:
        name = _stop_name(stop['name'])
        deps = _next_deps(stop['schedule'], count=2)
        if deps:
            times = ', '.join(_dep_spoken(h,m) for h,m in deps)
            parts.append(f'{name}: {times}')
        else:
            parts.append(f'{name} — ბოლო რეისი')
    t = f'{route_number}-ე მარშრუტი. ' + '. '.join(parts) + '.'
    return t, t

def _format_buses_at_place(place: str, results: list) -> tuple:
    if not results:
        t = f'"{place}"-სთან გამავალი ავტობუსი ვერ მოიძებნა.'
        return t, t
    routes = sorted({r['route_number'] for r in results})
    t = f'"{place}"-სთან გაივლის: {", ".join(f"{r}-ე" for r in routes)} მარშრუტი.'
    return t, t


# ── Nearest stops / buses ─────────────────────────────────────────────────────

def _format_nearest(stops: list) -> tuple:
    """Nearest buses with departure time and stop name."""
    if not stops:
        t = 'ახლომდებარე ავტობუსი ვერ მოიძებნა.'
        return t, t
    parts = []
    for s in stops[:5]:
        r     = s.get('route_number','')
        dep   = s.get('departure_time','')
        wm    = _walk_min(s)
        raw   = s.get('name') or s.get('stop_name') or s.get('depart_stop') or ''
        stop  = _stop_name(raw)
        # Format: "305 ავტობუსი X-ზე მოვა Y-ის გაჩერებაზე. ეს გაჩერება Z წუთის სავალზეა."
        if r and dep and stop:
            stop_gen = _geo_genitive(stop)
            walk_part = f' ეს გაჩერება {wm} წუთის სავალზეა' if wm else ''
            parts.append(
                f'{r} ავტობუსი {_time_to_georgian(dep)} მოვა {stop_gen}-ის გაჩერებაზე.{walk_part}'
            )
        elif r and dep:
            walk_part = f', {wm} წუთის სავალი' if wm else ''
            parts.append(f'{r} ავტობუსი {_time_to_georgian(dep)}{walk_part}')
        elif r:
            walk_part = f', {wm} წუთის სავალი' if wm else ''
            parts.append(f'{r} მარშრუტი{walk_part}')
    if not parts:
        t = 'ახლომდებარე ავტობუსი ვერ მოიძებნა.'
        return t, t
    t = f'ახლო გაჩერებებზე {len(parts)} ავტობუსი მოიძებნა. ' + ' '.join(parts)
    return t, t

def _format_nearest_stops(stops: list) -> tuple:
    """Stop names with walking time — no buses."""
    if not stops:
        t = 'ახლომდებარე გაჩერება ვერ მოიძებნა.'
        return t, t
    seen = {}
    for s in stops:
        name = _stop_name(s.get('name') or s.get('stop_name') or '')
        dist = s.get('distance_m') or 9999
        if name and name not in seen: seen[name] = dist
    lines = []
    for name, dist in sorted(seen.items(), key=lambda x: x[1])[:5]:
        wm = round(dist/80) if dist < 9999 else None
        lines.append(f'"{name}" {wm} წუთის სავალზე' if wm else f'"{name}"')
    if not lines:
        t = 'ახლომდებარე გაჩერება ვერ მოიძებნა.'
        return t, t
    t = f'ახლოს მოვძებნე {len(lines)} გაჩერება: ' + '. '.join(lines) + '.'
    return t, t


# ── Home route ────────────────────────────────────────────────────────────────

def _format_home_route(results: list, home_address: str = '', directions=None) -> tuple:
    if directions and directions.get('steps'):
        text, _ = _format_route(directions, '')
        return 'სახლში: ' + text, 'სახლში: ' + text
    if not results:
        t = 'სახლთან ახლოს ავტობუსი ვერ მოიძებნა.'
        return t, t
    parts = []
    for r in results[:3]:
        rn = r.get('route_number','')
        deps = _next_deps(r.get('schedule',[]), count=2)
        if deps:
            times = ', '.join(_dep_spoken(h,m) for h,m in deps)
            parts.append(f'{rn}-ე: {times}')
        else:
            parts.append(f'{rn}-ე: ბოლო რეისი')
    dest = f' ({home_address})' if home_address else ''
    t = f'სახლში{dest} მიმავალი ავტობუსები: ' + '. '.join(parts) + '.'
    return t, t


# ── Arrival planning ──────────────────────────────────────────────────────────

def _format_arrival_planning(intent, directions) -> tuple:
    """
    User asked 'when do I leave to arrive at X by HH:MM'.
    Formats departure time, full route, then arrival time.
    """
    arrival_time   = intent.specific_date or ''
    place          = intent.place or 'ადგილი'
    arrival_spoken = _time_to_georgian(arrival_time) if arrival_time else ''
    place_loc      = _geo_locative(place) if place != 'ადგილი' else place

    if directions and directions.get('steps'):
        dep_time = directions.get('departure_time','')
        arr_time = directions.get('arrival_time','')
        total    = directions.get('total_duration','')
        route_text, _ = _format_route(directions, '')

        # "იმისათვის რომ X-ში მიხვიდეთ Y-ზე, სახლიდან უნდა გახვიდეთ Z-ზე."
        if dep_time and arrival_spoken:
            prefix = (f'იმისათვის, რომ {place_loc} მიხვიდეთ {arrival_spoken}, '
                      f'სახლიდან უნდა გახვიდეთ {dep_time}-ზე. ')
        elif dep_time:
            prefix = f'{dep_time}-ზე გამოდით. '
        else:
            prefix = ''

        arr_suffix = ''
        if arr_time:
            arr_suffix = f' დანიშნულების ადგილზე იქნებით {_time_to_georgian(arr_time)}.'

        t = prefix + route_text.rstrip('.') + arr_suffix
        return t, t

    if arrival_spoken:
        t = f'{arrival_spoken} {place_loc} — მარშრუტი ვერ მოიძებნა.'
    else:
        t = f'{place_loc} მარშრუტი ვერ მოიძებნა.'
    return t, t


# ── Combined: event detail + route to venue ───────────────────────────────────

def _format_event_with_route(events: list, event_name: str,
                              directions=None) -> tuple:
    date_disp, date_tts = _format_event_dates(events, event_name)
    if directions and directions.get('steps'):
        route_text, _ = _format_route(directions, '')
        display = f'{date_disp}\n\nმისასვლელი გზა: {route_text}'
        tts     = f'{date_tts} {route_text}'
    else:
        display = f'{date_disp}\n\nმარშრუტი ვერ გამოითვალა.'
        tts     = f'{date_tts} მარშრუტი ვერ გამოითვალა.'
    return display, tts


# ── Unknown ───────────────────────────────────────────────────────────────────

def _format_unknown() -> tuple:
    t = ('ვერ გავიგე. შემიძლია გითხრა კონცერტებზე, სპექტაკლებზე, ოპერაზე, '
         'ან გითხრა როგორ მიხვიდე სასურველ ადგილამდე.')
    return t, t


# ── build_response ────────────────────────────────────────────────────────────

def build_response(intent: IntentResult, results: list,
                   venue_bus_offer=None, home_address='',
                   event_detail=None, directions=None,
                   extra_context: dict | None = None) -> dict:
    display, tts = '', ''
    ctx = extra_context or {}

    if intent.intent == 'bus_search':
        if ctx.get('buses_at_named_place'):
            display, tts = _format_buses_at_named_place(intent.place or '', results)
        elif ctx.get('bus_at_named_place'):
            display, tts = _format_route_bus_at_named_place(
                intent.route or '?', intent.place or '', results)
        elif ctx.get('buses_at_place'):
            display, tts = _format_buses_at_place(intent.place or intent.venue or '', results)
        elif ctx.get('nearest_for_route'):
            display, tts = _format_bus_at_nearest(
                intent.route or '?', results, gps_stops=ctx.get('gps_stops'))
        else:
            display, tts = _format_bus(intent.route or '?', results)

    elif intent.intent == 'concert_search':
        if results:
            category = results[0].get('category') if results else None
            display, tts = _format_concert_list(results, category)
        else:
            cat_label  = _CATEGORY_LABEL.get(intent.category,'ღონისძიება') if intent.category else 'ღონისძიება'
            venue_note = f' {intent.venue}-ში' if intent.venue else ''
            date_note  = f' {intent.specific_date}-ს' if intent.specific_date else ''
            t = f'ახლო დღეებში{venue_note}{date_note} {cat_label} ვერ მოიძებნა.'
            display, tts = t, t

    elif intent.intent == 'journey_search':
        if directions and directions.get('steps'):
            display, tts = _format_route(directions, intent.place or '')
        elif results:
            routes = list({r['route_number'] for r in results})
            place  = intent.place or 'ადგილი'
            t = f'{place}-სთან მიმავალი მარშრუტები: {", ".join(routes[:5])}.'
            display, tts = t, t
        else:
            t = 'ამ ადგილთან მიმავალი ავტობუსი ვერ მოიძებნა.'
            display, tts = t, t

    elif intent.intent == 'home_route':
        display, tts = _format_home_route(results, home_address, directions)

    elif intent.intent == 'event_detail':
        evs  = (event_detail if isinstance(event_detail, list)
                else ([event_detail] if event_detail else []))
        orig = ctx.get('original_text','').lower()
        if ctx.get('event_with_route'):
            display, tts = _format_event_with_route(evs, intent.event_name or '',
                                                     directions=directions)
        else:
            venue_only = ctx.get('venue_only', False) or any(
                kw in orig for kw in ['სად ტარდება','სად იმართება','სად არის','სად გაიმართება'])
            dates_only = ctx.get('dates_only', False) or (not venue_only and any(
                kw in orig for kw in ['რა დღეებ','რომელ დღეებ','სეანს','კვირ','განმავლობ',
                                       'გრაფიკ','განრიგ','როდის ტარდება','როდის არის',
                                       'როდის გაიმართება','როდის იქნება']))
            display, tts = _format_event_detail(
                evs, intent.event_name or '',
                dates_only=dates_only, venue_only=venue_only,
                context_date=ctx.get('context_date',''),
                user_query=orig,
            )

    elif intent.intent == 'nearest_stop':
        if ctx.get('stops_only'):
            display, tts = _format_nearest_stops(results or [])
        else:
            display, tts = _format_nearest(results or [])

    elif intent.intent == 'arrival_planning':
        display, tts = _format_arrival_planning(intent, directions)

    elif intent.intent == 'save_home_location':
        display = 'სახლის მისამართი შეინახა.'
        tts     = display

    else:
        display, tts = _format_unknown()

    display = _strip_promo(display or '')
    tts     = _strip_promo(tts or '')
    return {'response_text': display, 'tts_text': tts}