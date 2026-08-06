"""Catalog health: of the listings in a directory, how many can a spec-current buyer pay?

This is the question a catalog operator cannot answer about its own inventory, and the reason is
structural rather than negligent. A catalogue records what a seller CLAIMED at registration.
Payability is a property of what the endpoint DOES right now. Nothing reconciles the two, and
reconciling them means probing every distinct host and knowing what a conformant v2 challenge
looks like.

Currently answers it for the CDP x402 Bazaar, because that is the catalogue we hold in full
(`bazaar_all.json`, harvested by harvest_bazaar.py). The method is catalogue-agnostic: any
directory that exposes its listings can be joined against sweep_results.json the same way.

STATED NARROWLY, because the loose version of this sentence is false and would be the exact
thing this repo exists to refuse:

  A V1 host is NOT broken and its listing is NOT dead. v1 clients pay it perfectly well. The
  only claim is that a buyer implementing the CURRENT spec reads the PAYMENT-REQUIRED header,
  finds nothing there, and moves on. That is a real cost to the catalogue and to the seller,
  and it is much narrower than "broken".

  A NO_402 host may gate a different route or method than the one probed, or be deliberately
  free right now. Counted separately, never merged into the unpayable figure.

CONCENTRATION IS REPORTED ALONGSIDE EVERY COUNT, and that is not decoration. A four-figure
listing count can be one operator with a thousand deployments, which is a completely different
fact from a thousand operators. We nearly shipped that mistake on 2026-08-06: 66 hosts appeared
to fail a spec rule ecosystem-wide and every one of them was a single operator's vercel.app
fleet. Any figure here without its operator count is not reportable.

Read-only, no network: joins two files we already hold.
"""
import json
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
BAZAAR = HERE / "bazaar_all.json"
SWEEP = HERE / "sweep_results.json"
OUT = HERE / "catalog_health.json"

# Verdicts that mean a spec-current buyer cannot construct a payment from what it received.
UNPAYABLE = ("V1", "BLOCKED", "UNPARSEABLE")


def host_of(u):
    try:
        return (urllib.parse.urlsplit(str(u)).hostname or "").lower()
    except ValueError:
        return ""


def registrable(h):
    """Crude eTLD+1. Good enough to count operators, and honest about being crude."""
    p = (h or "").split(".")
    return ".".join(p[-2:]) if len(p) >= 2 else h


def main():
    items = json.loads(BAZAAR.read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("items") or items.get("resources") or []
    sweep = {r["host"]: r for r in json.loads(SWEEP.read_text(encoding="utf-8"))}

    listings_by_host = defaultdict(list)
    for it in items:
        h = host_of(it.get("resource") or it.get("url") or it.get("uri") or "")
        if h:
            listings_by_host[h].append(it)

    covered = {h: v for h, v in listings_by_host.items() if h in sweep}
    n_listings = sum(len(v) for v in covered.values())
    print(f"  catalogue listings held      : {len(items):,}")
    print(f"  distinct hosts behind them   : {len(listings_by_host):,}")
    print(f"  hosts we have probed         : {len(covered):,}"
          f"  ({len(covered)/len(listings_by_host)*100:.1f}% coverage, {n_listings:,} listings)")

    by_verdict = Counter()
    for h, lst in covered.items():
        by_verdict[sweep[h]["verdict"]] += len(lst)
    print("\n  listings by what their host actually does when probed:")
    for v, n in by_verdict.most_common():
        print(f"   {n:>7,}  {v:<16} {n/n_listings*100:5.1f}%")

    affected = {h: lst for h, lst in covered.items() if sweep[h]["verdict"] in UNPAYABLE}
    n_aff = sum(len(v) for v in affected.values())
    operators = {registrable(h) for h in affected}
    print(f"\n  UNPAYABLE BY A SPEC-CURRENT BUYER")
    print(f"   listings : {n_aff:,}  ({n_aff/n_listings*100:.1f}%)")
    print(f"   hosts    : {len(affected):,}")
    print(f"   OPERATORS: {len(operators):,}   <- the number that says whether this is systemic")

    top_op = Counter()
    for h, lst in affected.items():
        top_op[registrable(h)] += len(lst)
    print("\n  most affected operators:")
    for op, n in top_op.most_common(8):
        print(f"   {n:>6,} listings  {op}")
    biggest = top_op.most_common(1)[0][1] if top_op else 0
    if n_aff:
        print(f"\n   largest single operator is {biggest/n_aff*100:.1f}% of the affected listings,")
        print(f"   so this is {'CONCENTRATED, report it as one operator' if biggest/n_aff > 0.5 else 'spread across operators, not one fleet'}")

    notes = Counter()
    for h in affected:
        for nte in (sweep[h].get("notes") or []):
            notes[str(nte)[:74]] += 1
    print("\n  why those hosts fail, by host count:")
    for nte, n in notes.most_common(6):
        print(f"   {n:>4}x  {nte}")

    OUT.write_text(json.dumps({
        "catalogue": "CDP x402 Bazaar",
        "listings_total": len(items),
        "listings_covered": n_listings,
        "hosts_covered": len(covered),
        "hosts_total": len(listings_by_host),
        "by_verdict": dict(by_verdict),
        "unpayable": {"listings": n_aff, "hosts": len(affected), "operators": len(operators)},
        "affected_hosts": sorted(
            ({"host": h, "listings": len(lst), "verdict": sweep[h]["verdict"],
              "notes": sweep[h].get("notes")} for h, lst in affected.items()),
            key=lambda r: -r["listings"]),
    }, indent=1), encoding="utf-8")
    print(f"\n  wrote {OUT.name}")


main()
