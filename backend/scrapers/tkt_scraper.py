# backend/scrapers/tkt_scraper.py
"""
TKT.ge concert scraper.

Key fix for 2-minute hang: get_concerts() NEVER waits for the scraper.
It always returns from cache immediately. If cache is stale, it launches
a background scrape. On first startup with empty cache, returns [] immediately
and the warm-up fills the cache within ~2 minutes in the background.
"""

import json
import logging
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path

from database import save_concerts, load_concerts, concerts_cache_fresh

log = logging.getLogger(__name__)
_WORKER = Path(__file__).parent / "_tkt_worker.py"

# Lock to prevent multiple simultaneous scrapes
_scrape_lock = threading.Lock()
_scraping = False


_GEORGIAN_MONTHS = {
    "იან":1,"თებ":2,"მარ":3,"აპრ":4,"მაი":5,"ივნ":6,
    "ივლ":7,"აგვ":8,"სექ":9,"ოქტ":10,"ნოე":11,"დეკ":12,
}


def _parse_date(date_str: str) -> datetime | None:
    date_str = date_str.strip()
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


def _filter_by_days(concerts: list[dict], days_ahead: int) -> list[dict]:
    now    = datetime.now()
    today  = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today + timedelta(days=days_ahead)
    result = []

    for c in concerts:
        date_str = c.get("date", "")
        parts    = [p.strip() for p in date_str.split(" - ")]
        start_dt = _parse_date(parts[0])
        end_dt   = _parse_date(parts[-1]) if len(parts) > 1 else start_dt

        if start_dt is None:
            continue
        if end_dt is None:
            end_dt = start_dt
        if end_dt.year < start_dt.year:
            end_dt = end_dt.replace(year=start_dt.year)

        event_end   = end_dt.replace(hour=23, minute=59)
        event_start = start_dt.replace(hour=0, minute=0)

        if event_end < now:
            continue
        if event_start > cutoff:
            continue

        # Skip today's show if time already passed
        if event_start.date() == today.date() and " - " not in date_str:
            time_str = c.get("time", "N/A")
            if time_str and time_str != "N/A":
                try:
                    h, m = map(int, time_str.split(":"))
                    if now.replace(hour=h, minute=m) <= now:
                        continue
                except ValueError:
                    pass

        result.append(c)

    return result


def _run_worker() -> list[dict]:
    """Run the scraper subprocess. Blocks until done (~2-3 min)."""
    try:
        proc = subprocess.run(
            [sys.executable, str(_WORKER)],
            capture_output=True,
            timeout=360,
        )
        stderr_text = proc.stderr.decode("utf-8", errors="replace")
        log.info("Worker stderr (last 2000): %s", stderr_text[-2000:])

        if proc.returncode != 0:
            log.error("TKT worker failed (exit %d)", proc.returncode)
            return []

        stdout_bytes = proc.stdout.strip()
        if not stdout_bytes:
            log.warning("TKT worker returned empty output")
            return []

        return json.loads(stdout_bytes.decode("utf-8"))

    except subprocess.TimeoutExpired:
        log.error("TKT worker timed out")
        return []
    except json.JSONDecodeError as e:
        log.error("TKT worker bad JSON: %s", e)
        return []
    except Exception as e:
        log.error("TKT subprocess error: %s", e)
        return []


def _scrape_in_background():
    """Launch scraper in background thread. Only one at a time."""
    global _scraping
    with _scrape_lock:
        if _scraping:
            return
        _scraping = True

    def _bg():
        global _scraping
        try:
            log.info("Background scrape starting...")
            concerts = _run_worker()
            if concerts:
                save_concerts(concerts)
                log.info("Background scrape done: %d concerts", len(concerts))
            else:
                log.warning("Background scrape returned 0 results")
        finally:
            _scraping = False

    threading.Thread(target=_bg, daemon=True, name="tkt-scrape").start()


async def get_concerts(days_ahead: int = 3) -> list[dict]:
    """
    ALWAYS returns immediately from cache.
    If cache is stale, triggers background refresh for next call.
    """
    cached, scraped_at = load_concerts()

    if cached is None:
        # No cache at all — return empty, background will fill it
        log.info("No concert cache yet — returning [] (background scrape running)")
        _scrape_in_background()
        return []

    if not concerts_cache_fresh():
        # Cache is stale — serve it anyway, refresh in background
        log.info("Concert cache stale (scraped: %s) — serving stale, refreshing", scraped_at)
        _scrape_in_background()

    return _filter_by_days(cached, days_ahead)


def warm_concert_cache() -> None:
    """Called at startup. If cache is empty or stale, start background scrape."""
    cached, _ = load_concerts()
    if cached is not None and concerts_cache_fresh():
        log.info("Concert cache fresh (%d items)", len(cached))
        return
    log.info("Concert cache needs refresh — starting background scrape")
    _scrape_in_background()