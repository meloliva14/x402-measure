#!/usr/bin/env python3
"""Lay the nohumans.directory control files beside our daily snapshots.

THEIRS: thirdparty/nohumans_control_*.csv, one row per host per day carrying the state
  (all_402 | all_fail | mixed) and the 402 share across every probe they ran that day. Probe
  COUNTS are deliberately absent from these files.
OURS:   snapshots/<day>/observation.json, exactly ONE probe per host per day.

WHY THE COUNTS ARE NOT NEEDED HERE. Under the model being tested, a daily sample lands somewhere
inside the day independently of what the endpoint is doing, so the chance it sees a challenge IS
the day's 402 share. Expected landings is then the sum of the per-day shares and its variance is
the sum of p(1-p). Both are functions of the share alone. Counts would only let us put an error
bar on each share itself, which is a second-order correction, and at their probe volumes a small
one. So the files as published are sufficient.

WHAT EACH CONTROL IS FOR, in their words and confirmed against their own files:
  api.onesource.io          GENERALISATION. Sole host on its domain, and its mixed days sit at
                            96 to 99.9 percent, so a daily sample lands on a challenge almost
                            always. It carries almost no power. It re-tests the unmixed agreement
                            outside the hergertsynthora fleet, which is exactly the open question.
  api.osf-master-server.com POWER. 19 mixed days spanning a wide share range. But the shape is a
                            DECLINE, not a flap: high, falling, then twelve consecutive all-fail
                            days. They said so themselves rather than letting it be discovered.
"""
import collections
import csv
import json
import math
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(BASE, "snapshots")
FILES = [
    ("api.onesource.io", "thirdparty/nohumans_control_onesource_2026-09-13.csv", "generalisation"),
    ("api.osf-master-server.com", "thirdparty/nohumans_control_osf_2026-09-13.csv", "power"),
]
SERVED = {"OK", "V1"}


def ours():
    out = collections.defaultdict(dict)
    for day in sorted(d for d in os.listdir(SNAP) if d[:2] == "20"):
        with open(os.path.join(SNAP, day, "observation.json"), encoding="utf-8") as f:
            for r in json.load(f)["observations"]:
                out[r["host"]][day] = (r.get("verdict"), str(r.get("notes") or ""))
    return out


def main() -> int:
    mine = ours()
    report = {"generated": "2026-09-13", "controls": []}

    for host, rel, role in FILES:
        rows = list(csv.DictReader(open(os.path.join(BASE, rel), encoding="utf-8")))
        recs, missing = [], []
        for r in rows:
            got = mine.get(host, {}).get(r["day"])
            if got is None:
                missing.append(r["day"])
                continue
            verdict, note = got
            recs.append(dict(day=r["day"], their_state=r["state"],
                             share=float(r["share_402"]),
                             our_verdict=verdict, our_served=verdict in SERVED,
                             our_note=note[:60]))

        shapes = collections.Counter(x["their_state"] for x in recs)
        unmixed = [x for x in recs if x["their_state"] != "mixed"]
        dis = [x for x in unmixed if x["our_served"] != (x["their_state"] == "all_402")]
        mixed = [x for x in recs if x["their_state"] == "mixed"]
        exp = sum(x["share"] for x in mixed)
        var = sum(p * (1 - p) for p in (x["share"] for x in mixed))
        sd = math.sqrt(var) if var > 0 else 0.0
        obs = sum(1 for x in mixed if x["our_served"])
        z = (obs - exp) / sd if sd > 0 else None

        print(f"\n{host}  ({role})")
        print(f"  their file: {len(rows)} days {rows[0]['day']}..{rows[-1]['day']}, {dict(shapes)}")
        print(f"  compared {len(recs)}, no snapshot of ours for {len(missing)}")
        print(f"  UNMIXED days: {len(unmixed)}, disagreements {len(dis)}")
        for x in dis:
            print(f"    {x['day']} theirs={x['their_state']:8} ours={x['our_verdict']} {x['our_note'][:44]}")
        if mixed:
            print(f"  MIXED days: {len(mixed)}, share {min(x['share'] for x in mixed)*100:.1f}"
                  f"..{max(x['share'] for x in mixed)*100:.1f}%")
            print(f"    our sample saw a challenge on {obs}; expected {exp:.2f}, sd {sd:.2f}"
                  + (f", z {z:+.2f}" if z is not None else ", sd 0 so no z"))
        report["controls"].append(dict(
            host=host, role=role, source=rel, days=len(recs), missing=missing,
            shapes=dict(shapes), unmixed=len(unmixed), unmixed_disagreements=len(dis),
            mixed=len(mixed), observed=obs, expected=round(exp, 4), sd=round(sd, 4),
            z=(round(z, 4) if z is not None else None), records=recs))

    tot_un = sum(c["unmixed"] for c in report["controls"])
    tot_dis = sum(c["unmixed_disagreements"] for c in report["controls"])
    print(f"\nACROSS BOTH CONTROLS: {tot_un - tot_dis} of {tot_un} unmixed days agree, "
          f"{tot_dis} disagreement(s)")
    out = os.path.join(BASE, "compare_controls_nohumans_2026-09-13.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print("->", os.path.basename(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
