# backend/database.py
"""
SQLite caching layer.
- Concerts: refreshed from TKT every CONCERT_CACHE_HOURS
- Bus routes: loaded from CSV once per BUS_CACHE_HOURS (data doesn't change daily)
"""

import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager

from config import DB_PATH, CONCERT_CACHE_HOURS, BUS_CACHE_HOURS


# ── Connection helper ─────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS concerts (
                id          INTEGER PRIMARY KEY,
                data        TEXT    NOT NULL,
                scraped_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS bus_routes (
                id           INTEGER PRIMARY KEY,
                route_number TEXT    NOT NULL UNIQUE,
                data         TEXT    NOT NULL,
                loaded_at    TEXT    NOT NULL
            );
        """)


# ── Concerts ──────────────────────────────────────────────────────────────────

def save_concerts(concerts: list) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM concerts")
        conn.execute(
            "INSERT INTO concerts (data, scraped_at) VALUES (?, ?)",
            (json.dumps(concerts, ensure_ascii=False), datetime.now().isoformat()),
        )


def load_concerts() -> tuple[list | None, str | None]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data, scraped_at FROM concerts LIMIT 1"
        ).fetchone()
    if not row:
        return None, None
    return json.loads(row["data"]), row["scraped_at"]


def concerts_cache_fresh() -> bool:
    _, scraped_at = load_concerts()
    if not scraped_at:
        return False
    age = (datetime.now() - datetime.fromisoformat(scraped_at)).total_seconds()
    return age < CONCERT_CACHE_HOURS * 3600


# ── Bus routes ────────────────────────────────────────────────────────────────

def save_bus_route(route_number: str, stops: list) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO bus_routes (route_number, data, loaded_at)
            VALUES (?, ?, ?)
            ON CONFLICT(route_number) DO UPDATE SET
                data      = excluded.data,
                loaded_at = excluded.loaded_at
            """,
            (route_number, json.dumps(stops, ensure_ascii=False), datetime.now().isoformat()),
        )


def load_bus_route(route_number: str) -> tuple[list | None, str | None]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data, loaded_at FROM bus_routes WHERE route_number = ?",
            (route_number,),
        ).fetchone()
    if not row:
        return None, None
    return json.loads(row["data"]), row["loaded_at"]


def bus_route_cache_fresh(route_number: str) -> bool:
    _, loaded_at = load_bus_route(route_number)
    if not loaded_at:
        return False
    age = (datetime.now() - datetime.fromisoformat(loaded_at)).total_seconds()
    return age < BUS_CACHE_HOURS * 3600


def get_all_cached_routes() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT route_number FROM bus_routes").fetchall()
    return [r["route_number"] for r in rows]


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    print(f"Database ready at: {DB_PATH}")