#!/usr/bin/env python
"""
Run from backend/: python debug_tkt_interact.py
Clicks through the calendar/session UI to find where individual dates load from.
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

        # ── Intercept API calls ───────────────────────────────────────────────
        api_calls = []
        def on_request(req):
            if 'api' in req.url or 'session' in req.url or 'schedule' in req.url or 'event' in req.url.lower():
                api_calls.append({'url': req.url, 'method': req.method})

        api_responses = []
        def on_response(resp):
            url = resp.url
            if ('api' in url or 'session' in url.lower() or 'schedule' in url.lower()):
                try:
                    body = resp.body()
                    if body and len(body) < 50000:
                        try:
                            data = json.loads(body)
                            api_responses.append({'url': url, 'data': data})
                        except Exception:
                            pass
                except Exception:
                    pass

        page = ctx.new_page()
        page.on('request', on_request)
        page.on('response', on_response)

        print(f'Loading: {TEST_URL}')
        page.goto(TEST_URL, wait_until='networkidle', timeout=30_000)
        page.wait_for_timeout(2000)

        # ── Print all API calls made ──────────────────────────────────────────
        print(f'\n=== API CALLS MADE ON PAGE LOAD ({len(api_calls)}) ===')
        for c in api_calls[:20]:
            print(f"  {c['method']} {c['url']}")

        print(f'\n=== API RESPONSES WITH DATA ({len(api_responses)}) ===')
        for r in api_responses[:5]:
            print(f"\n  URL: {r['url']}")
            print(f"  Data: {str(r['data'])[:400]}")

        # ── Look for a "Buy ticket" or session button ─────────────────────────
        print('\n=== LOOKING FOR BUY/SESSION BUTTONS ===')
        buy_selectors = [
            'button[data-testid*="buy"]',
            'button[data-testid*="ticket"]',
            'a[data-testid*="buy"]',
            '[data-testid*="session"]',
            'button:has-text("ბილეთის")',
            'button:has-text("შეიძინე")',
            'button:has-text("სეანსი")',
            'a:has-text("ბილეთი")',
        ]
        clicked = False
        for sel in buy_selectors:
            try:
                els = page.query_selector_all(sel)
                if els:
                    print(f'  Found {len(els)} elements matching {sel!r}')
                    for el in els[:3]:
                        try:
                            t = el.inner_text().strip()[:80]
                            print(f'    text={t!r}  class={str(el.get_attribute("class") or "")[:60]}')
                        except Exception:
                            pass
                    if not clicked:
                        try:
                            els[0].click()
                            page.wait_for_timeout(2000)
                            clicked = True
                            print(f'  >>> Clicked first element of {sel!r}')
                        except Exception as e:
                            print(f'  Click failed: {e}')
            except Exception:
                pass

        if clicked:
            html_after = page.content()
            geo_after = list(set(re.findall(GEO_MONTH_PAT, html_after)))
            iso_after = list(set(re.findall(r'\d{4}-\d{2}-\d{2}', html_after)))
            print(f'\nAfter click — Georgian dates: {geo_after}')
            print(f'After click — ISO dates: {iso_after}')

            # Check new API calls
            print(f'\nNew API calls after click ({len(api_calls)}) total:')
            for c in api_calls[-10:]:
                print(f"  {c['method']} {c['url']}")

            print(f'\nNew API responses:')
            for r in api_responses[-5:]:
                print(f"\n  URL: {r['url']}")
                print(f"  Data: {str(r['data'])[:600]}")

        # ── Try scrolling to find lazy-loaded content ─────────────────────────
        print('\n=== CHECKING AFTER SCROLL ===')
        page.evaluate('window.scrollTo(0, document.body.scrollHeight / 2)')
        page.wait_for_timeout(2000)

        html_scroll = page.content()
        geo_scroll = list(set(re.findall(GEO_MONTH_PAT, html_scroll)))
        print(f'After scroll — Georgian dates: {geo_scroll}')

        # ── Try longer wait ───────────────────────────────────────────────────
        print('\n=== CHECKING AFTER 8s TOTAL WAIT ===')
        page.wait_for_timeout(5000)
        html_final = page.content()
        geo_final = list(set(re.findall(GEO_MONTH_PAT, html_final)))
        iso_final = list(set(re.findall(r'\d{4}-\d{2}-\d{2}', html_final)))
        print(f'Final Georgian dates: {geo_final}')
        print(f'Final ISO dates: {iso_final}')

        # Print all network requests made
        print(f'\n=== ALL REQUESTS TO tkt.ge API ({len(api_calls)}) ===')
        for c in api_calls:
            if 'tkt.ge' in c['url']:
                print(f"  {c['method']} {c['url'][:120]}")

        browser.close()

    print('\nDone.')

if __name__ == '__main__':
    main()