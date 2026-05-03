# backend/scrapers/tkt_scraper.py
"""
TKT.ge concert scraper.

Windows problem: FastAPI's uvicorn uses ProactorEventLoop. Playwright cannot
spawn subprocesses on ProactorEventLoop — even in a thread with its own loop,
Playwright's internal connection code inherits the wrong loop type.

Solution: run the Playwright scrape in a completely separate Python process
(_tkt_worker.py). That process starts fresh with SelectorEventLoop and works.
Results come back over stdout as raw UTF-8 bytes (not text) to avoid Windows
cp1252 codec errors with Georgian characters.
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


# ── Date helpers ──────────────────────────────────────────────────────────────

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


def _filter_by_days(concerts: list[dict], days_ahead: int) -> list[dict]:
    """
    Return concerts happening from NOW until days_ahead days from today.
    - Future dates: always included
    - Today's events: included only if the time hasn't passed yet (or time is unknown)
    - Past events: excluded
    """
    now    = datetime.now()
    today  = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = today + timedelta(days=days_ahead)
    result = []

    for c in concerts:
        parsed = _parse_date(c.get("date", ""))
        if parsed is None:
            continue

        event_day = parsed.replace(hour=0, minute=0, second=0, microsecond=0)

        # Outside the requested window
        if not (today <= event_day <= cutoff):
            continue

        # For today's events, check if the time has already passed
        if event_day == today:
            time_str = c.get("time", "N/A")
            if time_str and time_str != "N/A":
                try:
                    h, m = map(int, time_str.split(":"))
                    event_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    if event_dt <= now:
                        continue   # already started/passed — skip
                except ValueError:
                    pass  # can't parse time — include it to be safe
            # time is N/A — include it (we don't know when it starts)

        result.append(c)

    return result


# ── Subprocess runner ─────────────────────────────────────────────────────────

def _run_worker() -> list[dict]:
    """
    Launch _tkt_worker.py as a fresh Python process.

    IMPORTANT: do NOT pass text=True or encoding= to subprocess.run.
    The worker writes UTF-8 bytes directly to stdout.buffer to bypass
    Windows' cp1252 default codec. We read raw bytes here and decode
    manually — this is the only reliable way to handle Georgian on Windows.
    """
    try:
        proc = subprocess.run(
            [sys.executable, str(_WORKER)],
            capture_output=True,   # returns bytes, not str
            timeout=90,
        )

        stderr_text = proc.stderr.decode("utf-8", errors="replace")
        log.info("Worker stderr: %s", stderr_text[-2000:])

        if proc.returncode != 0:
            log.error("TKT worker failed (exit %d)", proc.returncode)
            return []

        stdout_bytes = proc.stdout.strip()
        if not stdout_bytes:
            log.warning("TKT worker returned empty output")
            return []

        return json.loads(stdout_bytes.decode("utf-8"))

    except subprocess.TimeoutExpired:
        log.error("TKT worker timed out after 90 s")
        return []
    except json.JSONDecodeError as e:
        log.error("TKT worker output not valid JSON: %s", e)
        return []
    except Exception as e:
        log.error("TKT subprocess error: %s", e)
        return []


# ── Public API ────────────────────────────────────────────────────────────────

async def get_concerts(days_ahead: int = 3) -> list[dict]:
    cached, _ = load_concerts()
    if cached is not None and concerts_cache_fresh():
        return _filter_by_days(cached, days_ahead)

    log.info("Concert cache stale — launching scraper subprocess ...")
    fresh = _run_worker()

    if fresh:
        save_concerts(fresh)
        log.info("TKT cache updated: %d concerts", len(fresh))
        return _filter_by_days(fresh, days_ahead)

    log.warning("Scrape returned 0 results — serving stale cache")
    return _filter_by_days(cached or [], days_ahead)


def warm_concert_cache() -> None:
    """Non-blocking background warm-up — call once at startup."""
    cached, _ = load_concerts()
    if cached is not None and concerts_cache_fresh():
        log.info("Concert cache already fresh (%d items)", len(cached))
        return

    def _bg():
        log.info("Background concert warm-up starting ...")
        concerts = _run_worker()
        if concerts:
            save_concerts(concerts)
            log.info("Warm-up done: %d concerts cached", len(concerts))
        else:
            log.warning("Warm-up: scraper returned 0 results")

    threading.Thread(target=_bg, daemon=True, name="tkt-warmup").start()


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    all_concerts = _run_worker()
    filtered = _filter_by_days(all_concerts, days)
    print(f"Scraped {len(all_concerts)} total, {len(filtered)} within {days} days:")
    for c in filtered:
        print(f"  {c['date']} | {c['name']} @ {c['venue']} — {c['price']}")