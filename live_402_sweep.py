"""Send ONE live request to every distinct host in the Bazaar and record what it really serves.

The registry is a list of claims. This measures reality: is the host up, does it still
return a 402, is that challenge v1 or v2, and could a stock @x402/evm 2.x buyer sign it?

Deliberately conservative:
  - exactly ONE request per host. This is not a crawler.
  - honest User-Agent
  - a host that times out is recorded UNREACHABLE, never "broken"
  - non-EVM is set aside, not counted as a failure
  - nothing is signed and no payment is ever sent

Run harvest_bazaar.py first. Writes sweep_results.json.

USAGE
    python live_402_sweep.py [max_workers]
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

from preflight import classify

try:
    items = json.load(open("bazaar_all.json", encoding="utf-8"))
except FileNotFoundError:
    raise SystemExit("bazaar_all.json not found - run: python harvest_bazaar.py")

# One representative route per host: the shortest path, usually the simplest to call.
by_host = {}
for it in items:
    res = it.get("resource")
    if not isinstance(res, str) or not res.startswith("http"):
        continue
    host = res.split("/")[2]
    if host not in by_host or len(res) < len(by_host[host]):
        by_host[host] = res

targets = sorted(by_host.items())
workers = int(sys.argv[1]) if len(sys.argv) > 1 else 24
print(f"\n  sweeping {len(targets)} distinct hosts, one live request each\n")


def one(pair):
    host, url = pair
    verdict, notes, _ = classify(url)
    return {"host": host, "url": url, "verdict": verdict, "notes": notes}


results = []
with ThreadPoolExecutor(max_workers=workers) as ex:
    for i, r in enumerate(ex.map(one, targets), 1):
        results.append(r)
        if i % 100 == 0:
            print(f"    {i}/{len(targets)}")

json.dump(results, open("sweep_results.json", "w", encoding="utf-8"))

from collections import Counter  # noqa: E402 - kept local to the reporting step

counts = Counter(r["verdict"] for r in results)
print("\n  LIVE RESULT, one route per host:\n")
for k, n in counts.most_common():
    print(f"    {k:<16} {n:>5}   {n / len(results) * 100:5.1f}%")
print(f"\n    TOTAL            {len(results):>5}")
print("\n  -> sweep_results.json")
