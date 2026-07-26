"""Pull every resource listed in the CDP x402 Bazaar.

Writes three files:
    bazaar_all.json    every listing, verbatim
    paytos.json        {payTo address -> [hosts advertising it]}
    harvest_meta.json  provenance: when, reported total, collected, whether complete

What the registry says a seller accepts is a CLAIM. What the endpoint serves right now is
a FACT, and they are not always the same. live_402_sweep.py collects the second.

Read-only, no key, no payment.

TWO SAMPLING HAZARDS, BOTH LEARNED THE HARD WAY. Read before quoting any number from this.

1. A SHORT PAGE IS NOT THE END. An earlier version stopped at the first page returning fewer
   than `limit` rows. The API emits short pages mid-run, so that silently truncated a sweep
   to 8,200 of 14,365 listings (57%) while reporting success, and figures derived from it
   were published before anyone noticed. Only an empty batch or reaching `total` ends the
   sweep now; an incomplete run warns loudly and records it in harvest_meta.json.

2. EVEN A COMPLETE SWEEP IS A SAMPLE, NOT AN ENUMERATION. Offset pagination over a registry
   that changes while you page it cannot guarantee coverage — rows shift across page
   boundaries between requests. Measured directly: 13 hosts present in one run were absent
   from a complete run a day later while still serving live manifests. Cite the timestamp,
   keep prior runs, and prefer a union across runs when the question is "does X exist" rather
   than "what share of the registry is X".

USAGE
    python harvest_bazaar.py [max_pages]
"""
import datetime
import json
import sys
import urllib.request

BASE = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"
PAGE = 200


def fetch_all(max_pages=60):
    items = []
    total = None
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
        # NOTE: do NOT stop on a short page. The API returns short pages mid-run, and
        # treating one as end-of-data silently truncated an earlier harvest to 57% of the
        # registry (8,200 of 14,365) — which then propagated into published figures.
        # Only an empty batch or reaching `total` ends the sweep.
    if total and len(items) < total:
        print(f"  !! WARNING: collected {len(items)} of {total} — sweep is INCOMPLETE. "
              "Do not publish figures derived from this run.")
    return items, total


def main():
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    items, reported_total = fetch_all(max_pages)
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

    complete = bool(reported_total) and len(items) >= reported_total
    meta = {
        "collected_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "registry_reported_total": reported_total,
        "collected": len(items),
        "complete": complete,
        "distinct_hosts": len(hosts),
        "distinct_paytos": len(paytos),
        "caveat": ("Offset pagination over a live registry is a snapshot, not an enumeration. "
                   "Rows shift between requests; hosts present in one run can be absent from "
                   "the next. Quote this timestamp alongside any figure derived from this run."),
    }
    with open("harvest_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"\n  {len(items)} resources" + ("" if complete else "   <-- INCOMPLETE"))
    print(f"  {len(hosts)} distinct hosts")
    print(f"  {len(paytos)} distinct EVM payTo wallets")
    print("\n  -> bazaar_all.json, paytos.json, harvest_meta.json")


if __name__ == "__main__":
    main()
