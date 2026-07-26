"""Do registry-listed sellers ALSO publish a standalone manifest, or are the camps disjoint?

x402 discovery is currently being argued two ways: a standalone `/.well-known/x402`
manifest, versus extending an existing OpenAPI document. The argument is mostly conducted
on design merits. This measures what sellers actually do.

For every distinct host in the CDP Bazaar, ask whether it also serves its own
`/.well-known/x402`. The answer tells you whether a measurement built on one registry can
say anything about the other -- and in practice it can't, which matters to anyone quoting
adoption numbers from a single source.

One request per host. Read-only, no key, no payment.

Run harvest_bazaar.py first. Writes manifest_probe.json.

USAGE
    python manifest_probe.py [max_workers]
"""
import json
import ssl
import sys
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = "x402-measure manifest probe (read-only; no payment sent)"

try:
    items = json.load(open("bazaar_all.json", encoding="utf-8"))
except FileNotFoundError:
    raise SystemExit("bazaar_all.json not found - run: python harvest_bazaar.py")

hosts = sorted({
    it["resource"].split("/")[2] for it in items
    if isinstance(it.get("resource"), str) and it["resource"].startswith("http")
})

workers = int(sys.argv[1]) if len(sys.argv) > 1 else 24
print(f"\n  probing {len(hosts)} Bazaar hosts for a standalone /.well-known/x402\n")


def version_of(d):
    """x402Version can sit at the top level or inside paymentTerms, depending on the author."""
    if not isinstance(d, dict):
        return None
    v = d.get("x402Version")
    if v is None:
        v = (d.get("paymentTerms") or {}).get("x402Version")
    return v


def probe(host):
    url = f"https://{host}/.well-known/x402"
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=12, context=CTX) as r:
            status, body = r.status, r.read(200_000)
    except urllib.error.HTTPError as e:
        return {"host": host, "verdict": "NO_MANIFEST", "http": e.code}
    except Exception:  # noqa: BLE001
        return {"host": host, "verdict": "UNREACHABLE", "http": None}

    if status != 200:
        return {"host": host, "verdict": "NO_MANIFEST", "http": status}
    try:
        d = json.loads(body)
    except Exception:  # noqa: BLE001
        # A 200 that isn't JSON is almost always an SPA index.html catch-all route,
        # not a manifest. Counting it as one would inflate the overlap.
        return {"host": host, "verdict": "NOT_JSON", "http": 200}

    v = version_of(d)
    return {"host": host, "verdict": "MANIFEST", "http": 200,
            "x402Version": v if v is not None else "ABSENT"}


results = []
with ThreadPoolExecutor(max_workers=workers) as ex:
    for i, r in enumerate(ex.map(probe, hosts), 1):
        results.append(r)
        if i % 200 == 0:
            print(f"    {i}/{len(hosts)}")

json.dump(results, open("manifest_probe.json", "w", encoding="utf-8"))

c = Counter(r["verdict"] for r in results)
n = len(results)
print("\n  DOES A BAZAAR-LISTED HOST ALSO SELF-PUBLISH?\n")
for k, v in c.most_common():
    print(f"    {k:<14} {v:>5}   {v / n * 100:5.1f}%")
print(f"\n    TOTAL          {n:>5}")

both = c.get("MANIFEST", 0)
print(f"\n  in BOTH the Bazaar and a standalone manifest : {both} ({both / n * 100:.1f}%)")
print(f"  registry-only (no manifest of their own)     : {n - both} ({(n - both) / n * 100:.1f}%)")

vers = Counter(r.get("x402Version") for r in results if r["verdict"] == "MANIFEST")
if vers:
    print("\n  x402Version declared in those manifests:")
    for k, v in vers.most_common():
        print(f"    {str(k):<10} {v:>5}")

print("\n  -> manifest_probe.json")
