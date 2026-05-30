# backend/scrapers/ttc_data.py
"""
TTC bus data layer.

The CSV was collected manually via browser DevTools — there's no live
scraper here because the transit.ttc.com.ge API blocks external requests.

This module:
  1. Reads ttc_final.csv into structured objects (once per BUS_CACHE_HOURS)
  2. Caches results in SQLite
  3. Provides query functions used by the API endpoints
"""

import csv
from collections import defaultdict
from pathlib import Path

from config import TTC_CSV_PATH
from database import (
    load_bus_route,
    save_bus_route,
    bus_route_cache_fresh,
    get_all_cached_routes,
    init_db,
)


# ── CSV loading ───────────────────────────────────────────────────────────────

def _load_csv() -> dict[str, dict[str, dict]]:
    """
    Parse ttc_final.csv into:
      { route_number: { stop_index: { name, hours: {hour: [min, ...]} } } }
    """
    if not TTC_CSV_PATH.exists():
        raise FileNotFoundError(f"TTC data file not found: {TTC_CSV_PATH}")

    data: dict[str, dict] = defaultdict(lambda: defaultdict(
        lambda: {"name": "", "schedule": defaultdict(list)}
    ))

    with open(TTC_CSV_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            route  = row["route_number"].strip()
            idx    = row["stop_index"].strip()
            name   = row["stop_name"].strip()
            hour   = row["hour"].strip()
            mins   = row["minutes"].strip().split()

            stop = data[route][idx]
            stop["name"] = name
            stop["schedule"][hour].extend(mins)

    return data


def _structure_stops(raw_stops: dict) -> list[dict]:
    """Convert the nested dict into a clean list of stop dicts."""
    stops = []
    for idx in sorted(raw_stops.keys(), key=lambda x: int(x)):
        raw = raw_stops[idx]
        schedule = [
            {"hour": int(h), "departures": sorted(set(raw["schedule"][h]))}
            for h in sorted(raw["schedule"].keys(), key=int)
        ]
        stops.append({"index": int(idx), "name": raw["name"], "schedule": schedule})
    return stops


# ── Cache population ──────────────────────────────────────────────────────────

def populate_cache_from_csv() -> list[str]:
    """
    Load all routes from CSV into SQLite.
    Called once at startup (and again if cache expires).
    Returns list of route numbers loaded.
    """
    init_db()
    raw = _load_csv()
    loaded = []
    for route_number, stops_raw in raw.items():
        stops = _structure_stops(stops_raw)
        save_bus_route(route_number, stops)
        loaded.append(route_number)
    return loaded


# ── Public query API ──────────────────────────────────────────────────────────

def get_route(route_number: str) -> dict | None:
    """
    Return a route dict with all stops and schedules.
    Populates cache from CSV if needed.
    """
    route_number = route_number.strip()

    if not bus_route_cache_fresh(route_number):
        populate_cache_from_csv()

    stops, _ = load_bus_route(route_number)
    if stops is None:
        return None
    return {"route_number": route_number, "stops": stops}


def get_stop_schedule(route_number: str, stop_name_query: str) -> list[dict]:
    """
    Find stops whose name contains stop_name_query (case-insensitive).
    Returns a list of matching stops with their schedules.
    """
    route = get_route(route_number)
    if not route:
        return []
    query = stop_name_query.lower()
    return [s for s in route["stops"] if query in s["name"].lower()]


def search_routes_by_stop(stop_name_query: str) -> list[dict]:
    """
    Search all routes for a stop name.
    Returns [{ route_number, stop_name, stop_index }, ...]
    """
    # Make sure cache is populated
    if not get_all_cached_routes():
        populate_cache_from_csv()

    results = []
    for route_number in get_all_cached_routes():
        stops, _ = load_bus_route(route_number)
        if not stops:
            continue
        query = stop_name_query.lower()
        for stop in stops:
            if query in stop["name"].lower():
                results.append({
                    "route_number": route_number,
                    "stop_index":   stop["index"],
                    "stop_name":    stop["name"],
                })
    return results


def get_available_routes() -> list[str]:
    """Return all route numbers that have data."""
    if not get_all_cached_routes():
        populate_cache_from_csv()
    return sorted(get_all_cached_routes(), key=lambda x: int(x))


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    routes = populate_cache_from_csv()
    print(f"Loaded {len(routes)} routes: {routes}")

    # Quick sanity check
    route = get_route("305")
    if route:
        print(f"\nRoute 305: {len(route['stops'])} stops")
        first = route["stops"][0]
        print(f"First stop: {first['name']}")
        print(f"First hour schedule: {first['schedule'][0]}")