#!/usr/bin/env python3
"""Per-wallet settlement counters and first-seen block, for the Paddock parity sample.

WHY A LONGER LOOKBACK THAN THE WINDOW. The sample needs two different things. distinct_payers
and settlements are counted over the reporting window (30 days by default). "First seen in the
last 7 days" is a claim about ABSENCE before that, and a 30-day scan cannot make it: a wallet
whose earliest payment inside the window falls in the last 7 days may have been paid on day 40.
So the scan runs over a longer lookback and records each wallet's earliest payment in it. The
claim then becomes first-seen-within-the-lookback, and the lookback start ships beside it rather
than being left for the reader to assume.

METHOD. Same as demand_sweep.py and for the same reason: eth_getLogs over block ranges with the
recipient topic filtered to our wallet set, never the per-address history endpoint, which pages
and silently truncates. A range the RPC refuses is split, never skipped, because a dropped range
understates payments. Read-only, keyless, free. Burn addresses are excluded exactly as
demand_sweep.py excludes them.

WHOSE COUNT IS WHICH. Paddock's settlement counts, which this sample was built to sit beside, are
a nightly approximation: against this full-window scan they ran over by 19% on one of these
wallets and short by roughly 90% on the facilitator-heavy ones (Paddock, 2026-09-22). What this
scan counts is every USDC transfer into the payTo inside the window, x402 or not, so the two
numbers answer different questions and the difference is not a disagreement about x402.

Usage: python parity_scan.py [--days 30] [--lookback 120] [--src payto_wallets.json]
Writes parity_scan.json. No API key is used or stored here.
"""
import collections
import json
import sys
import time

from rpc import TRANSFER, USDC, blocks_for_days, rpc, topic_addr

CHUNK = 1000            # the archive-capable public gateway's ceiling, measured 2026-09-20
RETRIES = 4             # a rate-limited range is retried before it is split, never dropped quietly
BURN = {"0x" + "0" * 40, "0x" + "0" * 39 + "1", "0x" + "d" * 40}


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def main() -> int:
    days = int(arg("--days", 30))
    lookback = int(arg("--lookback", 120))
    src = arg("--src", "payto_wallets.json")
    out_path = arg("--out", "parity_scan.json")
    only = [a.strip().lower() for a in arg("--only", "").split(",") if a.strip()]
    rows = json.load(open(src, encoding="utf-8"))
    addrs = sorted({(r.get("payTo") or "").lower() for r in rows if r.get("payTo")})
    addrs = [a for a in addrs if a not in BURN]
    # Phase 2 of the parity run: the population scan answers "how many payers in the window",
    # and this narrows a deeper lookback to a handful of candidates. Cost tracks the number of
    # MATCHING logs, not the block span, so a few addresses over months is cheap where the whole
    # population over the same span is not.
    if only:
        addrs = [a for a in addrs if a in set(only)]
        missing = sorted(set(only) - set(addrs))
        if missing:
            print(f"  NOTE: {len(missing)} requested address(es) are not in {src}: {missing[:3]}")
    topics = [topic_addr(a) for a in addrs]

    look_start, head = blocks_for_days(lookback)
    win_start, _ = blocks_for_days(days)
    # Phase 2 asks one question only: was a candidate paid BEFORE the window? Scanning the window
    # again would just re-derive what the population scan already holds, so --before-window stops
    # at the window's first block and the answer is the presence or absence of any log at all.
    before_window = "--before-window" in sys.argv
    if before_window:
        head = win_start - 1
    print(f"  {len(addrs)} wallets from {src}")
    print(f"  lookback blocks {look_start}..{head} ({lookback}d) | window starts {win_start} ({days}d)")

    n_win = collections.Counter()
    payers_win = collections.defaultdict(set)
    first_blk, last_blk = {}, {}
    n_logs = covered = 0
    gaps = []

    def scan(lo, hi, depth=0):
        nonlocal n_logs, covered
        logs = None
        for attempt in range(RETRIES):
            try:
                logs = rpc("eth_getLogs", [{"fromBlock": hex(lo), "toBlock": hex(hi),
                                            "address": USDC, "topics": [TRANSFER, None, topics]}])
                break
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(1.5 * (attempt + 1))
        if logs is None:
            if hi - lo < 40 or depth > 12:
                gaps.append([lo, hi, str(err)[:80]])
                print(f"    !! gave up on {lo}..{hi}: {str(err)[:60]}", flush=True)
                return
            mid = (lo + hi) // 2
            scan(lo, mid, depth + 1)
            scan(mid + 1, hi, depth + 1)
            return
        for lg in logs:
            to = "0x" + lg["topics"][2][-40:]
            blk = int(lg["blockNumber"], 16)
            if to not in first_blk or blk < first_blk[to]:
                first_blk[to] = blk
            if to not in last_blk or blk > last_blk[to]:
                last_blk[to] = blk
            if blk >= win_start:
                n_win[to] += 1
                payers_win[to].add("0x" + lg["topics"][1][-40:])
        n_logs += len(logs)
        covered += hi - lo + 1

    t0 = time.time()
    frm = look_start
    while frm <= head:
        to = min(frm + CHUNK - 1, head)
        scan(frm, to)
        frm = to + 1
        done, span = frm - look_start, head - look_start
        if done % (CHUNK * 50) < CHUNK:
            print(f"    {done / span * 100:5.1f}%  {n_logs:>9,} payments  "
                  f"{len(first_blk):>4} wallets seen  {time.time() - t0:5.0f}s", flush=True)

    out = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": src, "wallets_scanned": len(addrs),
        "window_days": days, "lookback_days": lookback,
        "blocks": {"lookback_start": look_start, "window_start": win_start, "head": head,
                   "covered": covered, "span": head - look_start + 1},
        "payments_in_lookback": n_logs,
        "uncovered_ranges": gaps,
        "fully_covered": not gaps,
        "note": ("settlements and distinct_payers are counted inside the window only; "
                 "first_block is the earliest payment anywhere in the lookback, so "
                 "'first seen in the last 7 days' means no payment in the lookback before then"),
        "per_wallet": {a: {"settlements_window": n_win.get(a, 0),
                           "distinct_payers_window": len(payers_win.get(a, ())),
                           "first_block_lookback": first_blk.get(a),
                           "last_block_lookback": last_blk.get(a)}
                       for a in addrs if a in first_blk or a in n_win},
    }
    json.dump(out, open(out_path, "w", encoding="utf-8", newline="\n"), indent=1)
    print(f"\n  covered {covered:,} of {head - look_start + 1:,} blocks | "
          f"{n_logs:,} payments | {len(out['per_wallet'])} wallets with activity")
    print(f"  -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
