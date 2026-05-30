# backend/merge_ttc.py
"""
Merges stop names + schedules into ttc_final.csv.

Input files:
  ttc_stop_names.csv    — columns: route_number, stop_index, stop_name
                          (produced by the fixed scraper script)
  ttc_schedules_full.csv — columns: route_number, stop_index, hour, minutes
                          (produced by scrapeComplete() — has real data for 7 routes)

Output:
  ttc_final.csv — columns: route_number, stop_index, stop_name, hour, minutes

Routes 299/300/301 had their schedules blocked on the TTC site.
They get a fallback every-10-minute pattern.  This is documented in the thesis
as a known data gap for the Vake corridor routes.
"""

import csv
import os
from collections import defaultdict

BACKEND       = os.path.dirname(os.path.abspath(__file__))
STOPS_FILE    = os.path.join(BACKEND, "ttc_stop_names.csv")       # new format
SCHEDULE_FILE = os.path.join(BACKEND, "ttc_schedules_full.csv")   # unchanged
OUTPUT        = os.path.join(BACKEND, "ttc_final.csv")

# ── Load stop names ───────────────────────────────────────────────────────────
# Format: route_number, stop_index, stop_name
stops: dict[str, dict[str, str]] = defaultdict(dict)   # {route: {idx: name}}

with open(STOPS_FILE, "r", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for row in reader:
        route = row["route_number"].strip()
        idx   = row["stop_index"].strip()
        name  = row["stop_name"].strip()
        stops[route][idx] = name

print("Stop names loaded:")
for route, stop_dict in sorted(stops.items()):
    indices = sorted(stop_dict.keys(), key=lambda x: int(x))
    first = stop_dict[indices[0]] if indices else "?"
    last  = stop_dict[indices[-1]] if indices else "?"
    print(f"  Route {route}: {len(stop_dict)} stops | {first[:35]} ... {last[:35]}")

# ── Load schedules ────────────────────────────────────────────────────────────
schedules: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

with open(SCHEDULE_FILE, "r", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        route = row["route_number"].strip()
        idx   = row["stop_index"].strip()
        schedules[route][idx].append((row["hour"].strip(), row["minutes"].strip()))

print("\nSchedule data loaded:")
for route, s in sorted(schedules.items()):
    print(f"  Route {route}: {sum(len(v) for v in s.values())} rows across {len(s)} stops")

# ── Fallback for routes with no real schedule data ────────────────────────────
# 299/300/301 (Vake corridor) were blocked on the TTC website.
# Every 10 minutes, 06:00–22:00 is a reasonable approximation.
FALLBACK = [(str(h), "00 10 20 30 40 50") for h in range(6, 23)]

blocked_routes = set(stops.keys()) - set(schedules.keys())
if blocked_routes:
    print(f"\nRoutes using fallback schedule (no real data available): {sorted(blocked_routes)}")

# ── Write output ──────────────────────────────────────────────────────────────
written = 0
with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["route_number", "stop_index", "stop_name", "hour", "minutes"])

    for route in sorted(stops.keys()):
        stop_dict = stops[route]
        for idx in sorted(stop_dict.keys(), key=lambda x: int(x)):
            stop_name = stop_dict[idx]
            if route in schedules and idx in schedules[route]:
                times = schedules[route][idx]
            else:
                times = FALLBACK
            for hour, mins in times:
                writer.writerow([route, idx, stop_name, hour, mins])
                written += 1

print(f"\nWrote {written} rows to {OUTPUT}")
print("Routes in output:", sorted(stops.keys()))
print("\nNext step: delete backend/data.db and restart the server.")