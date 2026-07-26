"""Pull every resource listed in the CDP x402 Bazaar.

Writes two files the other scripts consume:
    bazaar_all.json   every listing, verbatim
    paytos.json       {payTo address -> [hosts advertising it]}

What the registry says a seller accepts is a CLAIM. What the endpoint serves right now is
a FACT, and they are not always the same. live_402_sweep.py collects the second.

Read-only, no key, no payment.

USAGE
    python harvest_bazaar.py [max_pages]
"""
import json
import sys
import urllib.request

BASE = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"
PAGE = 200


def fetch_all(max_pages=60):
    items = []
    for page in range(max_pages):
        url = f"{BASE}?limit={PAGE}" + (f"&offset={len(items)}" if items else "")
        req = urllib.request.Request(url, headers={"User-Agent": "x402-measure"})
        with urllib.request.urlopen(req, timeout=45) as r:
            d = json.loads(r.read().decode("utf-8"))
        batch = d.get("items") or []
        if not batch:
            break
        items.extend(batch)
        total = (d.get("pagination") or {}).get("total")
        print(f"  page {page + 1}: +{len(batch)}  (have {len(items)}"
              + (f" of {total}" if total else "") + ")")
        if total and len(items) >= total:
            break
        if len(batch) < PAGE:
            break
    return items


def main():
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    items = fetch_all(max_pages)
    with open("bazaar_all.json", "w", encoding="utf-8") as f:
        json.dump(items, f)

    hosts, paytos = {}, {}
    for it in items:
        res = it.get("resource")
        if not isinstance(res, str) or not res.startswith("http"):
            continue
        host = res.split("/")[2]
        hosts.setdefault(host, 0)
        hosts[host] += 1
        for a in (it.get("accepts") or []):
            p = a.get("payTo")
            if isinstance(p, str) and p.startswith("0x") and len(p) == 42:
                paytos.setdefault(p.lower(), set()).add(host)

    with open("paytos.json", "w", encoding="utf-8") as f:
        json.dump({p: sorted(v) for p, v in paytos.items()}, f)

    print(f"\n  {len(items)} resources")
    print(f"  {len(hosts)} distinct hosts")
    print(f"  {len(paytos)} distinct EVM payTo wallets")
    print("\n  -> bazaar_all.json, paytos.json")


if __name__ == "__main__":
    main()
