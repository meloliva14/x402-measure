"""How many x402 sellers have actually been paid?

live_402_sweep.py measures supply: can these endpoints take money at all. This measures
the other half -- of the payTo wallets those hosts advertise, how many received any USDC
in the window, how much, and from how many distinct payers.

Read-only, keyless, free. Aggregates counters only; never holds the whole log set in memory.
A range the RPC refuses is SPLIT rather than skipped: a silently dropped range would
understate payments and overstate "never paid", which is precisely the direction a claim
like this must not err in.

Run harvest_bazaar.py first. Writes demand_results.json.

WHY THIS AND NOT THE PER-ADDRESS API. ecosystem_revenue.py asks Blockscout for each wallet's
transfer history, and that endpoint pages: on 2026-08-16 it returned a first page for 239 of 379
wallets and stopped, so its $42,019.73 total was a floor with no way to know how deep. Paginating
it is not the fix either, because the busiest seller wallet alone carries on the order of a
million transfers. Scanning blocks answers the same question exactly, in one pass, because a
window of blocks is finite where an address's history is not.

USAGE
    python demand_sweep.py [days] [wallet-file]
      days         default 7
      wallet-file  default paytos.json (registry-advertised). Pass payto_wallets.json to use
                   the addresses actually returned by live 402s instead.
"""
import collections
import json
import statistics
import sys
import time

from rpc import USDC, TRANSFER, rpc, topic_addr, blocks_for_days

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
SRC = sys.argv[2] if len(sys.argv) > 2 else "paytos.json"
CHUNK = 3000

try:
    pay = json.load(open(SRC, encoding="utf-8"))
except FileNotFoundError:
    raise SystemExit(f"{SRC} not found - run: python harvest_bazaar.py")

# paytos.json is a dict keyed by address; payto_wallets.json is a list of {"payTo": ...}.
# Accept either so the demand figure can be quoted against the same population as the rest
# of the census rather than against a different one.
if isinstance(pay, dict):
    addrs = sorted(pay)
else:
    addrs = sorted({(r.get("payTo") or "").lower() for r in pay if r.get("payTo")})
if not addrs:
    raise SystemExit(f"no addresses found in {SRC}")

# The null address is a BURN destination, not a seller wallet, and counting transfers into it
# as revenue is catastrophic rather than merely wrong: a 30-day scan on 2026-08-17 attributed
# $3,109,683,234 of USDC burns to "seller revenue", which was 99.98% of the total and made the
# top wallet read as 100% of the network. It is in the census legitimately, because
# agents.sayerandstone.com really does serve it as its payTo, so the fix belongs here at the
# revenue layer and NOT in the census, which is supposed to record what a host actually served.
BURN = {"0x" + "0" * 40, "0x" + "0" * 39 + "1", "0x" + "d" * 40}
burned = [a for a in addrs if a.lower() in BURN]
if burned:
    print(f"  excluding {len(burned)} burn address(es) from the revenue population: "
          + ", ".join(burned))
    print("  (they are still real payTo values and stay in the census; they are just not"
          " destinations anyone gets paid at)")
    addrs = [a for a in addrs if a.lower() not in BURN]
topics = [topic_addr(a) for a in addrs]
start, head = blocks_for_days(DAYS)
print(f"\n  {len(addrs)} seller wallets from {SRC} | blocks {start}..{head} ({DAYS}d)\n")

count = collections.Counter()
total = collections.defaultdict(float)
payers = collections.defaultdict(set)
n_logs = 0
covered = 0


def scan(lo, hi, depth=0):
    global n_logs, covered
    try:
        logs = rpc("eth_getLogs", [{
            "fromBlock": hex(lo), "toBlock": hex(hi),
            "address": USDC, "topics": [TRANSFER, None, topics],
        }])
    except Exception as e:  # noqa: BLE001
        if hi - lo < 40 or depth > 12:
            print(f"    !! gave up on {lo}..{hi}: {str(e)[:60]}")
            return
        mid = (lo + hi) // 2
        scan(lo, mid, depth + 1)
        scan(mid + 1, hi, depth + 1)
        return
    for lg in logs:
        to = "0x" + lg["topics"][2][-40:]
        count[to] += 1
        total[to] += int(lg["data"], 16) / 1e6      # USDC has 6 decimals
        payers[to].add("0x" + lg["topics"][1][-40:])
    n_logs += len(logs)
    covered += hi - lo + 1


t0 = time.time()
frm = start
while frm <= head:
    to = min(frm + CHUNK - 1, head)
    scan(frm, to)
    frm = to + 1
    done, span = frm - start, head - start
    if done % (CHUNK * 25) < CHUNK:
        print(f"    {done / span * 100:5.1f}%  {n_logs:>9,} payments  "
              f"{len(count):>4} wallets paid  {time.time() - t0:5.0f}s")

paid = len(count)
never = len(addrs) - paid
print(f"\n  blocks covered : {covered:,} of {head - start + 1:,}")
print(f"  payments seen  : {n_logs:,}")
print(f"\n  PAID at least once : {paid:>5} of {len(addrs)}  ({paid / len(addrs) * 100:.1f}%)")
print(f"  NEVER paid         : {never:>5} of {len(addrs)}  ({never / len(addrs) * 100:.1f}%)")

grand = sum(total.values())
ranked = sorted(((v, k) for k, v in total.items()), reverse=True)
print(f"\n  total USDC into all seller wallets: ${grand:,.2f}")
if ranked:
    top1 = ranked[0][0] / grand * 100
    top5 = sum(v for v, _ in ranked[:5]) / grand * 100
    print(f"  concentration: top wallet {top1:.1f}% | top 5 {top5:.1f}%")
    biggest = ranked[0][1]
    print(f"  busiest wallet by count: {count.most_common(1)[0][1]:,} payments")
    print(f"  largest wallet avg/payment: ${total[biggest] / count[biggest]:,.4f}"
          "   <- if this is retail-sized, that wallet is taking non-x402 USDC too")

vals = [total[a] for a in count] + [0.0] * never
print(f"\n  median seller, {DAYS}d      : ${statistics.median(vals):.4f}")
if count:
    print(f"  median PAID seller, {DAYS}d : ${statistics.median([total[a] for a in count]):.4f}")
for t in (1, 10, 100, 1000):
    n = sum(1 for x in vals if x < t)
    print(f"    earned < ${t:<6,} : {n:>5} of {len(addrs)}  ({n / len(addrs) * 100:.1f}%)")

if count:
    p = [len(payers[a]) for a in count]
    print(f"\n  median distinct payers per paid wallet : {statistics.median(p):.0f}")
    print(f"  paid wallets with exactly one payer    : {sum(1 for x in p if x == 1)}")

json.dump({
    "days": DAYS, "wallets": len(addrs), "paid": paid, "never": never,
    "payments": n_logs, "total_usdc": grand,
    "per_wallet": {a: {"n": count[a], "usd": total[a], "payers": len(payers[a])} for a in count},
}, open("demand_results.json", "w", encoding="utf-8"))
print("\n  -> demand_results.json")
