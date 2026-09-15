#!/usr/bin/env python3
"""The 14-day not-gated census, reported both ways: counting origin failures, and not.

WHY. A host that answers 404 has told us something about the route. A host whose origin returns
503, or whose CDN returns 530 because it never reached the origin at all, has told us only that
its server is failing. Both produce no payment challenge, so both are NO_402, and the published
sentence "gone at least fourteen straight days serving no payment challenge" is true of both.
But a reader using that count to decide whether a provider stopped selling will read the two very
differently, and until 2026-09-14 the row's note asserted "endpoint is not payment-gated right
now" over a plain server failure, which claims more than the response supports.

Found on 2026-09-14 from Mancy (Paddock), who reported the same shape on her side: one reason
code spanning 429, 503, 504 and a genuinely ungated 200, glossed in partner docs as "it answered,
but never asked for payment". Only the ungated 200 fits that gloss. On this census the same
conflation covered 731 host-days across 85 hosts.

WHAT THIS DOES NOT DO. It does not move a published number. The verdict stays NO_402 and the
counts stay what they were; this script prints the alternative beside it so both are visible,
the way a re-cut belongs beside an original rather than replacing it.

Usage: python origin_error_history.py   (writes origin_error_history_<latest-snapshot>.json)
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"
NEED = 14
_HTTP = re.compile(r"HTTP (\d+)")


def status_of(row: dict) -> str:
    """The HTTP status recorded in the row's note, under either era's wording."""
    for n in row.get("notes") or []:
        m = _HTTP.match(n)
        if m:
            return m.group(1)
    return ""


def origin_error(row: dict) -> bool:
    """True when the row's NO_402 came from the origin failing rather than answering."""
    return row.get("verdict") == "NO_402" and status_of(row).startswith("5")


def load():
    days = sorted(p.name for p in SNAPSHOTS.iterdir() if p.name[:2] == "20")
    V, S = {}, {}
    for d in days:
        with open(SNAPSHOTS / d / "observation.json", encoding="utf-8") as f:
            rows = json.load(f)["observations"]
        V[d] = {r["host"]: r["verdict"] for r in rows}
        S[d] = {r["host"]: status_of(r) for r in rows}
    return days, V, S


def ever_hit_run(days, V, S, neutralise: bool) -> set:
    out = set()
    for h in V[days[-1]]:
        run = 0
        for d in days:
            v = V[d].get(h)
            if neutralise and v == "NO_402" and S[d].get(h, "").startswith("5"):
                v = "ORIGIN_ERROR"
            if v == "NO_402":
                run += 1
                if run >= NEED:
                    out.add(h)
                    break
            else:
                run = 0
    return out


def main() -> int:
    days, V, S = load()
    per = defaultdict(int)
    hosts = defaultdict(set)
    for d in days:
        for h, st in S[d].items():
            if V[d].get(h) == "NO_402" and st.startswith("5"):
                per[st] += 1
                hosts[st].add(h)
    total = sum(per.values())
    allhosts = set().union(*hosts.values()) if hosts else set()
    print(f"  5xx filed as NO_402 across {len(days)} days: {total} host-days, {len(allhosts)} hosts")
    for st, n in sorted(per.items(), key=lambda kv: -kv[1]):
        print(f"    HTTP {st}: {n:>4} host-days, {len(hosts[st]):>3} hosts")

    a = ever_hit_run(days, V, S, False)
    b = ever_hit_run(days, V, S, True)
    dropped = sorted(a - b)
    print(f"\n  hosts with a {NEED}-day not-gated run, as published:        {len(a)}")
    print(f"  same if an origin failure is not counted as an answer:   {len(b)}")
    print(f"  the difference is {len(dropped)} host(s) whose run leans on 5xx days")

    detail = []
    for h in dropped:
        tot = sum(1 for d in days if V[d].get(h) == "NO_402")
        five = sum(1 for d in days if V[d].get(h) == "NO_402" and S[d].get(h, "").startswith("5"))
        detail.append({"host": h, "no_402_days": tot, "of_which_5xx": five,
                       "every_day_5xx": tot == five == len(days)})
    for r in sorted(detail, key=lambda r: -r["of_which_5xx"])[:10]:
        print(f"    {r['host'][:50]:50} {r['of_which_5xx']}/{r['no_402_days']} 5xx")

    out = HERE / f"origin_error_history_{days[-1]}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump({
            "generated": days[-1],
            "window": {"first": days[0], "last": days[-1], "days": len(days)},
            "rule": ("verdict is unchanged: a 5xx stays NO_402 because the probe obtained no "
                     "payment challenge. From 2026-09-14 the note says the origin failed rather "
                     "than that the endpoint is not payment-gated. Earlier rows carry the old "
                     "note and are separated here by reading the status out of it."),
            "host_days_5xx_as_no_402": total,
            "hosts_affected": len(allhosts),
            "by_status": {k: {"host_days": v, "hosts": len(hosts[k])} for k, v in sorted(per.items())},
            "notgated_runs_rule_days": NEED,
            "notgated_runs_as_published": len(a),
            "notgated_runs_if_origin_errors_excluded": len(b),
            "hosts_that_would_drop": detail,
        }, f, indent=1)
    print("->", out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
