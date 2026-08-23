"""Does anyone publish an `_x402` DNS TXT pointer? A census, not a spot-check.

whawk46 probed about a dozen named hosts on #2979, found none, and asked for a real number
rather than "none I could find". This is that number.

THE CONTROL IS THE POINT OF THIS FILE. A DNS probe that is silently broken returns zero, and
zero is exactly the answer we expect, so the measurement and the failure are indistinguishable
without a positive control. Reporting "nobody publishes this" off an untested resolver would be
the worst kind of confident wrong: it would be used to argue that the `.well-known` half is
carrying the whole extension.

So before reporting any zero, this asserts:

  1. the resolver returns TXT records for a domain that definitely has them, and
  2. the resolver returns NXDOMAIN-ish empty for a name that definitely does not exist,

and it refuses to print a result if either control fails.

Uses DNS-over-HTTPS so it needs no resolver library and behaves the same everywhere. Queries the
registrable domain (`_x402.example.com`), which is what the spec's TXT pointer is defined on, and
also the full host, since a subdomain deployment could put it there.

Read-only, keyless, free.
"""
import json
import ssl
import sys
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
SWEEP = HERE / "sweep_results.json"
OUT = HERE / "dns_census.json"

DOH = "https://dns.google/resolve"
TIMEOUT = 10
WORKERS = 16

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def txt(name):
    """TXT records for a name. Returns (records, error). None records means the query failed."""
    url = f"{DOH}?name={urllib.parse.quote(name)}&type=TXT"
    req = urllib.request.Request(url, headers={"accept": "application/dns-json",
                                               "user-agent": "verity-measure/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
            d = json.loads(r.read(200_000))
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__
    # type 16 = TXT. The Answer array also carries the CNAME chase (type 5) when the queried
    # name is an alias, and a CNAME target is not a TXT record. Unfiltered, every wildcard-CNAME
    # platform name (onrender, vercel) reads as "label occupied", which is a false positive the
    # old substring filter was accidentally hiding.
    return [a.get("data", "").strip('"')
            for a in (d.get("Answer") or []) if a.get("type") == 16], None


def registrable(h):
    p = (h or "").lower().strip(".").split(".")
    return ".".join(p[-2:]) if len(p) >= 2 else h


def controls_pass():
    """Refuse to report a zero unless the resolver demonstrably works in both directions."""
    pos, err1 = txt("google.com")
    if err1 or not pos:
        print(f"  CONTROL FAILED: resolver returned nothing for google.com TXT ({err1})")
        return False
    neg, err2 = txt("this-name-should-not-exist-verity-8f3a1c.example")
    if err2:
        print(f"  CONTROL FAILED: negative lookup errored ({err2})")
        return False
    if neg:
        print(f"  CONTROL FAILED: a nonexistent name returned records: {neg[:1]}")
        return False
    print(f"  controls pass: google.com TXT -> {len(pos)} records, "
          f"nonexistent name -> 0 records")
    return True


def grade(rec: str) -> str:
    """Version-token grade only. Full grammar conformance is the spec's job, not this file's:
    'conforming-version' means the record opens with the document's exact token, nothing more."""
    r = rec.strip().lower()
    if r.startswith("v=x402-1"):
        return "conforming-version"
    if r.startswith("v=x402"):
        return "near-miss-version"          # v=x4021 and friends: token present, wrong spelling
    return "no-version-token"               # bare URLs, x402-manifest=, wk=-only, ...


def check(name):
    recs, err = txt("_x402." + name)
    if err:
        return {"name": name, "status": "query-failed", "error": err}
    recs = [r for r in (recs or []) if r]
    # Two classes of occupied label, and conflating them was this file's 2026-08-23 bug in both
    # directions at once. Until then check() filtered on the substring "v=x402", which (a) threw
    # away every x402 attempt with no version token -- bare URLs, x402-manifest= -- exactly the
    # near-misses this census was cited as evidence about, and (b) hid that txt() was not
    # filtering DoH answers to type 16, so CNAME chases would have counted as records. Found
    # because novadyne-hq's independent walk on #2979 saw records at two names this census had
    # queried and reported empty. Fixing the filter then surfaced a third population: wildcard
    # TXT (SPF, site-verification, registrar parking) that answers at ANY label, x402 included.
    # Spot-checked by querying garbage labels: those zones answer there too. So the split is by
    # content -- an _x402 label carrying a record that never mentions x402 is incidental DNS
    # hygiene, not an attempt at this convention, and counting it as one would be a new lie.
    intent = [r for r in recs if "x402" in r.lower()]
    if intent:
        return {"name": name, "status": "x402-record", "records": intent,
                "grades": [grade(r) for r in intent]}
    if recs:
        return {"name": name, "status": "incidental-txt", "records": recs[:3]}
    return {"name": name, "status": "no-record"}


def main(argv):
    if not controls_pass():
        print("\n  Refusing to report. A broken resolver and an empty network look identical.")
        return 1

    rows = json.loads(SWEEP.read_text(encoding="utf-8"))
    hosts = sorted({r["host"] for r in rows if r.get("host")})
    domains = sorted({registrable(h) for h in hosts})
    limit = int(argv[0]) if argv else None
    if limit:
        domains, hosts = domains[:limit], hosts[:limit]

    # Named hosts whawk46 checked by hand, plus the ones the spec/ecosystem would most expect.
    extra = ["x402.org", "api.cdp.coinbase.com", "facilitator.x402.rs", "x402.rs",
             "proxy402.com", "neynar.com", "heurist.ai", "openrouter.ai", "x402atlas.com",
             "glassnode.com", "x402.glassnode.com", "coinbase.com"]
    targets = sorted(set(domains) | set(hosts) | set(extra))
    print(f"\n  querying _x402 TXT on {len(targets):,} names "
          f"({len(domains):,} registrable domains + {len(hosts):,} full hosts + {len(extra)} named)\n")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(check, targets))

    c = Counter(r["status"] for r in res)
    for s, n in c.most_common():
        print(f"   {n:>6,}  {s}")

    hits = [r for r in res if r["status"] == "x402-record"]
    print(f"\n  PUBLISH AN _x402 RECORD: {len(hits)}")
    for h in hits[:20]:
        print(f"   {h['name']}  {h['records'][:1]}")
    if not hits:
        print("   none, and the controls above are why that zero is reportable")

    # observedAt: this file previously carried no date, which is the exact stamping failure
    # the #2979 thread is about -- two counts of a moving surface are not comparable without it.
    import datetime as _dt
    OUT.write_text(json.dumps({"observedAt": _dt.datetime.now(_dt.timezone.utc)
                                   .strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "queried": len(targets), "controls": "passed",
                               "counts": dict(c), "hits": hits,
                               "incidental": [r for r in res
                                              if r["status"] == "incidental-txt"]},
                              indent=1), encoding="utf-8")
    print(f"\n  wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
