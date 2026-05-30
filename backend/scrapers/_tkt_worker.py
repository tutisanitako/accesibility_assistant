#!/usr/bin/env python
# backend/scrapers/_tkt_worker.py
"""
TKT.ge scraper. Uses gateway.tkt.ge REST API for exact session dates —
no Playwright on detail pages. Playwright is only used for listing pages.

Public API discovered from browser DevTools:
  GET https://gateway.tkt.ge/Shows/new?itemId=ID&category=Show&accessCode=&api_key=KEY
"""

import json, re, sys, time, urllib.request
from datetime import datetime, timedelta, date
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

_GATEWAY_API_KEY = '7d8d34d1-e9af-4897-9f0f-5c36c179be77'
_GATEWAY_BASE    = 'https://gateway.tkt.ge'

_MONTH_ABBR = {1:'იან',2:'თებ',3:'მარ',4:'აპრ',5:'მაი',6:'ივნ',
               7:'ივლ',8:'აგვ',9:'სექ',10:'ოქტ',11:'ნოე',12:'დეკ'}
_GEO_MONTHS = {'იან':1,'თებ':2,'მარ':3,'აპრ':4,'მაი':5,'ივნ':6,
               'ივლ':7,'აგვ':8,'სექ':9,'ოქტ':10,'ნოე':11,'დეკ':12}

# ALL THREE categories — each gets its own listing page scrape
_CATEGORIES = [
    ('concerts', 'კონცერტი'),
    ('theatre',  'თეატრი'),
    ('opera',    'ოპერა'),
]
_BUDGET = {'კონცერტი': 40, 'თეატრი': 70, 'ოპერა': 15}


def _fmt(d, m): return f'{d:02d} {_MONTH_ABBR[m]}'

def _parse_card_date(s):
    s = s.split('-')[0].strip()
    p = s.split()
    if len(p) < 2: return None
    try:
        d = int(p[0]); m = _GEO_MONTHS.get(p[1][:3])
        if not m: return None
        yr = datetime.now().year
        dt = datetime(yr, m, d)
        if dt < datetime.now() - timedelta(days=1): dt = datetime(yr+1, m, d)
        return dt
    except: return None

def _parse_iso(s):
    if not s: return None
    try:
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})', str(s))
        if m: return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except: pass
    return None

def _extract_time(s):
    m = re.search(r'T(\d{2}:\d{2})', str(s or ''))
    return m.group(1) if m else 'N/A'

def _fetch_gateway(item_id):
    url = (f'{_GATEWAY_BASE}/Shows/new?itemId={item_id}'
           f'&category=Show&accessCode=&api_key={_GATEWAY_API_KEY}')
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'ka,en;q=0.9',
        'Referer': f'https://tkt.ge/show/{item_id}/',
        'Origin': 'https://tkt.ge',
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f'  API err {item_id}: {e}', file=sys.stderr)
        return None

def _sessions_from_api(data, now, cutoff):
    now_d = now.date(); cut_d = cutoff.date()
    by_date = {}  # date -> best_time

    # Raw scan of entire JSON string for ISO dates in window
    raw = json.dumps(data)
    for m in re.finditer(r'(\d{4}-\d{2}-\d{2})(?:T(\d{2}:\d{2}))?', raw):
        d = _parse_iso(m.group(1))
        if d and now_d <= d <= cut_d:
            t = m.group(2) or 'N/A'
            # prefer a time over N/A
            if d not in by_date or by_date[d] == 'N/A':
                by_date[d] = t

    return [
        {'date_str': _fmt(d.day, d.month), 'time_str': t, 'sort_key': d}
        for d, t in sorted(by_date.items())
    ]

def _item_id(href):
    m = re.search(r'/show/(\d+)', href or '')
    return m.group(1) if m else None

def _scrape_category(page, url, category, now, cutoff, budget):
    events = []; remaining = budget
    print(f'Listing: {url}', file=sys.stderr)
    try:
        page.goto(url, wait_until='networkidle', timeout=25_000)
        page.wait_for_selector('[data-testid="event-item"]', timeout=15_000)
    except PWTimeout:
        print(f'Timeout: {url}', file=sys.stderr); return events

    cards = page.query_selector_all('[data-testid="event-item"]')
    print(f'  {category}: {len(cards)} cards', file=sys.stderr)

    for card in cards:
        try:
            name_el    = card.query_selector('[data-testid="title"]')
            venue_el   = card.query_selector('[data-testid="location"]')
            date_el    = card.query_selector('[data-testid="floating-date"]')
            link_el    = card.query_selector('a')
            price_el   = card.query_selector('span.text-\\[\\#0F78FF\\]')
            soldout_el = card.query_selector('button.bg-\\[\\#E1000F\\]')
            time_el    = card.query_selector('p[title*=":"]')

            name      = name_el.inner_text().strip()  if name_el  else 'N/A'
            venue     = venue_el.inner_text().strip() if venue_el else 'N/A'
            href      = (link_el.get_attribute('href') or '') if link_el else ''
            full_url  = 'https://tkt.ge' + href if href else 'N/A'
            date_text = date_el.inner_text().replace('\n',' ').strip() if date_el else ''
            price     = ('გაყიდულია' if soldout_el
                         else price_el.inner_text().strip() if price_el
                         else 'უფასო')
            time_raw  = time_el.get_attribute('title').strip() if time_el else ''
            card_time = time_raw.split(', ',1)[1] if ', ' in time_raw else (time_raw or 'N/A')

            iid = _item_id(href)
            sessions_used = False

            if iid and remaining > 0:
                remaining -= 1
                time.sleep(0.1)
                api_data = _fetch_gateway(iid)
                if api_data:
                    sessions = _sessions_from_api(api_data, now, cutoff)
                    if sessions:
                        sessions_used = True
                        for s in sessions:
                            events.append({'name':name,'venue':venue,'price':price,
                                           'date':s['date_str'],'time':s['time_str'],
                                           'category':category,'url':full_url})
                        print(f'  ✓ [{iid}] {name[:35]:35s} {len(sessions)} dates', file=sys.stderr)
                    else:
                        print(f'  ~ [{iid}] {name[:35]:35s} no dates in window', file=sys.stderr)

            if not sessions_used:
                parts = [p.strip() for p in date_text.split(' - ')]
                s_dt = _parse_card_date(parts[0])
                e_dt = _parse_card_date(parts[-1])
                ok = False
                if s_dt and e_dt: ok = s_dt.date() <= cutoff.date() and e_dt.date() >= now.date()
                elif s_dt:        ok = now.date() <= s_dt.date() <= cutoff.date()
                if ok:
                    events.append({'name':name,'venue':venue,'price':price,
                                   'date':date_text,'time':card_time,
                                   'category':category,'url':full_url})

        except Exception as e:
            print(f'Card err: {e}', file=sys.stderr)

    print(f'  {category} total: {len(events)}', file=sys.stderr)
    return events

def scrape():
    all_events = []
    now = datetime.now(); cutoff = now + timedelta(days=30)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-setuid-sandbox'])
        ctx = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
        page = ctx.new_page()
        for path, cat in _CATEGORIES:
            all_events.extend(_scrape_category(page, f'https://tkt.ge/{path}', cat, now, cutoff, _BUDGET.get(cat,30)))
        browser.close()
    print(f'Done: {len(all_events)} sessions', file=sys.stderr)
    return all_events

if __name__ == '__main__':
    try:
        sys.stdout.buffer.write(json.dumps(scrape(), ensure_ascii=False).encode('utf-8'))
        sys.stdout.buffer.flush()
    except Exception as e:
        print(f'Fatal: {e}', file=sys.stderr); sys.exit(1)