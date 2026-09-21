"""The TXT spellings table, derived from dns_census.json instead of typed by hand.

WHY THIS EXISTS. On x402#2979 the discovery spec's per-row table drifted from the census it cites:
the doc read 2 bare URL / 1 descriptor / 1 url-only / 1 manifest / 2 conforming where the file
reads 1 / 3 / 0 / 1 / 2. The total, 7, was right the whole time, which is exactly why a spot check
passed over it. minia2auk then found the second half of the same defect: the sentence under the
table counts a different unit from the table itself. Three names, two publishing zones, two
distinct record bodies are all defensible counts of the same seven rows, and a number written into
prose by hand drifts again on the next re-run.

So this emits every unit the prose might want, from the file that already holds the answer.

WHAT THE CENSUS CANNOT SETTLE. The walk records names and record strings. It does not observe zone
boundaries, so "two zones" is not derivable from it. The delegation check below is a separate live
DNS query, over the same DNS-over-HTTPS vantage the census used, and it is kept in its own block
with its own date rather than folded into the 2026-08-23 numbers.

Read-only, keyless, free.

Usage: python spellings.py   (writes spellings_<census date>.json)
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
CENSUS = HERE / "dns_census.json"
DOH = "https://dns.google/resolve"

# The spellings, in the order the spec's table lists them. A record belongs to the first class it
# matches; the classes are prefix tests on the record string exactly as published.
CLASSES = [
    ("bare URL", lambda r: r.startswith("https://")),
    ("v=x4021;descriptor=...;url=", lambda r: r.startswith("v=x4021;descriptor=")),
    ("v=x4021;url=", lambda r: r.startswith("v=x4021;url=")),
    ("x402-manifest=", lambda r: r.startswith("x402-manifest=")),
    ("v=x402-1 (conforming)", lambda r: r.startswith("v=x402-1")),
]


def registrable(name):
    """Last two labels. Every name in this census sits under a two-label registrable domain; a
    name under a multi-label public suffix would need the suffix list, and none occurs here."""
    return ".".join(name.split(".")[-2:])


def classify(record):
    for label, test in CLASSES:
        if test(record):
            return label
    return "unclassified"


def doh(name, rtype):
    url = f"{DOH}?name={urllib.parse.quote(name)}&type={rtype}"
    req = urllib.request.Request(url, headers={"accept": "application/dns-json", "User-Agent": "x402-measure"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def delegation_check(names):
    """Is each name its own zone, or a name inside its registrable domain's zone?

    A name is a zone apex if it answers SOA for itself or carries an NS set. Anything else sits
    inside the nearest enclosing zone. Recorded per name with what was actually seen, because a
    claim about zones deserves the query rather than the assumption.

    Both the published name and the `_x402` name under it are checked: the record lives at
    `_x402.<name>`, so a delegation there would put the record in a different zone from its host
    even when the host itself is not an apex."""
    out = {}
    for n in sorted(set(names) | {f"_x402.{n}" for n in names}):
        soa, ns = doh(n, "SOA"), doh(n, "NS")
        soa_here = [a for a in soa.get("Answer", []) if a["type"] == 6 and a["name"].rstrip(".") == n]
        ns_here = [a["data"] for a in ns.get("Answer", []) if a["type"] == 2]
        out[n] = {
            "soa_at_this_name": bool(soa_here),
            "ns_set_at_this_name": sorted(ns_here),
            "is_zone_apex": bool(soa_here) or bool(ns_here),
            "enclosing_registrable_domain": registrable(n),
        }
    return out


def main() -> int:
    d = json.loads(CENSUS.read_text(encoding="utf-8"))
    hits = d["hits"]
    assert all(len(h["records"]) == 1 for h in hits), "a name with two records needs a rule here"
    by_name = {h["name"]: h["records"][0] for h in hits}

    rows = []
    for label, _ in CLASSES:
        names = sorted(n for n, r in by_name.items() if classify(r) == label)
        bodies = {by_name[n] for n in names}
        rows.append({
            "spelling": label,
            "records": len(names),
            "names": names,
            "distinct_record_bodies": len(bodies),
            "registrable_domains": sorted({registrable(n) for n in names}),
        })
    assert sum(r["records"] for r in rows) == d["counts"]["x402-record"] == len(hits)

    shared = {}
    for n, r in by_name.items():
        shared.setdefault(r, []).append(n)
    identical = sorted([sorted(v) for v in shared.values() if len(v) > 1])

    doc = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {
            "file": "dns_census.json",
            "observedAt": d["observedAt"],
            "names_queried": d["queried"],
            "x402_record": d["counts"]["x402-record"],
        },
        "rows": rows,
        "units_over_all_records": {
            "names": len(hits),
            "distinct_record_bodies": len({r for r in by_name.values()}),
            "registrable_domains": len({registrable(n) for n in by_name}),
        },
        "names_sharing_a_byte_identical_record": identical,
        "note": "Every count here is derived from the census file. Pick the unit the sentence means "
                "and read it from this file, so the table and the prose move together on the next re-run.",
    }
    doc["delegation_check"] = {
        "why": "zone boundaries are not in the census; this is a separate live observation",
        "checked_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "resolver": DOH,
        "names": delegation_check(by_name),
    }
    doc["delegation_check"]["zones_holding_the_records"] = sorted({
        n if v["is_zone_apex"] else v["enclosing_registrable_domain"]
        for n, v in doc["delegation_check"]["names"].items()
    })

    out = HERE / f"spellings_{d['observedAt'][:10]}.json"
    out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"  {d['counts']['x402-record']} records over {len(hits)} names, "
          f"{doc['units_over_all_records']['distinct_record_bodies']} distinct record bodies, "
          f"{len(doc['delegation_check']['zones_holding_the_records'])} zones")
    for r in rows:
        print(f"   {r['records']}  {r['spelling']:28} {', '.join(r['names']) or '-'}")
    for group in identical:
        print(f"   identical bodies: {', '.join(group)}")
    print(f"  zones: {', '.join(doc['delegation_check']['zones_holding_the_records'])}")
    print(f"  -> {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
