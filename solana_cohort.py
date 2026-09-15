#!/usr/bin/env python3
"""The Solana-mainnet cohort this census carries, with the payTo the daily sweep throws away.

WHY THIS EXISTS. Two counterparts asked for the same artifact on 2026-09-15: nohumans.directory
wants the host list and the daily rows so the two catalogues can be intersected before either
side commits to a trade, and Paddock wants the list plus the Solana payTo, because payTo is the
join key their settlement graph structurally lacks.

WHAT THE DAILY CENSUS ALREADY HAS. A host whose live challenge names a Solana network is recorded
NON_EVM: served, but not assessed, because preflight only knows the EVM signer. That verdict is a
statement about this instrument's competence and never about the operator. The per-day series is
therefore already in the signed snapshots and needs no new probe.

WHAT IT DOES NOT HAVE. decide() returns the parsed challenge for a NON_EVM row and observe()
discards it, so payTo was never stored. That is the one field this script fetches live, with the
same read-only method the daily sweep uses: no wallet, no key, no payment, one request per host.

WHAT IT REFUSES TO FLATTEN. The cohort is NOT uniform in age. Membership is per-day, not per-host:
some of these hosts have named Solana on every day of the window and some only recently, so the
file carries first_non_evm_day, last, and a count per host rather than one number for the group.
A reader who wants "15 hosts since 08-08" cannot get it from here, because it is not true.

Usage: python solana_cohort.py [--no-probe]   (writes solana_cohort_<latest-snapshot>.json/.csv)
"""
import csv
import json
import sys
from pathlib import Path

import preflight

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"
SOLANA_PREFIX = "network=solana"


def series():
    """host -> the NON_EVM day list, read from the signed archive. No network."""
    days = sorted(p.name for p in SNAPSHOTS.iterdir() if p.name[:2] == "20")
    per, url, net = {}, {}, {}
    for d in days:
        with open(SNAPSHOTS / d / "observation.json", encoding="utf-8") as f:
            for r in json.load(f)["observations"]:
                if r.get("verdict") != "NON_EVM":
                    continue
                note = next((n for n in (r.get("notes") or []) if n.startswith(SOLANA_PREFIX)), None)
                if not note:
                    continue
                per.setdefault(r["host"], []).append(d)
                url[r["host"]] = r["url"]
                net[r["host"]] = note.split(" ")[0].split("=", 1)[1]
    return days, per, url, net


def payto(u: str) -> dict:
    """One read-only request, same method as the daily sweep. Never raises."""
    try:
        status, headers, body = preflight.get_402(u)
    except Exception as e:  # noqa: BLE001
        return {"probe": f"unreachable: {type(e).__name__}"}
    if status != 402:
        return {"probe": f"HTTP {status}, no challenge"}
    hdr, bod = preflight.parse_challenge(headers, body)
    ch = hdr if isinstance(hdr, dict) else (bod if isinstance(bod, dict) else None)
    if not ch:
        return {"probe": "402 with no readable challenge"}
    acc = ch.get("accepts")
    if not isinstance(acc, list) or not acc:
        return {"probe": "challenge carries no accepts[]"}
    a = acc[0]
    return {"probe": "ok", "pay_to": a.get("payTo"), "network": a.get("network"),
            "asset": a.get("asset"), "amount": a.get("amount", a.get("maxAmountRequired")),
            "accepts_len": len(acc)}


def main() -> int:
    days, per, url, net = series()
    latest = days[-1]
    live = sorted(h for h, ds in per.items() if ds and ds[-1] == latest)
    probe = "--no-probe" not in sys.argv

    rows = []
    for h in live:
        ds = per[h]
        row = {"host": h, "url": url[h], "network_named": net[h],
               "first_non_evm_day": ds[0], "last_non_evm_day": ds[-1],
               "non_evm_days": len(ds), "window_days": len(days),
               "every_day_of_window": len(ds) == len(days),
               # The full per-day series, because a count is not the rows. nohumans.directory
               # asked for daily NON_EVM rows to intersect against their catalogue, and a
               # first/last/count triple hides a gap in the middle. Derivable from the public
               # snapshots either way; shipping it saves them re-deriving it.
               "non_evm_days_list": ds,
               "gaps_inside_span": sorted(
                   set(days[days.index(ds[0]):days.index(ds[-1]) + 1]) - set(ds))}
        row.update(payto(url[h]) if probe else {"probe": "skipped"})
        rows.append(row)

    print(f"  window {days[0]}..{latest} ({len(days)} days); {len(live)} hosts naming Solana on {latest}")
    got = sum(1 for r in rows if r.get("pay_to"))
    print(f"  payTo recovered for {got} of {len(rows)}")
    print(f"  {'host':44} {'first':11} {'days':>4}  payTo")
    for r in rows:
        print(f"  {r['host'][:44]:44} {r['first_non_evm_day']} {r['non_evm_days']:>4}  "
              f"{(r.get('pay_to') or r.get('probe') or '')[:46]}")
    span = sorted({r["non_evm_days"] for r in rows})
    print(f"\n  NOT uniform: per-host NON_EVM day counts run {min(span)} to {max(span)}; "
          f"{sum(1 for r in rows if r['every_day_of_window'])} of {len(rows)} cover every day.")

    out = HERE / f"solana_cohort_{latest}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump({
            "generated": latest,
            "window": {"first": days[0], "last": latest, "days": len(days)},
            "definition": ("hosts whose live challenge named a Solana network on the latest day, "
                           "recorded NON_EVM by this census: served, not assessed, because this "
                           "prober only knows the EVM signer. NON_EVM is a fact about this "
                           "instrument and never about the operator."),
            "membership_note": ("membership is per-day, not per-host. non_evm_days is the count of "
                                "days each host was recorded NON_EVM inside the window; it is NOT "
                                "uniform and must not be read as one age for the cohort."),
            "payto_note": ("payTo is fetched live with the same read-only method as the daily "
                           "sweep, one request per host, no wallet and no payment. It is not in "
                           "the signed snapshots because observe() discards the parsed challenge."),
            "hosts": rows,
        }, f, indent=1)
    csvp = HERE / f"solana_cohort_{latest}.csv"
    cols = ["host", "network_named", "first_non_evm_day", "last_non_evm_day", "non_evm_days",
            "window_days", "every_day_of_window", "pay_to", "asset", "amount", "probe"]
    with open(csvp, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"-> {out.name} and {csvp.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
