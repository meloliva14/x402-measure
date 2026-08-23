#!/usr/bin/env python3
"""Count X -> UNREACHABLE -> X flaps in the observation series.

Why this exists
---------------
A failed fetch can only ever move a host toward UNREACHABLE, never toward OK. That makes
transport failure a ONE-DIRECTIONAL error: it can invent verdict transitions but never hide
them. A host that reads X on Monday, UNREACHABLE on Tuesday and X again on Wednesday has not
changed state at all, yet a naive day-over-day diff mints TWO transitions from it, one into
UNREACHABLE and one back out, landing in two different published windows.

What this can and cannot tell you
---------------------------------
The X -> UNREACHABLE -> X pattern is equally consistent with two causes:

  (a) the prober transiently failed, and
  (b) the host was genuinely down at the instant of the probe and up either side of it.

THIS SCRIPT CANNOT DISTINGUISH THEM, and does not try. The correction it supports does not
depend on the cause: under either reading the host holds the same verdict on both sides of
the gap, so counting the pair as two state changes is wrong either way. Cause matters for
whose fault it is; it does not matter for whether the transition is real.

The count is a LOWER BOUND on the false transitions in the series. Not detected:
  - a gap two or more days wide (X -> UN -> UN -> X)
  - a flap on the first or last day of the series, which has no bracketing day
  - a flap that straddles a genuine state change (X -> UN -> Y)

Reproduce:  python flap_census.py           (writes flap_census.json)
"""
from __future__ import annotations

import glob
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOTS = os.path.join(HERE, "snapshots")


def load_series() -> dict[str, dict[str, str]]:
    """{date: {host: verdict}} for every snapshot that carries an observation."""
    series = {}
    for path in sorted(glob.glob(os.path.join(SNAPSHOTS, "2026-*"))):
        obs = os.path.join(path, "observation.json")
        if not os.path.isfile(obs):
            continue
        with open(obs, encoding="utf-8") as fh:
            doc = json.load(fh)
        series[os.path.basename(path)] = {
            r["host"]: r["verdict"] for r in doc.get("observations", [])
        }
    return series


def find_flaps(series: dict[str, dict[str, str]]) -> list[dict]:
    """Every host that read UNREACHABLE on day D and the SAME other verdict on D-1 and D+1."""
    days = sorted(series)
    flaps = []
    for i in range(1, len(days) - 1):
        prev, day, nxt = days[i - 1], days[i], days[i + 1]
        for host, verdict in series[day].items():
            if verdict != "UNREACHABLE":
                continue
            before = series[prev].get(host)
            after = series[nxt].get(host)
            if before is None or after is None:
                continue  # host not in the cohort on both sides; cannot judge
            if before == "UNREACHABLE" or before != after:
                continue
            flaps.append({"date": day, "host": host, "verdict": before,
                          "window_in": f"{prev}->{day}", "window_out": f"{day}->{nxt}"})
    return flaps


def transitions(series: dict[str, dict[str, str]], a: str, b: str) -> list[tuple[str, str, str]]:
    """Hosts present both days whose verdict differs."""
    A, B = series[a], series[b]
    return sorted((h, A[h], B[h]) for h in A if h in B and A[h] != B[h])


def main() -> None:
    series = load_series()
    days = sorted(series)
    flaps = find_flaps(series)

    per_window = []
    for i in range(1, len(days)):
        a, b = days[i - 1], days[i]
        moved = transitions(series, a, b)
        involving_unreachable = [t for t in moved if "UNREACHABLE" in (t[1], t[2])]
        # Transitions this window contributed by a detected flap, either leg.
        flap_hosts_in = {f["host"] for f in flaps if f["window_in"] == f"{a}->{b}"}
        flap_hosts_out = {f["host"] for f in flaps if f["window_out"] == f"{a}->{b}"}
        from_flap = [t for t in moved if t[0] in flap_hosts_in or t[0] in flap_hosts_out]
        per_window.append({
            "window": f"{a}->{b}",
            "raw": len(moved),
            "from_detected_flap": len(from_flap),
            "involving_unreachable": len(involving_unreachable),
            "excluding_unreachable": len(moved) - len(involving_unreachable),
        })

    by_date = Counter(f["date"] for f in flaps)
    out = {
        "schema": "x402-measure/flap-census/1",
        "series": {"first": days[0], "last": days[-1], "days": len(days)},
        "definition": "host reads UNREACHABLE on day D and the same non-UNREACHABLE verdict "
                      "on D-1 and D+1; each such flap mints two transitions that are not "
                      "state changes, one in each adjacent window",
        "cause_is_not_determined": "the pattern is equally consistent with a transient prober "
                                   "failure and with the host being down only at the probe "
                                   "instant; the transition is unreal under either reading",
        "is_a_lower_bound": "gaps two or more days wide, flaps on the first or last day, and "
                            "flaps straddling a real state change are all undetected",
        "flap_events": len(flaps),
        "distinct_hosts": len({f["host"] for f in flaps}),
        "false_transitions_minted": len(flaps) * 2,
        "worst_day": {"date": by_date.most_common(1)[0][0],
                      "events": by_date.most_common(1)[0][1]} if flaps else None,
        "per_window": per_window,
        "flaps": flaps,
    }

    path = os.path.join(HERE, "flap_census.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=False)
        fh.write("\n")

    print(f"series {days[0]} .. {days[-1]}  ({len(days)} days)")
    print(f"flap events            {out['flap_events']}")
    print(f"distinct hosts         {out['distinct_hosts']}")
    print(f"false transitions      {out['false_transitions_minted']}  (lower bound)")
    if out["worst_day"]:
        print(f"worst single day       {out['worst_day']['date']}  "
              f"{out['worst_day']['events']} events")
    print()
    print(f"  {'window':<24}{'raw':>6}{'from flap':>11}{'incl UNREACH':>14}{'excl UNREACH':>14}")
    for w in per_window:
        print(f"  {w['window']:<24}{w['raw']:>6}{w['from_detected_flap']:>11}"
              f"{w['involving_unreachable']:>14}{w['excluding_unreachable']:>14}")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
