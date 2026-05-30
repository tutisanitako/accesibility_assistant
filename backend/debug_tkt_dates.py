#!/usr/bin/env python
"""
Run from backend/: python debug_tkt_dates.py
Finds exactly where Georgian session dates live in the TKT.ge HTML.
"""
import re, json, sys
from playwright.sync_api import sync_playwright

TEST_URL = sys.argv[1] if len(sys.argv) > 1 else 'https://tkt.ge/show/32403/gedebis-tba'

GEO_MONTH_PAT = r'\d{1,2}\s+(?:იან|თებ|მარ|აპრ|მაი|ივნ|ივლ|აგვ|სექ|ოქტ|ნოე|დეკ)'

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        ctx = browser.new_context(user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        ))
        page = ctx.new_page()
        page.goto(TEST_URL, wait_until='domcontentloaded', timeout=20_000)
        page.wait_for_timeout(3000)
        html = page.content()
        browser.close()

    # ── 1. Where are the Georgian dates in raw HTML? ──────────────────────────
    print('=== GEORGIAN DATE OCCURRENCES IN HTML ===')
    for m in re.finditer(GEO_MONTH_PAT, html):
        start = max(0, m.start() - 120)
        end   = min(len(html), m.end() + 120)
        print(f'\n  Date: {m.group()!r}  pos={m.start()}')
        snippet = html[start:end].replace('\n', ' ')
        print(f'  Context: ...{snippet}...')

    # ── 2. Extract and dump __NEXT_DATA__ structure ───────────────────────────
    print('\n\n=== __NEXT_DATA__ STRUCTURE ===')
    nd_m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if nd_m:
        try:
            nd = json.loads(nd_m.group(1))
            # Find all strings that look like dates (Georgian or ISO)
            date_strings = []
            def walk(obj, path=''):
                if isinstance(obj, str):
                    if re.search(GEO_MONTH_PAT, obj) or re.search(r'\d{4}-\d{2}-\d{2}', obj):
                        date_strings.append((path, obj[:120]))
                elif isinstance(obj, dict):
                    for k, v in obj.items():
                        walk(v, f'{path}.{k}')
                elif isinstance(obj, list):
                    for i, v in enumerate(obj[:20]):
                        walk(v, f'{path}[{i}]')
            walk(nd)
            if date_strings:
                print('Date-like strings found in __NEXT_DATA__:')
                for path, val in date_strings[:30]:
                    print(f'  {path}: {val!r}')
            else:
                print('No date strings found in __NEXT_DATA__')
                # Print top-level keys to understand structure
                def show_keys(obj, depth=0, max_depth=2):
                    if depth > max_depth: return
                    if isinstance(obj, dict):
                        for k, v in list(obj.items())[:12]:
                            print('  ' * (depth+1) + f'{k}: {type(v).__name__}' +
                                  (f' = {str(v)[:60]}' if not isinstance(v, (dict,list)) else ''))
                            show_keys(v, depth+1, max_depth)
                    elif isinstance(obj, list) and obj:
                        print('  ' * (depth+1) + f'[list of {len(obj)}]')
                        show_keys(obj[0], depth+1, max_depth)
                show_keys(nd)
        except json.JSONDecodeError as e:
            print(f'JSON parse error: {e}')
    else:
        print('No __NEXT_DATA__ found')

    # ── 3. Look for session/date data in any JSON blobs in the page ───────────
    print('\n\n=== JSON BLOBS WITH DATE DATA ===')
    # Find all JSON-like objects/arrays embedded in scripts
    json_blobs = re.findall(r'(?:=|:)\s*(\[[\s\S]{20,2000}?\]|\{[\s\S]{20,2000}?\})\s*[;,\n]', html)
    found = 0
    for blob in json_blobs:
        if re.search(GEO_MONTH_PAT, blob) or re.search(r'"date"', blob):
            try:
                obj = json.loads(blob)
                print(f'\nJSON blob with date: {str(obj)[:300]}')
                found += 1
                if found >= 5:
                    break
            except Exception:
                # Not valid JSON on its own, show raw
                if re.search(GEO_MONTH_PAT, blob):
                    print(f'\nRaw blob with Georgian date: {blob[:300]}')
                    found += 1
                    if found >= 5:
                        break

    # ── 4. Check what the calendar/session UI looks like after hydration ───────
    print('\n\n=== DOM: elements containing Georgian month names ===')
    # Re-open with playwright to query DOM
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
        ctx = browser.new_context(user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        ))
        page = ctx.new_page()
        page.goto(TEST_URL, wait_until='domcontentloaded', timeout=20_000)
        page.wait_for_timeout(3000)

        # Get all text nodes containing Georgian month names
        results = page.evaluate('''() => {
            const months = ["იან","თებ","მარ","აპრ","მაი","ივნ","ივლ","აგვ","სექ","ოქტ","ნოე","დეკ"];
            const found = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.children.length === 0) {  // leaf nodes only
                    const t = el.textContent.trim();
                    if (months.some(m => t.includes(m)) && t.length < 200) {
                        found.push({
                            tag: el.tagName,
                            text: t,
                            class: el.className.substring(0, 80),
                            id: el.id,
                            dataAttrs: Object.fromEntries(
                                [...el.attributes]
                                .filter(a => a.name.startsWith('data-'))
                                .map(a => [a.name, a.value.substring(0,60)])
                            )
                        });
                    }
                }
            });
            return found.slice(0, 30);
        }''')

        print(f'Found {len(results)} leaf DOM elements with Georgian month names:')
        for r in results:
            print(f"  <{r['tag']} class={r['class']!r:.60} id={r['id']!r}>")
            print(f"    text: {r['text']!r}")
            if r['dataAttrs']:
                print(f"    data-attrs: {r['dataAttrs']}")

        browser.close()

    print('\nDone.')

if __name__ == '__main__':
    main()