#!/usr/bin/env python3
"""List the window each daily sweep actually ran in, read from the manifests, so an intraday
instrument can be compared INSIDE it instead of against a whole-day rate.

WHY THIS FILE EXISTS. The census is scheduled at 04:17 UTC. The scheduler has delivered that job
from half an hour to more than six hours late, so the schedule says nothing about when a day was
sampled; the manifest does, in sweep_started_utc and sweep_ended_utc. On 2026-09-13 the window
was first written up as "04:17 to 05:05 UTC" from the schedule. The manifests for that week said
08:22 to 09:36. The record beats the schedule, and this script is how the record is read.

USAGE
    python sweep_windows.py            # prints every day and writes sweep_windows_<today>.csv/.json
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(BASE, "snapshots")


def windows() -> list[dict]:
    """One row per snapshot day: start and end of the sweep in UTC, and its length in seconds."""
    rows = []
    for day in sorted(d for d in os.listdir(SNAP) if d[:2] == "20"):
        with open(os.path.join(SNAP, day, "observation.json"), encoding="utf-8") as f:
            m = json.load(f)["manifest"]
        s, e = m["sweep_started_utc"], m["sweep_ended_utc"]
        secs = (datetime.fromisoformat(e) - datetime.fromisoformat(s)).total_seconds()
        rows.append({"day": day, "sweep_started_utc": s, "sweep_ended_utc": e, "seconds": round(secs)})
    return rows


def main() -> int:
    rows = windows()
    for r in rows:
        print(f"  {r['day']}  {r['sweep_started_utc'][11:19]} to {r['sweep_ended_utc'][11:19]} UTC  ({r['seconds']} s)")
    starts = sorted(r["sweep_started_utc"][11:19] for r in rows)
    print(f"\n{len(rows)} days; earliest start {starts[0]} UTC, latest start {starts[-1]} UTC, "
          f"longest sweep {max(r['seconds'] for r in rows)} s")
    today = datetime.now(timezone.utc).date().isoformat()
    out_csv = os.path.join(BASE, f"sweep_windows_{today}.csv")
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["day", "sweep_started_utc", "sweep_ended_utc", "seconds"], lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    with open(os.path.join(BASE, f"sweep_windows_{today}.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"generated": today, "source": "snapshots/<day>/observation.json manifest.sweep_started_utc / sweep_ended_utc",
                   "note": "the census is scheduled at 04:17 UTC and delivered late by the scheduler; this is when it actually ran",
                   "days": rows}, f, indent=1)
    print("->", os.path.basename(out_csv), "and .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
