# backend/check_bus_data.py
# Run this from the backend/ folder: python check_bus_data.py
# It tells you exactly what's in your CSVs and what the real problem is.

import csv
from collections import defaultdict
from pathlib import Path

SCHEDULES = Path("ttc_schedules.csv")       # stop names per route
FULL      = Path("ttc_schedules_full.csv")  # actual timetables

# ── 1. Which routes have stop name data? ─────────────────────────────────────
print("=== ROUTES IN ttc_schedules.csv ===")
route_stops = defaultdict(list)
with open(SCHEDULES, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        route_stops[row["route_number"].strip()].append(row["stop_name"].strip())

for route, stops in sorted(route_stops.items()):
    print(f"  Route {route}: {len(stops)} stops  |  first: {stops[0][:40]}")

# ── 2. Which routes have timetable data? ─────────────────────────────────────
print("\n=== ROUTES IN ttc_schedules_full.csv ===")
route_schedule_rows = defaultdict(int)
with open(FULL, encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        route_schedule_rows[row["route_number"].strip()] += 1

for route, count in sorted(route_schedule_rows.items()):
    print(f"  Route {route}: {count} schedule rows")

# ── 3. Which routes are MISSING timetable data? ──────────────────────────────
print("\n=== ROUTES WITH STOPS BUT NO TIMETABLE (will use fallback) ===")
missing = set(route_stops.keys()) - set(route_schedule_rows.keys())
if missing:
    for r in sorted(missing):
        print(f"  Route {r} — no real schedule, gets fallback every-10-min pattern")
else:
    print("  (none — all routes have timetable data)")

# ── 4. Check if any routes share identical stop lists ────────────────────────
print("\n=== ROUTES WITH IDENTICAL STOP LISTS ===")
stop_fingerprints = defaultdict(list)
for route, stops in route_stops.items():
    fp = tuple(stops)
    stop_fingerprints[fp].append(route)

for fp, routes in stop_fingerprints.items():
    if len(routes) > 1:
        print(f"  Routes {routes} share the same {len(fp)} stops")
        print(f"    First stop:  {fp[0][:50]}")
        print(f"    Last stop:   {fp[-1][:50]}")

print("\n=== DONE ===")
print("If routes share stops: that reflects the real Tbilisi corridor structure.")
print("If routes are MISSING timetable data: they get a dummy every-10-min schedule.")
print("Delete data.db and restart after fixing CSVs.")