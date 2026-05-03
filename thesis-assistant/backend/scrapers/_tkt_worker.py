#!/usr/bin/env python
# backend/scrapers/_tkt_worker.py
"""
Standalone TKT.ge scraper using sync_playwright.
No asyncio, no event loop, no Windows compatibility issues.

Output: writes a UTF-8 encoded JSON array to stdout.buffer (raw bytes).
        Do NOT use print() for the result — Windows cp1252 will corrupt Georgian.
Errors: printed to stderr.
"""

import json
import sys
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

_GEORGIAN_MONTHS = {
    "იან": 1,  "თებ": 2,  "მარ": 3,  "აპრ": 4,
    "მაი": 5,  "ივნ": 6,  "ივლ": 7,  "აგვ": 8,
    "სექ": 9,  "ოქტ": 10, "ნოე": 11, "დეკ": 12,
}


def _parse_date(date_str: str) -> datetime | None:
    date_str = date_str.split("-")[0].strip()
    parts = date_str.split()
    if len(parts) < 2:
        return None
    try:
        day   = int(parts[0])
        month = _GEORGIAN_MONTHS.get(parts[1][:3])
        if not month:
            return None
        year = datetime.now().year
        dt   = datetime(year, month, day)
        if dt < datetime.now() - timedelta(days=1):
            dt = datetime(year + 1, month, day)
        return dt
    except (ValueError, TypeError):
        return None


def scrape() -> list[dict]:
    concerts: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        print("Navigating to TKT.ge ...", file=sys.stderr)
        try:
            page.goto(
                "https://tkt.ge/concerts",
                wait_until="networkidle",
                timeout=20_000,
            )
            page.wait_for_selector('[data-testid="event-item"]', timeout=15_000)
        except PWTimeout:
            print("Timeout: no event cards found", file=sys.stderr)
            browser.close()
            return concerts

        cards  = page.query_selector_all('[data-testid="event-item"]')
        now    = datetime.now()
        cutoff = now + timedelta(days=30)
        print(f"Found {len(cards)} cards", file=sys.stderr)

        for card in cards:
            try:
                name_el    = card.query_selector('[data-testid="title"]')
                venue_el   = card.query_selector('[data-testid="location"]')
                date_el    = card.query_selector('[data-testid="floating-date"]')
                link_el    = card.query_selector('a')
                price_el   = card.query_selector('span.text-\\[\\#0F78FF\\]')
                soldout_el = card.query_selector('button.bg-\\[\\#E1000F\\]')
                time_el    = card.query_selector('p[title*=":"]')

                date_text = (
                    date_el.inner_text().replace("\n", " ").strip()
                    if date_el else ""
                )
                parsed = _parse_date(date_text)
                if parsed is None or not (now <= parsed <= cutoff):
                    continue

                # Price: sold out > paid > free
                if soldout_el:
                    price_value = "გაყიდულია"
                elif price_el:
                    price_value = price_el.inner_text().strip()
                else:
                    price_value = "უფასო"

                # Time: extract clock from "სამშაბათი, 19:00" → "19:00"
                time_raw = time_el.get_attribute("title").strip() if time_el else ""
                if ", " in time_raw:
                    time_value = time_raw.split(", ", 1)[1]
                elif time_raw:
                    time_value = time_raw
                else:
                    time_value = "N/A"

                concerts.append({
                    "name":  name_el.inner_text().strip()  if name_el  else "N/A",
                    "venue": venue_el.inner_text().strip() if venue_el else "N/A",
                    "price": price_value,
                    "date":  date_text,
                    "time":  time_value,
                    "url": (
                        "https://tkt.ge" + (link_el.get_attribute("href") or "")
                        if link_el else "N/A"
                    ),
                })
            except Exception as e:
                print(f"Skipped card: {e}", file=sys.stderr)

        browser.close()

    print(f"Done: {len(concerts)} concerts", file=sys.stderr)
    return concerts


if __name__ == "__main__":
    try:
        results = scrape()
        # Write raw UTF-8 bytes — never use print() here.
        # Windows defaults stdout to cp1252 which cannot encode Georgian.
        # stdout.buffer bypasses the codec layer entirely.
        sys.stdout.buffer.write(json.dumps(results, ensure_ascii=False).encode("utf-8"))
        sys.stdout.buffer.flush()
    except Exception as e:
        print(f"Worker fatal error: {e}", file=sys.stderr)
        sys.exit(1)