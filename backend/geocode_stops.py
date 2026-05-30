#!/usr/bin/env python
# backend/geocode_stops.py
"""
One-time script: adds lat/lng columns to ttc_final.csv using the free
Nominatim geocoder (OpenStreetMap). No API key required.

Usage (from backend/ folder):
    python geocode_stops.py

Creates ttc_final_geo.csv.  After verifying it looks correct:
    copy ttc_final_geo.csv ttc_final.csv    (Windows)
    cp   ttc_final_geo.csv ttc_final.csv    (Linux/macOS)

Then delete data.db and restart the server.

Rate limit: Nominatim requires 1 request/second max.
With ~200 unique stop names this takes about 3-4 minutes.
"""

import csv
import time
import json
import urllib.request
import urllib.parse
from pathlib import Path
from collections import OrderedDict

INPUT  = Path(__file__).parent / "ttc_final.csv"
OUTPUT = Path(__file__).parent / "ttc_final_geo.csv"

# Tbilisi bounding box — keeps Nominatim from returning wrong cities
TBILISI_VIEWBOX = "44.6,41.6,45.1,41.8"   # left,bottom,right,top (lng,lat)
TBILISI_COUNTRYCODES = "ge"

_cache: dict[str, tuple[float, float] | None] = {}


def geocode(stop_name: str) -> tuple[float, float] | None:
    """Return (lat, lng) for a Tbilisi stop name, or None if not found."""
    # Strip codes like [2293] and prefixes like მ/ს
    import re
    clean = re.sub(r'\s*\[\d+\]', '', stop_name).strip()
    clean = re.sub(r'^მ/ს\s*["\']?', '', clean).strip().strip('"\'')

    if clean in _cache:
        return _cache[clean]

    query = urllib.parse.urlencode({
        "q":            clean + ", Tbilisi",
        "format":       "json",
        "limit":        1,
        "countrycodes": TBILISI_COUNTRYCODES,
        "viewbox":      TBILISI_VIEWBOX,
        "bounded":      1,
    })
    url = f"https://nominatim.openstreetmap.org/search?{query}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "TbilisiAssistant/1.0 thesis-project"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        if data:
            result = (float(data[0]["lat"]), float(data[0]["lon"]))
            _cache[clean] = result
            return result
        else:
            print(f"  [not found] {clean!r}")
            _cache[clean] = None
            return None

    except Exception as e:
        print(f"  [error] {clean!r}: {e}")
        _cache[clean] = None
        return None


def main():
    # Read all rows
    rows = []
    with open(INPUT, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    print(f"Loaded {len(rows)} rows from {INPUT.name}")

    # Collect unique stop names per route (we geocode once per unique name)
    unique_stops: OrderedDict[str, None] = OrderedDict()
    for row in rows:
        key = (row["route_number"], row["stop_name"])
        unique_stops[key] = None

    print(f"Found {len(unique_stops)} unique (route, stop) combinations")
    print("Geocoding... (this takes 3-4 minutes, 1 request/sec)")

    coords: dict[tuple, tuple[float, float] | None] = {}
    done = 0
    for (route, stop_name) in unique_stops:
        result = geocode(stop_name)
        coords[(route, stop_name)] = result
        done += 1
        status = f"{result[0]:.5f},{result[1]:.5f}" if result else "NOT FOUND"
        print(f"  [{done}/{len(unique_stops)}] {stop_name[:40]:40s} → {status}")
        time.sleep(1.05)   # Nominatim ToS: max 1 req/sec

    # Write output with lat/lng columns
    out_fields = list(fieldnames) + ["lat", "lng"]
    found = 0
    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        for row in rows:
            key = (row["route_number"], row["stop_name"])
            coord = coords.get(key)
            if coord:
                row["lat"] = f"{coord[0]:.7f}"
                row["lng"] = f"{coord[1]:.7f}"
                found += 1
            else:
                row["lat"] = ""
                row["lng"] = ""
            writer.writerow(row)

    total = len(rows)
    print(f"\nDone. {found}/{total} rows have coordinates ({100*found//total}%)")
    print(f"Output: {OUTPUT}")
    print()
    print("Next steps:")
    print("  1. Check the output file looks correct")
    print("  2. Run: copy ttc_final_geo.csv ttc_final.csv")
    print("  3. Delete data.db")
    print("  4. Restart the server")


if __name__ == "__main__":
    main()