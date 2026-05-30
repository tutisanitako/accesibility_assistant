# backend/nlp/intent_parser.py
import re, os, json, sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import IntentResult

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an intent parser for a Georgian voice assistant called "თბილისის ასისტენტი".

Return a JSON object. Possible intents:
- "concert_search": find events/concerts/theatre/opera
- "event_detail": user asks about a SPECIFIC named show — description, info, details, dates, schedule, OR asks when a specific show is held
- "nearest_stop": user asks about nearby stops/buses with no specific destination
- "bus_search": asks about a specific bus route NUMBER with transport words
- "journey_search": how to GET TO a place OR from one place to another
- "arrival_planning": user wants to know WHEN TO LEAVE to arrive at a place by a specific time
- "home_route": wants to go home
- "unknown"

JSON format:
{
  "intent": "...",
  "days": <int, default 30 for opera, 7 otherwise>,
  "route": <string or null>,
  "place": <string, journey_search only — nominative form>,
  "venue": <string or null>,
  "specific_date": <"DD მაი" format or null>,
  "category": <"კონცერტი"|"თეატრი"|"ოპერა"|null>,
  "event_name": <string or null>
  "arrival_time": <"HH:MM" or null — for arrival_planning only>,
  "origin": <string or null — starting point if specified>,
}

CRITICAL RULES:
- Numbers like "30", "6" are bus routes ONLY when transport words present (ავტობუსი/მარშრუტი/ტრანსპორტი/ttc)
- "30 მაისი", "ექვს მაისს", "ოცდაათი მაისის" = specific_date, NOT bus
- journey_search: ANY movement verb → "წამიყვანე","მიმიყვანე","მივიდე","წავიდე","ჩავიდე","მისასვლელი","მიმავალი","როგორ მივიდე"
- "სახლში მიყვანე"/"სახლში მიმიყვანე"/"სახლში წამიყვანე" → home_route
- "X-იდან სახლამდე"/"X-დან სახლში" → home_route (with origin=X)
- opera default days=30
- event_detail: ANY query about a SPECIFIC named show, including:
  * "რა დღეებში ტარდება X" → event_detail, event_name:"X"
  * "X-ის სეანსები" → event_detail, event_name:"X"
  * "X შემდეგი ორი კვირის განმავლობაში" → event_detail, event_name:"X"
  * "X როდის ტარდება" → event_detail, event_name:"X"
  * "X-ის გრაფიკი" → event_detail, event_name:"X"
  * "X-ის აღწერა" / "X-ის შესახებ" → event_detail, event_name:"X"
- For days: "ხვალ"→1, "დღეს"→0, "ზეგ"→2, "ამ კვირაში"→7, "ამ თვეში"→30

Georgian date words (genitive case used in speech):
ერთ/პირველ→1, ორ/მეორე→2, სამ/მესამე→3, ოთხ/მეოთხე→4, ხუთ/მეხუთე→5,
ექვს/მეექვსე→6, შვიდ/მეშვიდე→7, რვა/მერვე→8, ცხრა/მეცხრე→9, ათ/მეათე→10,
თერთმეტ→11, თორმეტ→12, ცამეტ→13, თოთხმეტ→14, თხუთმეტ→15, თექვსმეტ→16,
ჩვიდმეტ→17, თვრამეტ→18, ცხრამეტ→19, ოც/ოცი→20, ოცდაერთ→21, ოცდაორ→22,
ოცდასამ→23, ოცდაოთხ→24, ოცდახუთ→25, ოცდაექვს→26, ოცდაშვიდ→27,
ოცდარვა→28, ოცდაცხრა→29, ოცდაათ/ოცდაათი→30, ოცდათერთმეტ→31

Month names: იანვარ→იან, თებერვალ→თებ, მარტ→მარ, აპრილ→აპრ, მაის→მაი,
ივნის→ივნ, ივლის→ივლ, აგვისტ→აგვ, სექტემბერ→სექ, ოქტომბერ→ოქტ, ნოემბერ→ნოე, დეკემბერ→დეკ

Examples:
- "ხვალ რა სპექტაკლებია" → concert_search, category:"თეატრი", days:1
- "ხვალინდელი კონცერტები" → concert_search, category:"კონცერტი", days:1
- "დღეს რა ტარდება" → concert_search, days:0
- "ზეგ კონცერტები" → concert_search, days:2
- "ამ კვირის ღონისძიებები" → concert_search, days:7
- "ექვს მაისს რა თეატრებია" → concert_search, specific_date:"06 მაი", category:"თეატრი"
- "ოცდაათი მაისის კონცერტები" → concert_search, specific_date:"30 მაი", category:"კონცერტი"
- "წამიყვანე ნუცუბიძის პლატოზე" → journey_search, place:"ნუცუბიძის პლატო"
- "305 ავტობუსი" → bus_search, route:"305"
- "სახლში წამიყვანე" → home_route
- "რუსთაველის მეტროდან სახლამდე" → home_route, origin:"რუსთაველის მეტრო"
- "მეტროდან სახლში მივიდე" → home_route, origin:"მეტრო"
- "მაკბეტი როდის ტარდება" → event_detail, event_name:"მაკბეტი"
- "რა დღეებში ტარდება მაკბეტი" → event_detail, event_name:"მაკბეტი"
- "რა დღეებში ტარდება მაკბეტი შემდეგი ორი კვირის განმავლობაში" → event_detail, event_name:"მაკბეტი"
- "მაკბეტის სეანსები" → event_detail, event_name:"მაკბეტი"
- "ურჩხული და ლამაზმანი რომელ დღეებში" → event_detail, event_name:"ურჩხული და ლამაზმანი"
- "ბენზინგასამართი სადგური გრაფიკი" → event_detail, event_name:"ბენზინგასამართი სადგური"
- "მითხარი რწყილი და ჭიანჭველას აღწერილობა" → event_detail, event_name:"რწყილი და ჭიანჭველა"
- "გაბრიაძის თეატრში რა ტარდება" → concert_search, venue:"გაბრიაძის თეატრი"
- "ახლო გაჩერება მითხარი" → nearest_stop
- "X-იდან Y-მდე" → journey_search, place:"Y", origin:"X"
- "როდის გავიდე სახლიდან რომ 22:00-ზე ვიყო X-თან" → arrival_planning, place:"X", arrival_time:"22:00"

Return ONLY valid JSON."""


def _parse_with_gemini(text: str) -> IntentResult | None:
    try:
        from google import genai
        from google.genai import types
        api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
        if not api_key:
            return None
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=types.Content(role='user', parts=[types.Part(text=f'{_SYSTEM_PROMPT}\n\nUser text: {text}')]),
            config=types.GenerateContentConfig(temperature=0, max_output_tokens=400),
        )
        raw = None
        if response.text:
            raw = response.text.strip()
        elif response.candidates:
            for cand in response.candidates:
                if cand.content and cand.content.parts:
                    raw = ''.join(p.text for p in cand.content.parts if p.text).strip()
                    break
        if not raw:
            return None
        raw = re.sub(r'```(?:json)?|```', '', raw).strip()
        parsed = json.loads(raw)
        print(f'GEMINI: {parsed}', flush=True)
        intent = parsed.get('intent', 'unknown')
        lower_text = text.lower()

        # ── Fix days for time words Gemini often gets wrong ──
        if intent == 'concert_search':
            if any(kw in lower_text for kw in ['ხვალ', 'tomorrow', 'ხვალინდელ']):
                parsed['days'] = 1
            elif any(kw in lower_text for kw in ['დღეს', 'today', 'ახლა']):
                parsed['days'] = 0
            elif any(kw in lower_text for kw in ['ზეგ', 'ზეგინდელ']):
                parsed['days'] = 2
            elif any(kw in lower_text for kw in ['ამ კვირაში', 'ამ კვირას', 'კვირაში', 'this week']):
                parsed['days'] = 7
            # Opera default
            if parsed.get('category') == 'ოპერა' and parsed.get('days', 7) <= 7:
                if not any(kw in lower_text for kw in ['ხვალ','დღეს','ზეგ','ამ კვირ']):
                    parsed['days'] = 30

        # ── concert_search with category as place name → redirect ──
        if intent == 'journey_search':
            place = (parsed.get('place') or '').lower()
            cat_map = {'თეატრი': 'თეატრი', 'ოპერა': 'ოპერა', 'კონცერტი': 'კონცერტი', 'ბალეტი': 'ოპერა'}
            if place in cat_map:
                return IntentResult(intent='concert_search', days=parsed.get('days', 7), category=cat_map[place])

        if intent == 'nearest_stop':
            return IntentResult(intent='nearest_stop')

        if intent == 'arrival_planning':
            return IntentResult(
                intent='arrival_planning',
                place=parsed.get('place'),
                specific_date=parsed.get('arrival_time'),
            )

        # ── home_route with origin ──
        if intent == 'home_route':
            return IntentResult(
                intent='home_route',
                origin=parsed.get('origin'),
            )

        return IntentResult(
            intent=intent,
            days=parsed.get('days',
                            30 if parsed.get('category') == 'ოპერა' else 7) if intent == 'concert_search' else None,
            route=str(parsed['route']) if parsed.get('route') else None,
            place=parsed.get('place') if intent in ('journey_search', 'arrival_planning') else None,
            origin=parsed.get('origin') if intent in ('journey_search', 'arrival_planning', 'home_route') else None,
            venue=parsed.get('venue') if intent == 'concert_search' else None,
            specific_date=parsed.get('specific_date') if intent == 'concert_search' else parsed.get(
                'arrival_time') if intent == 'arrival_planning' else None,
            category=parsed.get('category') if intent == 'concert_search' else None,
            event_name=parsed.get('event_name') if intent == 'event_detail' else None,
        )
    except Exception as e:
        log.warning('Gemini intent failed: %s', e)
        return None


# ── Date extraction ───────────────────────────────────────────────────────────

_ALL_NUMS = {
    'ოცდათერთმეტ':31,'ოცდათერთმეტი':31,
    'ოცდაათ':30,'ოცდაათი':30,
    'ოცდაცხრა':29,'ოცდარვა':28,'ოცდაშვიდ':27,'ოცდაექვს':26,
    'ოცდახუთ':25,'ოცდაოთხ':24,'ოცდასამ':23,'ოცდაორ':22,'ოცდაერთ':21,
    'ოცი':20,'ოც':20,
    'ცხრამეტ':19,'თვრამეტ':18,'ჩვიდმეტ':17,'თექვსმეტ':16,
    'თხუთმეტ':15,'თოთხმეტ':14,'ცამეტ':13,'თორმეტ':12,'თერთმეტ':11,
    'ათი':10,'ათ':10,
    'ცხრა':9,'რვა':8,'შვიდ':7,'შვიდი':7,
    'ექვსი':6,'ექვს':6,'ხუთი':5,'ხუთ':5,
    'ოთხი':4,'ოთხ':4,'სამი':3,'სამ':3,'ორი':2,'ორ':2,'ერთი':1,'ერთ':1,
    'მეათე':10,'მეცხრე':9,'მერვე':8,'მეშვიდე':7,'მეექვსე':6,
    'მეხუთე':5,'მეოთხე':4,'მესამე':3,'მეორე':2,'პირველ':1,
}

_GEO_MONTHS_FULL = {
    'იანვარ':1,'თებერვალ':2,'მარტ':3,'აპრილ':4,'მაის':5,'ივნის':6,
    'ივლის':7,'აგვისტ':8,'სექტემბერ':9,'ოქტომბერ':10,'ნოემბერ':11,'დეკემბერ':12,
}
_MONTH_ABBR = {1:'იან',2:'თებ',3:'მარ',4:'აპრ',5:'მაი',6:'ივნ',
               7:'ივლ',8:'აგვ',9:'სექ',10:'ოქტ',11:'ნოე',12:'დეკ'}


def _extract_specific_date(text: str) -> str | None:
    lower = text.lower()
    m = re.search(
        r'(\d{1,2})\s+(იანვარ|თებერვალ|მარტ|აპრილ|მაის|ივნის|ივლის|აგვისტ|სექტემბერ|ოქტომბერ|ნოემბერ|დეკემბერ)',
        lower
    )
    if m:
        day = int(m.group(1))
        for stem, num in _GEO_MONTHS_FULL.items():
            if m.group(2).startswith(stem[:4]):
                return f'{day:02d} {_MONTH_ABBR[num]}'
    for word, day in sorted(_ALL_NUMS.items(), key=lambda x: -len(x[0])):
        if word in lower:
            idx = lower.index(word)
            rest = lower[idx + len(word):].strip()
            for stem, num in _GEO_MONTHS_FULL.items():
                if rest.startswith(stem[:4]):
                    return f'{day:02d} {_MONTH_ABBR[num]}'
    return None


# ── Keyword sets ──────────────────────────────────────────────────────────────

_CONCERT_KW = {'კონცერტ','ბილეთ','ივენთ','ივენტ','შოუ','ფესტივალ','tkt','concert','show','event'}
_THEATRE_KW = {'სპექტაკლ','წარმოდგენ','თეატრ','theatre','theater','play'}
_OPERA_KW   = {'ოპერ','ბალეტ','opera','ballet'}
_BUS_KW     = {'ავტობუს','მარშრუტ','გაჩერებ','ტრანსპორტ','ttc','bus','route'}
_EVENT_KW   = {'ღონისძიებ'}

_JOURNEY_KW = {
    'მივიდე','მივიდეთ','მისვლა','მისასვლელ','წავიდე','ჩავიდე','ჩასვლა',
    'ჩავაღწიო','მივაღწიო','მოვხვდე','მიმავალი','გზა','მარშრუტი',
    'მიდის','მივა','ახლოს','მდე მიდის',
    'იდან','დან','ფაბრიკიდან',
    'წამიყვანე','წამიყვანეთ','მიმიყვანე','მიმიყვანეთ',
    'გამიყვანე','გამიყვანეთ','წაიყვანე',
    'როგორ მივიდე','როგორ წავიდე','როგორ ჩავიდე',
    'which bus','what bus',
}

_HOME_KW = {
    'სახლში','სახლისკენ','home',
    'სახლში მიყვანე','სახლში მიმიყვანე','სახლში წამიყვანე',
    'სახლამდე მიყვანე','take me home','სახლამდე',
}

# ── EXTENDED detail triggers: descriptions + dates/schedule queries ──
_DETAIL_TRIGGERS = {
    # Description/info queries
    'აღწერილობ','აღწერ','შესახებ','დეტალ','ინფორმაცი',
    'სად ტარდება','რომელ საათ','იმართება','გაიმართება',
    'ბილეთი რა','რა ღირს','ვინ თამაშობ','ვინ მონაწილეობ',
    # Date/schedule queries for specific named shows
    'რა დღეებ','რომელ დღეებ','სეანსები','სეანს',
    'ყველა სეანს','შემდეგი კვირ','ორი კვირ','სამი კვირ',
    'თვის განმავლობ','კვირის განმავლობ','სრული გრაფიკ',
    'გრაფიკი','განრიგი','გრაფიკ',
    # "when is X" patterns
    'როდის არის','როდის ტარდება','როდის იქნება','როდის გაიმართება',
}

_DAY_MAP = {
    'დღეს':0,'ახლა':0,'ხვალ':1,'ხვალინდელ':1,'ზეგ':2,
    'ამ კვირაში':7,'ამ კვირას':7,'კვირაში':7,'კვირის':7,
    'ამ თვეში':30,'თვეში':30,'შემდეგი თვის':30,'ერთი თვის':30,
    'today':0,'tomorrow':1,'this week':7,'this month':30,
}

_NOISE = {
    'მივიდე','მივიდეთ','ჩავიდე','წავიდე','გადავიდე','წამიყვანე','მიმიყვანე',
    'გამიყვანე','როგორ','რომელი','სად','რა','მითხარი','შეგიძლია',
    'ჩავაღწიო','მივაღწიო','მოვხვდე','სახლი','სახლში','მინდა','გთხოვ',
    'მეტრო','გაჩერება','სადგური','ავტობუსი','მარშრუტი','ახლოს','მახლობლად',
    'რომ','თუ','ან','არის','არ','ვარ','თეატრი','ოპერა','კონცერტი',
    'სპექტაკლი','ბალეტი',
}


def _extract_days(lower: str) -> int:
    for phrase in sorted(_DAY_MAP.keys(), key=len, reverse=True):
        if phrase in lower:
            return _DAY_MAP[phrase]
    m = re.search(r'(\d+)\s*(დღეში|დღეს|დღე|days?)', lower)
    if m:
        return max(1, min(int(m.group(1)), 30))
    return 7


def _extract_route(text: str) -> str | None:
    lower = text.lower()
    if not any(kw in lower for kw in _BUS_KW):
        return None
    m = re.search(r'\b(\d{3})\b', text) or re.search(r'\b(\d{2})\b', text)
    return m.group(1) if m else None


def _has(lower: str, kw_set: set) -> bool:
    return any(kw in lower for kw in kw_set)


def _extract_place(text: str) -> str:
    for kw in sorted(_JOURNEY_KW, key=len, reverse=True):
        text = re.sub(re.escape(kw), '', text, flags=re.IGNORECASE)
    words = re.findall(r'[\u10D0-\u10FF]+', text)
    cleaned = []
    for w in words:
        if w in _NOISE:
            continue
        stripped = w
        for suf in ['სთანაც','ასთანაც','ისთვის','სთან','ასთან','ებში','ებზე',
                    'ებს','ისკენ','ისგან','იდან','ში','ზე','ად','ით','სკენ']:
            if stripped.endswith(suf) and len(stripped) > len(suf) + 2:
                stripped = stripped[:-len(suf)]
                break
        if stripped.endswith('ის') and len(stripped) > 4:
            stripped = stripped[:-2]
        elif stripped.endswith('ს') and len(stripped) > 3:
            stripped = stripped[:-1]
        if stripped and stripped not in _NOISE and len(stripped) > 1:
            cleaned.append(stripped)
    return ' '.join(cleaned).strip() or text.strip()


def _extract_event_name(text: str) -> str:
    """Extract event name, removing query scaffolding words."""
    remove = [
        'მითხარი','შეგიძლია','მაინტერესებს','გთხოვ',
        'აღწერილობა','შესახებ','დეტალები','ინფორმაცია',
        'სად ტარდება','რომელ საათზე','სად არის','რა არის',
        'დეტალი','მოყევი','გვიამბე',
        # Date query words to strip
        'რა დღეებში ტარდება','რა დღეებში','რომელ დღეებში',
        'სეანსები','ყველა სეანსი','სრული გრაფიკი','განრიგი',
        'შემდეგი ორი კვირის განმავლობაში','შემდეგი კვირის განმავლობაში',
        'ორი კვირის განმავლობაში','სამი კვირის განმავლობაში',
        'თვის განმავლობაში','კვირის განმავლობაში',
        'შემდეგი','განმავლობაში','კვირის','თვის',
        'როდის ტარდება','როდის არის','როდის იქნება','როდის გაიმართება',
    ]
    result = text.lower()
    for w in sorted(remove, key=len, reverse=True):
        result = result.replace(w.lower(), '')
    words = result.split()
    cleaned = []
    for w in words:
        stripped = w.strip()
        for suf in ['ის','ს','ზე','ში','ად']:
            if stripped.endswith(suf) and len(stripped) > len(suf) + 2:
                stripped = stripped[:-len(suf)]
                break
        if stripped and stripped not in _NOISE and len(stripped) > 1:
            cleaned.append(stripped)
    return ' '.join(cleaned).strip() or text.strip()


def _rule_based_parse(text: str) -> IntentResult:
    lower = text.lower()

    # Home route — check before journey
    # Also handles "from X to home"
    home_dest_patterns = ['სახლამდე','სახლში მივი','სახლისკენ','take me home']
    if _has(lower, _HOME_KW) or any(p in lower for p in home_dest_patterns):
        if any(kw in lower for kw in ['მიყვანე','მიმიყვანე','წამიყვანე','წასვლა','მისვლა','მივიდე',
                                       'სახლამდე','სახლისკენ','take me home']):
            # Extract origin if present (e.g. "მეტროდან სახლამდე")
            origin = None
            origin_m = re.search(r'([\u10D0-\u10FF]{3,})იდან', text)
            if origin_m:
                w = origin_m.group(1)
                if w not in {'სახლ','ჩემ','იქ','აქ','მათ','ამ'}:
                    origin = w
            return IntentResult(intent='home_route', origin=origin)
        if 'სახლში' in lower and not _has(lower, _CONCERT_KW | _THEATRE_KW | _OPERA_KW):
            return IntentResult(intent='home_route')

    # Event detail — check before concert_search
    # Matches both description queries AND date/schedule queries for named events
    if _has(lower, _DETAIL_TRIGGERS):
        event_name = _extract_event_name(text)
        if event_name and len(event_name) > 2:
            return IntentResult(intent='event_detail', event_name=event_name)

    # Nearest stop
    _NEAREST_KW = {'ახლო გაჩერება','ახლომდებარე','ახლოს ავტობუს','nearest bus',
                   'ახლო ავტობუს','უახლოეს გაჩერება'}
    if any(kw in lower for kw in _NEAREST_KW):
        return IntentResult(intent='nearest_stop')

    # Arrival planning
    if ('გავიდე' in lower or 'გამოვიდე' in lower) and ('რომ' in lower or 'რათა' in lower) and (
            'საათ' in lower or 'ზე ვიყო' in lower):
        place = _extract_place(text)
        t_match = re.search(r'(\d{1,2}):(\d{2})', text) or re.search(r'(\d{1,2})\s*საათ', text)
        arrival_time = None
        if t_match:
            h = int(t_match.group(1))
            m = int(t_match.group(2)) if t_match.lastindex >= 2 and ':' in t_match.group(0) else 0
            arrival_time = f'{h:02d}:{m:02d}'
        return IntentResult(intent='arrival_planning', place=place, specific_date=arrival_time)

    # Journey — any movement verb
    if _has(lower, _JOURNEY_KW):
        place = _extract_place(text)
        # Extract origin if present
        origin = None
        origin_m = re.search(r'([\u10D0-\u10FF]{3,})იდან', text)
        if origin_m:
            w = origin_m.group(1)
            if w not in {'სახლ','ჩემ','იქ','აქ','მათ','ამ'}:
                origin = w
        return IntentResult(intent='journey_search', place=place, origin=origin)

    # Specific date extraction
    specific_date = _extract_specific_date(text)

    # Bus route — only with transport keywords
    route = _extract_route(text)
    if route and not specific_date:
        return IntentResult(intent='bus_search', route=route)
    if _has(lower, _BUS_KW) and not specific_date and not _has(lower, _OPERA_KW | _THEATRE_KW | _CONCERT_KW):
        return IntentResult(intent='bus_search', route=None)

    # Opera
    if _has(lower, _OPERA_KW):
        return IntentResult(
            intent='concert_search',
            days=30,
            specific_date=specific_date,
            category='ოპერა',
        )

    # Theatre
    if _has(lower, _THEATRE_KW):
        days = 30 if specific_date else _extract_days(lower)
        return IntentResult(
            intent='concert_search',
            days=days,
            specific_date=specific_date,
            category='თეატრი',
        )

    # Concert
    if _has(lower, _CONCERT_KW):
        days = 30 if specific_date else _extract_days(lower)
        return IntentResult(
            intent='concert_search',
            days=days,
            specific_date=specific_date,
            category='კონცერტი',
        )

    # All events or date query
    if _has(lower, _EVENT_KW) or specific_date:
        days = 30 if specific_date else _extract_days(lower)
        return IntentResult(
            intent='concert_search',
            days=days,
            specific_date=specific_date,
            category=None,
        )

    # Venue-only query
    venue_m = re.search(r'([ა-ჿ\s]+(?:თეატრ\w*|42))\s*(?:ში|ზე|ად)', text, re.IGNORECASE)
    if venue_m:
        venue_raw = venue_m.group(1).strip()
        venue_clean = re.sub(r'(ში|ზე|ად|ით)$', '', venue_raw).strip()
        if len(venue_clean) > 4 and 'თეატრ' in venue_clean.lower():
            return IntentResult(
                intent='concert_search',
                days=30,
                category=None,
                venue=venue_clean,
            )

    return IntentResult(intent='unknown')


def parse_intent(text: str) -> IntentResult:
    lower = text.lower()
    # Fast rule-based pre-checks
    if any(kw in lower for kw in {'ახლო გაჩერება','ახლომდებარე','უახლოეს გაჩერება','nearest'}):
        return IntentResult(intent='nearest_stop')
    if any(kw in lower for kw in {'სახლში წამიყვანე','სახლში მიმიყვანე','სახლში მიყვანე'}):
        return IntentResult(intent='home_route')
    if any(kw in lower for kw in {'ახლო გაჩერებიდან','უახლოეს გაჩერებიდან','ახლო გაჩერებაზე'}):
        return IntentResult(intent='nearest_stop')

    result = _parse_with_gemini(text)
    if result:
        log.info('Intent (Gemini): %s | %r', result.intent, text)
        return result
    result = _rule_based_parse(text)
    log.info('Intent (rules):  %s | %r', result.intent, text)
    return result