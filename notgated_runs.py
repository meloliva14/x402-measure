"""Consecutive not-gated (NO_402) runs across the pinned population, and what ended them.

Written for the wg-domain-discovery delisting discussion: a rule that stops probing a
listing after N consecutive not-gated days cannot observe the listing coming back, so it
confirms itself. This derives, from the signed snapshots alone, every host that has had a
14-consecutive-day NO_402 run, whether that run has ended, and whether the host went on to
serve a 402 again. A run is consecutive NO_402 verdicts only; a day the prober could not
reach the host (UNREACHABLE) ends the run without being an answer, so hosts whose runs
ended that way are listed but flagged not-recovered.

Censoring, stated so nobody cites past it: a run that begins on the first snapshot day is
left-censored (its true length is at least what is recorded), and the window itself bounds
what any rule longer than the window can be tested against.

Usage: python notgated_runs.py   (writes notgated_runs_<latest-snapshot>.json)
"""
import json
import os
from pathlib import Path

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"
GATED = {"OK", "WARN", "V1", "NON_EVM", "BLOCKED"}
NEED = 14


def main() -> None:
    days = sorted(p.name for p in SNAPSHOTS.iterdir())
    V = {}
    for d in days:
        obs = json.load(open(SNAPSHOTS / d / "observation.json", encoding="utf-8"))["observations"]
        V[d] = {r["host"]: r["verdict"] for r in obs}
    hosts = list(V[days[-1]])

    rows = []
    for h in hosts:
        seq = [V[d].get(h) for d in days]
        run = 0
        start = None
        q = None
        for i, v in enumerate(seq):
            if v == "NO_402":
                run += 1
                if run == 1:
                    start = i
                if run >= NEED and q is None:
                    q = start
            else:
                run = 0
        if q is None:
            continue
        end = q
        while end + 1 < len(days) and seq[end + 1] == "NO_402":
            end += 1
        post = seq[end + 1:]
        recovered_on = next((days[end + 1 + j] for j, v in enumerate(post) if v in GATED), None)
        rows.append({
            "host": h,
            "run_start": days[q],
            "run_end": days[end],
            "run_days": end - q + 1,
            "left_censored": q == 0,
            "run_ended": end + 1 < len(days),
            "recovered_on": recovered_on,
            "verdict_latest": seq[-1],
        })

    rows.sort(key=lambda r: r["host"])
    ended = [r for r in rows if r["run_ended"]]
    rec = [r for r in ended if r["recovered_on"]]
    out = {
        "window": {"first": days[0], "last": days[-1], "days": len(days)},
        "population": len(hosts),
        "rule_days": NEED,
        "summary": {
            "ever_hit_run": len(rows),
            "in_run_at_latest": len(rows) - len(ended),
            "run_ended": len(ended),
            "recovered": len(rec),
            "ended_without_answer": len(ended) - len(rec),
        },
        "runs": rows,
    }
    dest = HERE / f"notgated_runs_{days[-1]}.json"
    json.dump(out, open(dest, "w"), indent=1)
    s = out["summary"]
    print(f"{len(days)} days {days[0]}..{days[-1]}, population {len(hosts)}")
    print(f"ever>= {NEED}: {s['ever_hit_run']}  in-run: {s['in_run_at_latest']}  "
          f"ended: {s['run_ended']} = recovered {s['recovered']} + no-answer {s['ended_without_answer']}")
    print(f"-> {dest.name}")


if __name__ == "__main__":
    main()
