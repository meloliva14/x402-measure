#!/usr/bin/env python3
"""Every host-day this census filed as not-payment-gated on the strength of an HTTP 429.

WHY THIS EXISTS. Until 2026-09-13, preflight.decide() returned NO_402 for any status that was
not 402, with the note "endpoint is not payment-gated right now". For a 429 that note states
the opposite of what is known: a rate-limit response is a fact about the conversation, not
about whether the endpoint sells anything. nohumans.directory published the same defect in
their own scanner on 2026-09-13, at a far larger scale and from the opposite direction (their
probe rate caused the 429s); checking their disclosure against this census turned up ours.

The evidence that the label was wrong is inside the series. Both affected hosts served a
readable 402 on the days their 429 lifted, so on the only days there is independent evidence,
the "not payment-gated" verdict is contradicted by this census itself.

THE SIGNED SNAPSHOTS ARE NEVER REWRITTEN. An observation.json is signed over its exact bytes
and a published digest is permanent; editing one to fix a label would be a worse act than the
label. The rows still read NO_402 and still carry "HTTP 429" in the note. What changes is the
reading: derived scripts take the recorded status rather than the label, which is what this
script and notgated_runs.py now do, so the correction is reproducible by anyone from the
public archive.

WHAT IT CHANGES IN A PUBLISHED FIGURE. notgated_runs.py counts hosts with a 14-consecutive-day
NO_402 run. This script recomputes that count with 429 days treated as neutral and prints both,
so the size of the correction is stated rather than quietly absorbed.

Usage: python rate_limited_history.py   (writes rate_limited_history_<latest-snapshot>.json)
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"
GATED = {"OK", "WARN", "V1", "NON_EVM", "BLOCKED"}
NEED = 14


def rate_limited(row: dict) -> bool:
    """True if this observation was a rate-limit response, under either era's labelling."""
    return (row.get("verdict") == "RATE_LIMITED"
            or any("HTTP 429" in n for n in (row.get("notes") or [])))


def load() -> tuple[list[str], dict]:
    days = sorted(p.name for p in SNAPSHOTS.iterdir() if p.name[:2] == "20")
    rows = {}
    for d in days:
        with open(SNAPSHOTS / d / "observation.json", encoding="utf-8") as f:
            rows[d] = {r["host"]: r for r in json.load(f)["observations"]}
    return days, rows


def ever_hit_run(days: list[str], rows: dict, neutralise: bool) -> set[str]:
    """Hosts with a NEED-day consecutive NO_402 run. With neutralise, a 429 day is not NO_402."""
    hosts = set(rows[days[-1]])
    out = set()
    for h in hosts:
        run = 0
        for d in days:
            r = rows[d].get(h)
            if r is None:
                run = 0
                continue
            v = r["verdict"]
            if neutralise and rate_limited(r):
                v = "RATE_LIMITED"
            if v == "NO_402":
                run += 1
                if run >= NEED:
                    out.add(h)
                    break
            else:
                run = 0
    return out


def main() -> int:
    days, rows = load()
    by_host = defaultdict(list)
    for d in days:
        for h, r in rows[d].items():
            if rate_limited(r):
                by_host[h].append(d)

    affected = []
    for h, ds in sorted(by_host.items()):
        served = [d for d in days
                  if rows[d].get(h) and rows[d][h]["verdict"] in GATED]
        affected.append({
            "host": h,
            "rate_limited_days": ds,
            "rate_limited_count": len(ds),
            "days_it_served_a_readable_challenge": served,
            "contradicted_by_this_census": bool(served),
        })
        print(f"  {h}")
        print(f"    rate-limited on {len(ds)} of {len(days)} days, {ds[0]}..{ds[-1]}")
        print(f"    served a readable challenge on {len(served)} day(s): {served or 'none'}")

    old = ever_hit_run(days, rows, neutralise=False)
    new = ever_hit_run(days, rows, neutralise=True)
    dropped = sorted(old - new)
    print(f"\n  total host-days affected: {sum(len(v) for v in by_host.values())}"
          f" of {sum(len(rows[d]) for d in days)}")
    print(f"  hosts with a {NEED}-day not-gated run, as filed:  {len(old)}")
    print(f"  hosts with a {NEED}-day not-gated run, corrected: {len(new)}")
    print(f"  dropped by the correction: {dropped or 'none'}")

    out = HERE / f"rate_limited_history_{days[-1]}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump({
            "generated": days[-1],
            "window": {"first": days[0], "last": days[-1], "days": len(days)},
            "rule": ("HTTP 429 is RATE_LIMITED, not NO_402, from 2026-09-13; earlier rows keep "
                     "the NO_402 label and carry the status in the note, and are reclassified "
                     "here by reading the status back out rather than by editing any signed file"),
            "host_days_affected": sum(len(v) for v in by_host.values()),
            "hosts": affected,
            "notgated_runs_rule_days": NEED,
            "notgated_runs_as_filed": len(old),
            "notgated_runs_corrected": len(new),
            "dropped_by_the_correction": dropped,
        }, f, indent=1)
    print("->", out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
