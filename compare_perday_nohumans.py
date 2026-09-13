#!/usr/bin/env python3
"""Lay the nohumans.directory per-day four-host file beside our daily snapshots.

THEIRS: thirdparty/nohumans_perday_four_hosts_2026-08-08_09-07.csv, one row per host per day,
  pass_402 and failures by status code across every probe they ran that day (~5-minute cadence).
OURS:   snapshots/<day>/observation.json, exactly ONE probe per host per day.

The question this answers is not "who is right". It is: when their day is MIXED (some probes
answered 402 and some did not), where does a single daily sample land, and does the rate agree?
A single sample cannot see a mixed day; it can only land somewhere inside one. So the honest
check is whether our landings, pooled across mixed days, track their 402 share.

Every figure printed as "theirs" comes from their file and is labelled theirs.
"""
import csv, json, os, sys, collections

BASE = os.path.dirname(os.path.abspath(__file__))
CSV  = os.path.join(BASE, "thirdparty", "nohumans_perday_four_hosts_2026-08-08_09-07.csv")
SNAP = os.path.join(BASE, "snapshots")
# Verdicts that mean "this host served a payment challenge on our probe that day".
SERVED = {"OK", "V1"}

def ours():
    """host -> day -> (verdict, note). One probe per host-day."""
    out = collections.defaultdict(dict)
    for day in sorted(d for d in os.listdir(SNAP) if d[:2] == "20"):
        o = json.load(open(os.path.join(SNAP, day, "observation.json"), encoding="utf-8"))
        rows = o.get("hosts") or o.get("results") or o.get("observations") or []
        if isinstance(rows, dict): rows = list(rows.values())
        for r in rows:
            h = str(r.get("host") or r.get("name") or r.get("domain") or "")
            if h:
                out[h][day] = (r.get("verdict"), str(r.get("notes") or ""))
    return out

def main():
    theirs = list(csv.DictReader(open(CSV, encoding="utf-8")))
    mine = ours()
    recs, missing = [], []
    for r in theirs:
        host, day = r["host"], r["day"]
        probes = int(r["probes"]); passes = int(r["pass_402"])
        fails = probes - passes
        shape = "ALL_402" if passes == probes else ("ALL_FAIL" if passes == 0 else "MIXED")
        got = mine.get(host, {}).get(day)
        if got is None:
            missing.append((host, day)); continue
        verdict, note = got
        served = verdict in SERVED
        recs.append(dict(day=day, host=host, probes=probes, passes=passes, fails=fails,
                         share_402=passes / probes if probes else None, their_shape=shape,
                         our_verdict=verdict, our_served=served, our_note=note[:60]))
    print(f"compared {len(recs)} host-days; {len(missing)} of their rows have no snapshot of ours")

    by_shape = collections.Counter(x["their_shape"] for x in recs)
    print("\nTHEIR day shape (their file):", dict(by_shape))

    print("\nAGREEMENT, by their day shape")
    print(f"  {'shape':9} {'host-days':>9} {'we saw a challenge':>19} {'we did not':>11}")
    for shape in ("ALL_402", "MIXED", "ALL_FAIL"):
        g = [x for x in recs if x["their_shape"] == shape]
        y = sum(1 for x in g if x["our_served"])
        print(f"  {shape:9} {len(g):>9} {y:>19} {len(g)-y:>11}")

    clean = [x for x in recs if x["their_shape"] != "MIXED"]
    dis = [x for x in clean if x["our_served"] != (x["their_shape"] == "ALL_402")]
    print(f"\nON UNMIXED DAYS we agree on {len(clean)-len(dis)} of {len(clean)}"
          f" ({(len(clean)-len(dis))/len(clean)*100:.1f}%). Disagreements: {len(dis)}")
    for x in dis:
        print(f"    {x['day']}  {x['host'][:44]:44} theirs={x['their_shape']:8} ours={x['our_verdict']} {x['our_note'][:40]}")

    mixed = [x for x in recs if x["their_shape"] == "MIXED"]
    if mixed:
        landed = sum(1 for x in mixed if x["our_served"])
        tot_p = sum(x["probes"] for x in mixed); tot_402 = sum(x["passes"] for x in mixed)
        print(f"\nMIXED DAYS: {len(mixed)}. Our single sample landed on a challenge {landed} of"
              f" {len(mixed)} times ({landed/len(mixed)*100:.0f}%).")
        print(f"  Their probe-weighted 402 share across those same days: {tot_402}/{tot_p}"
              f" = {tot_402/tot_p*100:.0f}%. That is the comparison that matters.")
        print("  per mixed day:")
        for x in sorted(mixed, key=lambda z: (z["host"], z["day"])):
            print(f"    {x['day']}  {x['host'][:40]:40} theirs {x['passes']:>4}/{x['probes']:<4}"
                  f" = {x['share_402']*100:>5.1f}% 402   ours={'402' if x['our_served'] else 'no 402':6} {x['our_note'][:34]}")

    out = os.path.join(BASE, "compare_perday_nohumans_2026-09-12.json")
    json.dump(dict(
        source="https://nohumans.directory/state/week-2026-09-09/perday-four-hosts.csv",
        license="CC-BY-4.0", retrieved="2026-09-12",
        note="their columns are theirs; our_verdict is one probe per host-day from our snapshots",
        compared=len(recs), missing=missing, records=recs), open(out, "w", encoding="utf-8"), indent=1)
    print("\n->", os.path.basename(out))

if __name__ == "__main__":
    main()
