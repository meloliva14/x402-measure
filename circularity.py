"""Is a seller's revenue coming from wallets the seller itself funded?

NAMING, DELIBERATELY. This is not called wash_trade.py, and the word does not appear in its
output. What is checkable from public data is an on-chain FUNDING EDGE: seller S sent USDC to
wallet W, and W later paid S. That edge is a fact. "Wash trading" is an inference about intent,
and intent is not on-chain. A seller funding a test wallet to exercise its own paid route is
doing something completely legitimate and produces exactly the same edge.

So this reports the edge and the share of receipts behind it, and leaves the conclusion to a
reader who knows the context. Publishing "X% of this seller's revenue came from wallets it
funded" is defensible and citable. Publishing "X is wash trading" is neither.

WHY IT MATTERS. Artemis found 48% of x402 transactions and 81% of dollar volume linked to gamed
activity as of December 2025, but the per-seller method is not public, so nobody can check it or
reproduce it for a specific counterparty. Every diligence process on an x402 company needs a
per-seller number and there isn't one. We hold every payTo wallet in the Bazaar and the chain is
public, so the gap is method, not data.

WHAT THIS DOES NOT CATCH, stated up front because a silent miss here understates circularity and
that is the direction this must not err in:

  - Indirect funding. S -> X -> W is invisible to a one-hop check. Only S -> W is detected.
  - Funding in anything other than USDC on Base, including ETH for gas, bridges, and CEX routes.
  - Funding that happened before the lookback window.
  - Common-controller wallets that were never funded by the seller at all.

Every one of those makes the reported share a FLOOR, never a ceiling. Say "at least" when
quoting it.

Read-only, keyless, free. Public RPC only, same as the rest of this repo.

USAGE
    python circularity.py                 # top 15 sellers by payment count, 7d receipts
    python circularity.py 25 14           # top 25 sellers, 14d receipts
"""
import json
import sys
import time
from pathlib import Path

from rpc import MAX_RANGE, TRANSFER, USDC, blocks_for_days, rpc, topic_addr

HERE = Path(__file__).parent
DEMAND = HERE / "demand_results.json"
OUT = HERE / "circularity.json"

# How far back to look for the seller having funded a payer. Deliberately much wider than the
# receipts window: the funding usually happens once, at setup, long before the traffic starts.
FUNDING_LOOKBACK_DAYS = 120


# Floor for the adaptive window in _logs. Below this the call count explodes for no benefit, and
# a range that still will not answer at 64 blocks is a real failure worth raising on rather than
# grinding at.
_MIN_RANGE = 64


def _fetch_range(params, frm, to, chain):
    """One eth_getLogs with backoff. Raises if the endpoint will not answer this window."""
    delay = 2.0
    for attempt in range(4):
        try:
            return rpc("eth_getLogs",
                       [dict(params, fromBlock=hex(frm), toBlock=hex(to))], chain)
        except Exception:  # noqa: BLE001 - transient load-shedding, retry then hand back up
            if attempt == 3:
                raise
            time.sleep(delay)
            delay *= 2
    return []


def _logs(params, chain="base", on_progress=None):
    """eth_getLogs across a block range the public RPCs will actually accept.

    Retries here rather than in rpc.py. A public endpoint answering 408 or 429 under a long
    sweep is expected load-shedding, not a broken call, and it is this module that generates
    the load. rpc.py stays a thin transport that reports failure honestly; the backoff policy
    belongs with the caller that needs one. A range that still fails after the retries RAISES
    rather than returning short: a silently dropped range would understate both receipts and
    funding edges, and understating a funding edge turns a circular seller into an
    "independent" one, which is the single worst direction this can be wrong in.
    """
    frm, head = params.pop("_from"), params.pop("_to")
    total = max(1, head - frm)
    out = []
    span = MAX_RANGE
    while frm <= head:
        to = min(frm + span - 1, head)
        try:
            out.extend(_fetch_range(params, frm, to, chain))
        except Exception:  # noqa: BLE001 - narrow the window rather than lose the seller
            # BACKOFF ALONE CANNOT FIX THIS ONE. Waiting longer and re-sending an IDENTICAL
            # request gets an identical refusal: a 408 here is usually the node declining to
            # serialise the number of logs the window matches, not a transient blip. The only
            # variable that changes the answer is the size of the window.
            #
            # Found on the largest wallet on the network: 1,088,620 payments in seven days is
            # roughly 32k logs per 9,000-block range, and every retry timed out at the same
            # size, so the biggest seller was the one seller we could not measure. Quartering
            # the window until it is answerable costs more calls and returns the data.
            if span <= _MIN_RANGE:
                raise
            span = max(_MIN_RANGE, span // 4)
            continue                      # same frm, smaller window
        if on_progress:
            on_progress(min(1.0, (to - (head - total)) / total))
        frm = to + 1
        # Widen back once a range succeeds, so one dense stretch does not force the rest of a
        # sweep to crawl at the narrow size.
        if span < MAX_RANGE:
            span = min(MAX_RANGE, span * 2)
    return out


def payers_of(seller, days, chain="base", asset=USDC):
    """Every wallet that paid `seller` in the window, with amount and count.

    rpc.revenue() already walks these logs but returns only counts; this keeps the addresses,
    which is the whole difference between "4 payers" and a checkable claim about who they are.
    """
    start, head = blocks_for_days(days, chain)
    logs = _logs({"_from": start, "_to": head, "address": asset,
                  "topics": [TRANSFER, None, topic_addr(seller)]}, chain)
    per = {}
    for lg in logs:
        try:
            amt = int(lg["data"], 16) / 1e6
        except (ValueError, KeyError, TypeError):
            continue
        payer = "0x" + lg["topics"][1][-40:]
        e = per.setdefault(payer.lower(), {"usd": 0.0, "n": 0})
        e["usd"] += amt
        e["n"] += 1
    return per


def funded_wallets(seller, days=FUNDING_LOOKBACK_DAYS, chain="base", asset=USDC):
    """Every wallet `seller` sent USDC to in the lookback, as {addr: {usd, n}}.

    ONE pass over the seller's outgoing transfers, then intersect with the payer set. The
    obvious implementation asks "did S fund payer P?" once per payer, which is a full
    lookback scan per payer: at 120 days and a 9,000-block cap that is ~576 RPC calls each,
    so a seller with 197 payers costs 113,000 calls. Public RPCs answer that with a 408, which
    is how this was found. Filtering on the FROM topic instead makes it ~576 calls total for
    the seller regardless of how many payers it has.
    """
    start, head = blocks_for_days(days, chain)
    logs = _logs({"_from": start, "_to": head, "address": asset,
                  "topics": [TRANSFER, topic_addr(seller), None]}, chain)
    out = {}
    for lg in logs:
        try:
            amt = int(lg["data"], 16) / 1e6
        except (ValueError, KeyError, TypeError):
            continue
        to = ("0x" + lg["topics"][2][-40:]).lower()
        e = out.setdefault(to, {"usd": 0.0, "n": 0})
        e["usd"] += amt
        e["n"] += 1
    return out


def analyze(seller, days=7):
    """One seller: who paid it, and how much of that came from wallets it had funded."""
    payers = payers_of(seller, days)
    total_usd = sum(p["usd"] for p in payers.values())
    total_n = sum(p["n"] for p in payers.values())

    sent = funded_wallets(seller)          # one pass, then a set intersection

    rows, circ_usd, circ_n = [], 0.0, 0
    for payer, e in sorted(payers.items(), key=lambda kv: -kv[1]["usd"]):
        # A seller paying itself is the degenerate case and needs no funding edge to be circular.
        if payer == seller.lower():
            rel, funded_usd, funded_n = "self", 0.0, 0
        else:
            f = sent.get(payer)
            rel = "seller_funded" if f else "independent"
            funded_usd, funded_n = (round(f["usd"], 2), f["n"]) if f else (0.0, 0)
        if rel != "independent":
            circ_usd += e["usd"]
            circ_n += e["n"]
        rows.append({"payer": payer, "usd": round(e["usd"], 6), "n": e["n"],
                     "relationship": rel, "funded_usd": funded_usd, "funded_transfers": funded_n})

    return {
        "seller": seller.lower(),
        "window_days": days,
        "receipts_usd": round(total_usd, 6),
        "receipts_n": total_n,
        "payers": len(payers),
        # "at_least" is not decoration. One-hop, USDC-only, bounded lookback: every limitation
        # pushes this number DOWN, so it is a floor and the field name has to say so.
        "at_least_circular_usd": round(circ_usd, 6),
        "at_least_circular_n": circ_n,
        "at_least_circular_share_usd": round(circ_usd / total_usd, 4) if total_usd else 0.0,
        "at_least_circular_share_n": round(circ_n / total_n, 4) if total_n else 0.0,
        "detail": rows,
    }


def main(argv):
    top_n = int(argv[0]) if argv else 15
    days = int(argv[1]) if len(argv) > 1 else 7

    if not DEMAND.exists():
        print(f"need {DEMAND.name}; run demand_sweep.py first")
        return 1
    d = json.loads(DEMAND.read_text(encoding="utf-8"))
    ranked = sorted(d["per_wallet"].items(), key=lambda kv: -kv[1]["n"])[:top_n]

    # RESUMABLE. A seller takes minutes, so a fifteen-seller sweep is a long-running job against
    # rate-limited public endpoints. Losing an hour of completed work to one late failure would
    # make the whole thing not worth starting, so every seller is flushed to disk as it lands
    # and an existing file is treated as work already done.
    done = {}
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
            if prev.get("window_days") == days:
                done = {s["seller"]: s for s in prev.get("sellers", []) if "error" not in s}
        except (json.JSONDecodeError, KeyError, TypeError):
            done = {}          # an unreadable cache is not a reason to refuse to run

    print(f"  top {len(ranked)} sellers by payment count, {days}d receipts, "
          f"{FUNDING_LOOKBACK_DAYS}d funding lookback")
    if done:
        print(f"  resuming: {len(done)} seller(s) already complete in {OUT.name}")
    print()

    def flush(rows):
        OUT.write_text(json.dumps({"window_days": days,
                                   "funding_lookback_days": FUNDING_LOOKBACK_DAYS,
                                   "sellers": rows}, indent=1), encoding="utf-8")

    results = []
    for i, (seller, agg) in enumerate(ranked, 1):
        key = seller.lower()
        if key in done:
            results.append(done[key])
            print(f"  {i:>3}. {seller}  (cached)")
            continue
        t0 = time.time()
        try:
            r = analyze(seller, days)
        except Exception as e:  # noqa: BLE001 - one seller failing must not lose the run
            print(f"  {i:>3}. {seller}  FAILED {type(e).__name__}: {str(e)[:70]}")
            results.append({"seller": key, "error": f"{type(e).__name__}: {e}"})
            flush(results)
            continue
        results.append(r)
        flush(results)
        print(f"  {i:>3}. {seller}   ({time.time()-t0:.0f}s)")
        print(f"       ${r['receipts_usd']:>12,.2f}  {r['receipts_n']:>7} payments  "
              f"{r['payers']:>3} payers")
        print(f"       at least {r['at_least_circular_share_usd']*100:5.1f}% of value and "
              f"{r['at_least_circular_share_n']*100:5.1f}% of count from wallets it funded "
              f"or itself")

    # ALWAYS flush at the end, whatever the mix of fresh and cached was.
    #
    # This line is here because its absence destroyed fourteen sellers. flush() only ran inside
    # the analyze branch, and a cached seller hits `continue` before reaching it. So a run whose
    # only fresh work was the FIRST seller wrote a one-seller file and then appended the other
    # fourteen to `results` in memory and never touched disk again. The printed summary said
    # "15 analysed" and was correct; the file on disk had one. The resume feature that exists to
    # stop long work being lost is exactly what lost it, and it did so silently, because the
    # summary is computed from memory rather than from what was actually written.
    flush(results)

    ok = [r for r in results if "error" not in r]
    failed = len(results) - len(ok)
    tot = sum(r["receipts_usd"] for r in ok)
    circ = sum(r["at_least_circular_usd"] for r in ok)
    print(f"\n  {len(ok)} analysed, {failed} failed")
    if tot:
        print(f"  across them: ${tot:,.2f} received, at least ${circ:,.2f} "
              f"({circ/tot*100:.1f}%) from wallets the seller funded or itself")
    # Never let a partial sweep read as a complete one.
    if failed:
        print(f"  NOTE: {failed} seller(s) failed and are excluded from that share.")
    print(f"  wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
