#!/usr/bin/env python
"""
Run from backend/: python debug_tkt_page.py
This fetches ONE TKT.ge show page and tells us exactly what date data is available,
so we can fix the scraper correctly without guessing.

Usage: python debug_tkt_page.py [optional-show-url]
"""

import re
import sys
import json
from playwright.sync_api import sync_playwright

# Use a show that you KNOW has upcoming dates
TEST_URL = sys.argv[1] if len(sys.argv) > 1 else 'https://tkt.ge/show/32403/gedebis-tba'


def main():
    print(f'Fetching: {TEST_URL}')
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox'],
        )
        context = browser.new_context(user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ))
        page = context.new_page()
        page.goto(TEST_URL, wait_until='domcontentloaded', timeout=20_000)
        page.wait_for_timeout(3000)  # let React hydrate
        html = page.content()

        print(f'\nHTML length: {len(html)} chars')
        print(f'Has __NEXT_DATA__: {"__NEXT_DATA__" in html}')
        print(f'Has __next_f: {"__next_f" in html}')

        # Check for ISO dates
        iso_dates = list(set(re.findall(r'(\d{4}-\d{2}-\d{2})', html)))
        print(f'\nISO dates found in HTML ({len(iso_dates)}): {sorted(iso_dates)[:20]}')

        # Check for Georgian month patterns
        geo_dates = re.findall(r'\d{1,2}\s+(?:იან|თებ|მარ|აპრ|მაი|ივნ|ივლ|აგვ|სექ|ოქტ|ნოე|დეკ)', html)
        print(f'\nGeorgian dates found: {geo_dates[:20]}')

        # Count RSC chunks
        rsc = re.findall(r'self\.__next_f\.push', html)
        print(f'\nRSC push calls: {len(rsc)}')

        # Show all script tag types
        scripts = re.findall(r'<script([^>]*)>', html)
        print(f'\nScript tags ({len(scripts)}):')
        for s in scripts[:15]:
            print(f'  <script{s}>')

        # Try to find any date-like DOM elements
        print('\n--- Trying DOM selectors ---')
        selectors = [
            'time', '[data-date]', '[data-testid*="date"]',
            '[class*="session"]', '[class*="Session"]',
            '[class*="calendar"]', '[class*="Calendar"]',
            '[class*="schedule"]', '[class*="Schedule"]',
            '[class*="date"]', '[class*="Date"]',
            'button', 'li',
        ]
        for sel in selectors:
            try:
                els = page.query_selector_all(sel)
                if els:
                    sample_texts = []
                    for el in els[:5]:
                        try:
                            t = el.inner_text().strip()[:60]
                            attrs = {}
                            for attr in ['datetime', 'data-date', 'class', 'data-testid']:
                                v = el.get_attribute(attr)
                                if v:
                                    attrs[attr] = v[:40]
                            if t or attrs:
                                sample_texts.append(f'text={t!r} attrs={attrs}')
                        except Exception:
                            pass
                    if sample_texts:
                        print(f'  {sel} ({len(els)} found): {sample_texts[0]}')
            except Exception:
                pass

        # Print a section of the raw HTML around any date-looking content
        print('\n--- Raw HTML around first date/session keyword ---')
        for keyword in ['session', 'Session', 'date', 'Date', 'schedule', 'Schedule', '2026', '2025']:
            idx = html.find(keyword)
            if idx != -1:
                snippet = html[max(0, idx-100):idx+300]
                print(f'\nKeyword "{keyword}" at pos {idx}:')
                print(snippet[:400])
                break

        # Save full HTML for manual inspection
        with open('debug_tkt_page.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'\nFull HTML saved to debug_tkt_page.html ({len(html)} chars)')
        print('Open it in a browser or text editor to find the date structure.')

        browser.close()


if __name__ == '__main__':
    main()