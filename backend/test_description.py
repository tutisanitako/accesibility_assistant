#!/usr/bin/env python
"""
Run from backend/: python test_description.py
Tests description scraping from TKT.ge show page.
"""
import sys, re
from playwright.sync_api import sync_playwright

URL = 'https://tkt.ge/show/7294/rtsyili-da-chianchvela'

def scrape(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox','--disable-setuid-sandbox'])
        page = browser.new_page(user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        ))
        print(f'Loading {url}...', flush=True)
        page.goto(url, wait_until='domcontentloaded', timeout=18_000)

        # Wait for #event-description
        try:
            page.wait_for_selector('#event-description', timeout=6_000)
            print('✓ #event-description found', flush=True)
        except Exception:
            print('✗ #event-description NOT found within 6s, waiting 3s more...', flush=True)
            page.wait_for_timeout(3000)

        # Check if element exists
        el = page.query_selector('#event-description')
        print(f'#event-description element: {el}', flush=True)

        if el:
            # Get raw inner HTML
            html = el.inner_html()
            print(f'\n--- Raw innerHTML ({len(html)} chars) ---')
            print(html[:1000])

            # Get text via JS
            desc = page.evaluate('''() => {
                const container = document.getElementById('event-description');
                if (!container) return 'NO CONTAINER';
                const paras = [...container.querySelectorAll('p, span')];
                const texts = paras
                    .map(el => el.textContent.trim())
                    .filter(t => t.length > 20 && /[\u10D0-\u10FF]{3,}/.test(t) && !t.startsWith('http'));
                const seen = new Set();
                const unique = [];
                for (const t of texts) {
                    const key = t.substring(0, 40);
                    if (!seen.has(key)) { seen.add(key); unique.push(t); }
                    if (unique.length >= 8) break;
                }
                return unique.join('\\n---\\n');
            }''')
            print(f'\n--- Extracted text ---')
            print(desc)
        else:
            # Dump all IDs on the page
            ids = page.evaluate('''() => {
                return [...document.querySelectorAll('[id]')].map(e => e.id).filter(Boolean);
            }''')
            print(f'\nAll element IDs on page: {ids}')

            # Try all p tags
            all_p = page.evaluate('''() => {
                return [...document.querySelectorAll('p')]
                    .map(e => e.textContent.trim())
                    .filter(t => t.length > 30 && /[\u10D0-\u10FF]{3,}/.test(t))
                    .slice(0, 10);
            }''')
            print(f'\nAll <p> with Georgian text:')
            for t in all_p:
                print(f'  {t[:100]}')

        browser.close()

if __name__ == '__main__':
    url = sys.argv[1] if len(sys.argv) > 1 else URL
    scrape(url)