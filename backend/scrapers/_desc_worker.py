#!/usr/bin/env python
# backend/scrapers/_desc_worker.py
"""
Standalone description scraper — runs as a subprocess so Playwright works on Windows.
Usage: python _desc_worker.py <url>
Outputs JSON: {"description": "...", "credits": "..."}
"""
import json, sys, re


def scrape(url: str) -> dict:
    from playwright.sync_api import sync_playwright
    result = {'description': '', 'credits': ''}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox'],
        )
        page = browser.new_page(user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        ))
        page.goto(url, wait_until='domcontentloaded', timeout=18_000)
        try:
            page.wait_for_selector('#event-description', timeout=6_000)
        except Exception:
            page.wait_for_timeout(3000)

        data = page.evaluate('''() => {
            const container = document.getElementById('event-description');
            if (!container) return {description: '', credits: ''};

            const paras = [...container.querySelectorAll('p')];
            const descParts = [];
            const creditLines = [];

            for (const p of paras) {
                const text = p.textContent.trim();
                if (!text || text.length < 10) continue;
                // Credits section contains emoji bullets like 🎥 👨 🎼 ➡️
                if (/[🎥👨🎼💼🕺📓➡️]/.test(text) || /რეჟისორ|მხატვარ|ქორეოგრ|მონაწილ|ინსცენ/.test(text)) {
                    // Split by emoji boundaries
                    const lines = text.split(/(?=[🎥👨🎼💼🕺📓➡️])/);
                    for (const line of lines) {
                        const l = line.trim();
                        if (l.length > 3) creditLines.push(l);
                    }
                } else if (/[\u10D0-\u10FF]{4,}/.test(text)) {
                    descParts.push(text);
                }
            }

            // Also get span text for description
            const spans = [...container.querySelectorAll('p > span')];
            for (const span of spans) {
                const text = span.textContent.trim();
                if (text.length > 40 && /[\u10D0-\u10FF]{4,}/.test(text)) {
                    // Check if already included
                    if (!descParts.some(d => d.includes(text.substring(0, 30)))) {
                        descParts.push(text);
                    }
                }
            }

            return {
                description: descParts.join('\\n\\n').substring(0, 1000),
                credits: creditLines.join('\\n').substring(0, 500),
            };
        }''')

        browser.close()
        return data


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({'description': '', 'credits': ''}))
        sys.exit(0)

    url = sys.argv[1]
    try:
        result = scrape(url)
        sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
        sys.stdout.buffer.flush()
    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.stdout.buffer.write(json.dumps({'description': '', 'credits': ''}).encode('utf-8'))
        sys.stdout.buffer.flush()