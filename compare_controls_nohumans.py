#!/usr/bin/env python3
"""Lay the nohumans.directory control files beside our daily snapshots.

THEIRS: thirdparty/nohumans_control_*.csv, one row per host per day carrying the state
  (all_402 | all_fail | mixed) and the 402 share across every probe they ran that day. Probe
  COUNTS are deliberately absent from these files.
OURS:   snapshots/<day>/observation.json, one daily sample per host: one to three
  requests (GET, POST fallback, transport retry) taken inside one window of about three
  minutes per day, at a time the scheduler sets and the manifest records (sweep_windows.py
  lists them). Called "exactly ONE probe" here until 2026-09-13; that was the defect.

WHY THEIR PROBE COUNTS ARE NOT NEEDED, AND WHAT IS. Expected landings is a function of the
day's 402 share and OUR draw count, not of how many probes THEY ran; their counts would only put
an error bar on each share, a second-order correction. What the model did need, and did not have
until 2026-09-13, is our own draw count: the probe is a GET, then a POST when the GET produced
no challenge, plus a transport retry, so one to three requests, and it runs inside one window of
about three minutes a day. The one-draw model this script first shipped with was wrong on that,
and osf showed it: 19 of 19 against an expected 12.47. landing_model.py now brackets the draw
count; the daily window needs the intraday share inside it and is stated, not corrected.

RETRACTED BY THE PUBLISHER, 2026-09-13, AFTER THIS SCRIPT FIRST RAN. jalcodev pulled the
status codes behind osf's 19 "mixed" days and reports that they are not endpoint failures:
3,008 of those probes returned HTTP 429 and 1,500 returned no status at all, which he
attributes to his own scanner's request rate rather than to the endpoint. He states the real
outage begins 2026-08-27. HIS NUMBERS AND HIS DIAGNOSIS, not measurements of mine. If he is
right, osf's 19 mixed days were not mixed, the landing test on this host has no subject, and
the z below is measuring his throttling. The figures are left standing rather than deleted
because they were published, and are labelled instead. What this census can say from its own
side: it recorded a readable 402 on all 19 of those days with no retry, and from 08-27 it has
recorded UNREACHABLE on both attempts every day for 18 consecutive days through 09-13.

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

import landing_model as lm

BASE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(BASE, "snapshots")
FILES = [
    ("api.onesource.io", "thirdparty/nohumans_control_onesource_2026-09-13.csv", "generalisation"),
    ("api.osf-master-server.com", "thirdparty/nohumans_control_osf_2026-09-13.csv", "power"),
]
SERVED = {"OK", "V1"}
# A rate-limited day is not "saw no challenge"; it is "was not assessed". Such a host-day is
# dropped from the landing test rather than counted on the wrong side of it. Both control files
# and the four-host file contain none, so no published figure moves; the guard is for the next one.
NOT_ASSESSED = {"RATE_LIMITED"}


def verdict_is_unassessed(v) -> bool:
    """A verdict the census declines to read as an answer either way."""
    return v in NOT_ASSESSED


def ours():
    out = collections.defaultdict(dict)
    for day in sorted(d for d in os.listdir(SNAP) if d[:2] == "20"):
        with open(os.path.join(SNAP, day, "observation.json"), encoding="utf-8") as f:
            for r in json.load(f)["observations"]:
                out[r["host"]][day] = (r.get("verdict"), str(r.get("notes") or ""),
                                       {"retried": bool(r.get("retried")), "probe": r.get("probe")})
    return out


def main() -> int:
    mine = ours()
    report = {
        "generated": "2026-09-13",
        "publisher_retraction_2026-09-13": {
            "host": "api.osf-master-server.com",
            "source": "jalcodev, #wg-domain-discovery, 2026-09-13",
            "claim": ("the 19 mixed days are not endpoint failures: 3,008 probes returned HTTP "
                      "429 and 1,500 returned no status at all, attributed by him to his own "
                      "scanner's request rate; the genuine outage begins 2026-08-27"),
            "status": "HIS claim about HIS instrument, carried here unverified by us",
            "effect_if_true": ("those days were not mixed, so the landing test on this host has "
                               "no subject and the z below describes his throttling"),
            "what_our_own_rows_say": ("a readable 402 on all 19 days with no retry; UNREACHABLE "
                                      "on both attempts every day from 2026-08-27 through "
                                      "2026-09-13, 18 consecutive days"),
        },
        "controls": []}

    for host, rel, role in FILES:
        rows = list(csv.DictReader(open(os.path.join(BASE, rel), encoding="utf-8")))
        recs, missing, skipped = [], [], []
        for r in rows:
            got = mine.get(host, {}).get(r["day"])
            if got is None:
                missing.append(r["day"])
                continue
            if verdict_is_unassessed(got[0]):
                skipped.append(r["day"])
                continue
            verdict, note, orow = got
            recs.append(dict(day=r["day"], their_state=r["state"],
                             share=float(r["share_402"]),
                             our_verdict=verdict, our_served=verdict in SERVED,
                             our_note=note[:60], row=orow))

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
        print(f"  compared {len(recs)}, no snapshot of ours for {len(missing)}"
              + (f", {len(skipped)} dropped as not assessed (rate-limited)" if skipped else ""))
        print(f"  UNMIXED days: {len(unmixed)}, disagreements {len(dis)}")
        for x in dis:
            print(f"    {x['day']} theirs={x['their_state']:8} ours={x['our_verdict']} {x['our_note'][:44]}")
        if mixed:
            print(f"  MIXED days: {len(mixed)}, share {min(x['share'] for x in mixed)*100:.1f}"
                  f"..{max(x['share'] for x in mixed)*100:.1f}%")
            print(f"    one-draw model (posted 2026-09-12, superseded): expected {exp:.2f}, "
                  f"sd {sd:.2f}" + (f", z {z:+.2f}" if z is not None else ", sd 0 so no z"))
            landing = lm.summarise([{"share": x["share"], "our_served": x["our_served"],
                                     "row": x["row"]} for x in mixed])
            print("    CORRECTED: " + lm.verdict_line(landing))
        else:
            landing = None
        report["controls"].append(dict(
            host=host, role=role, source=rel, days=len(recs), missing=missing,
            not_assessed_days=skipped,
            shapes=dict(shapes), unmixed=len(unmixed), unmixed_disagreements=len(dis),
            mixed=len(mixed), observed=obs, expected=round(exp, 4), sd=round(sd, 4),
            z=(round(z, 4) if z is not None else None),
            landing_model_corrected=landing, records=recs))

    tot_un = sum(c["unmixed"] for c in report["controls"])
    tot_dis = sum(c["unmixed_disagreements"] for c in report["controls"])
    print(f"\nACROSS BOTH CONTROLS: {tot_un - tot_dis} of {tot_un} unmixed days agree, "
          f"{tot_dis} disagreement(s)")
    out = os.path.join(BASE, "compare_controls_nohumans_2026-09-13.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=1)
    print("->", os.path.basename(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
