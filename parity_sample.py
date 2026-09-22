#!/usr/bin/env python3
"""Pick the 25 payTos for the Paddock parity run and write sample.csv.

THE THREE BUCKETS, exactly as Paddock specified them: the 10 with the most distinct payers, 10
with exactly one payer, and 5 first seen in the last 7 days. Ties are broken deterministically
so the same scan always yields the same 25, and a wallet is never counted in two buckets.

WHAT "FIRST SEEN" MEANS HERE, IN TWO PHASES. The population scan covers the reporting window and
gives each wallet its earliest payment inside it. That alone cannot support "first seen in the
last 7 days": a wallet first paid on day 28 of the window may have been paid on day 40. So every
candidate is re-checked against a second scan of the days BEFORE the window (parity_firstseen.json,
passed with --firstseen), and a candidate survives only if that scan finds no payment at all. The
claim is therefore bounded by the deeper scan's start, which ships in sample_basis.json rather
than being left for the reader to assume.

usdc_total is deliberately absent. The repo does not publish per-wallet revenue, Paddock agreed
the column was a convenience rather than a requirement, and the header below is the one they
restated after dropping it.

Usage: python parity_sample.py   (reads parity_scan.json, writes sample.csv)
"""
import csv
import json
import sys
import time

from rpc import blocks_for_days, rpc

HEADER = ["pay_to", "chain", "window_start", "window_end", "distinct_payers", "settlements"]
CHAIN = "eip155:8453"          # Base mainnet, CAIP-2, the form Paddock's own docs use


def block_time(n: int) -> str:
    b = rpc("eth_getBlockByNumber", [hex(n), False])
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(b["timestamp"], 16)))


def main() -> int:
    scan = json.load(open("parity_scan.json", encoding="utf-8"))
    per = scan["per_wallet"]
    blocks = scan["blocks"]
    start7, _ = blocks_for_days(7)

    win_start_ts = block_time(blocks["window_start"])
    win_end_ts = block_time(blocks["head"])

    paid = {a: r for a, r in per.items() if r["settlements_window"] > 0}
    chosen, why = [], {}

    most = sorted(paid.items(), key=lambda kv: (-kv[1]["distinct_payers_window"],
                                                -kv[1]["settlements_window"], kv[0]))[:10]
    for a, _ in most:
        chosen.append(a); why[a] = "most_distinct_payers"

    one = sorted(((a, r) for a, r in paid.items()
                  if r["distinct_payers_window"] == 1 and a not in why),
                 key=lambda kv: (-kv[1]["settlements_window"], kv[0]))[:10]
    for a, _ in one:
        chosen.append(a); why[a] = "exactly_one_payer"

    fs_path = sys.argv[sys.argv.index("--firstseen") + 1] if "--firstseen" in sys.argv else None
    paid_before, deeper = set(), None
    if fs_path:
        deeper = json.load(open(fs_path, encoding="utf-8"))
        paid_before = {a for a, r in deeper["per_wallet"].items()
                       if r.get("first_block_lookback") is not None}
    cands = [a for a, r in per.items()
             if r.get("first_block_lookback") is not None
             and r["first_block_lookback"] >= start7 and a not in why]
    survivors = [a for a in cands if a not in paid_before]
    new = sorted(((a, per[a]) for a in survivors),
                 key=lambda kv: (-kv[1]["first_block_lookback"], kv[0]))[:5]
    for a, _ in new:
        chosen.append(a); why[a] = "first_seen_last_7_days"

    with open("sample.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        for a in chosen:
            r = per[a]
            w.writerow([a, CHAIN, win_start_ts, win_end_ts,
                        r["distinct_payers_window"], r["settlements_window"]])

    counts = {b: sum(1 for v in why.values() if v == b) for b in
              ("most_distinct_payers", "exactly_one_payer", "first_seen_last_7_days")}
    json.dump({"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "window": {"start": win_start_ts, "end": win_end_ts,
                          "days": scan["window_days"], "start_block": blocks["window_start"],
                          "end_block": blocks["head"]},
               "lookback_days": scan["lookback_days"],
               "lookback_start_block": blocks["lookback_start"],
               "first_seen_boundary_block": start7,
               "first_seen_check": {
                   "candidates_in_window": len(cands),
                   "eliminated_by_earlier_payment": len([a for a in cands if a in paid_before]),
                   "survivors": len(survivors),
                   "deeper_scan": fs_path,
                   "deeper_scan_lookback_days": (deeper or {}).get("lookback_days"),
                   "deeper_scan_start_block": ((deeper or {}).get("blocks") or {}).get("lookback_start"),
                   "deeper_scan_fully_covered": (deeper or {}).get("fully_covered"),
                   "note": ("a candidate survives only if the scan of the days before the window "
                            "found no payment to it at all; absence is established no further "
                            "back than that scan's start block")},
               "chain": CHAIN, "rows": len(chosen), "bucket_counts": counts,
               "bucket_of": why},
              open("sample_basis.json", "w", encoding="utf-8", newline="\n"), indent=1)

    print(f"  window {win_start_ts} .. {win_end_ts} ({scan['window_days']}d), chain {CHAIN}")
    print(f"  wallets with a payment in the window: {len(paid)} of {scan['wallets_scanned']}")
    for b, n in counts.items():
        print(f"    {b:24} {n}")
    if len(chosen) != 25:
        print(f"  NOTE: {len(chosen)} rows, not 25. A bucket did not fill; "
              f"say so rather than padding it from another bucket.")
    print("  -> sample.csv, sample_basis.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
