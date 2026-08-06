"""Do the already-bare pointers really stay conforming under the revised wording?

whawk46 wrote the bare-pointer rule intending it to be a no-op for hosts that publish no payment
fields, and asked to be told if he failed at that.

There is a trap in the assumption, and it has nothing to do with payment fields. The revised
`resources` wording adds: each entry's `url` MUST be HTTPS and on the manifest's own domain or a
subdomain, and consumers MUST NOT dereference entries that are not. A host with no payment data
at all can still fail that, in which case the rule is not a no-op for it.

Re-fetches the manifests rather than reasoning from what the census retained. A host we cannot
re-read is counted unknown, never as passing.
"""
import json
import ssl
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

MAN = r"G:\VERITY\x402-measure\manifests.json"
PATHS = ("/.well-known/x402", "/.well-known/x402.json")
UA = {"user-agent": "verity-measure/1.0 (+https://veritylayer.dev)"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def registrable(h):
    p = (h or "").lower().strip(".").split(".")
    return ".".join(p[-2:]) if len(p) >= 2 else h


def fetch(host):
    for path in PATHS:
        try:
            req = urllib.request.Request(f"https://{host}{path}", headers=UA)
            with urllib.request.urlopen(req, timeout=10, context=CTX) as r:
                return json.loads(r.read(400_000))
        except Exception:  # noqa: BLE001
            continue
    return None


def urls_of(man):
    out = []
    if isinstance(man, list):
        man = {"resources": man}
    if not isinstance(man, dict):
        return out
    for key in ("resources", "endpoints", "services", "routes"):
        node = man.get(key)
        vals = node.values() if isinstance(node, dict) else node if isinstance(node, list) else []
        for v in vals:
            if isinstance(v, dict):
                u = v.get("resource") or v.get("url")
                if u:
                    out.append(str(u))
    return out


def check(host):
    man = fetch(host)
    if man is None:
        return {"host": host, "verdict": "unknown-unreachable"}
    urls = urls_of(man)
    if not urls:
        # No entries at all. Nothing for the resources rule to bite on: a true no-op.
        return {"host": host, "verdict": "noop-no-entries"}
    bad = []
    for u in urls:
        if u.startswith("/"):
            continue                      # relative, resolves in-domain by construction
        try:
            h = (urllib.parse.urlsplit(u).hostname or "").lower()
        except ValueError:
            bad.append(("unparseable", u))
            continue
        if not u.startswith("https://"):
            bad.append(("not-https", u))
        elif not (h == host.lower() or h.endswith("." + registrable(host))):
            bad.append(("out-of-domain", u))
    return {"host": host, "verdict": "VIOLATES" if bad else "noop-conforming",
            "entries": len(urls), "bad": bad[:3]}


def main():
    d = json.load(open(MAN, encoding="utf-8"))
    bare = [r["host"] for r in d["results"] if r.get("payable") == "none" and r.get("served")]
    print(f"  re-checking {len(bare)} hosts that publish a manifest with NO payment fields\n")
    with ThreadPoolExecutor(max_workers=14) as ex:
        res = list(ex.map(check, bare))

    c = Counter(r["verdict"] for r in res)
    for v, n in c.most_common():
        print(f"   {n:>4}  {v}")

    viol = [r for r in res if r["verdict"] == "VIOLATES"]
    decided = c.get("noop-conforming", 0) + c.get("noop-no-entries", 0) + len(viol)
    print(f"\n  decidable: {decided}   unknown: {c.get('unknown-unreachable',0)}")
    if decided:
        print(f"  -> the rule is a genuine no-op for {decided-len(viol)} of {decided} "
              f"({(decided-len(viol))/decided*100:.1f}%)")
    if viol:
        print(f"\n  {len(viol)} would NOT be a no-op. Reasons:")
        for why, n in Counter(b[0] for r in viol for b in r["bad"]).most_common():
            print(f"   {n:>4}x  {why}")
        for r in viol[:5]:
            print(f"   {r['host'][:44]:<44} {r['bad'][0][0]}: {str(r['bad'][0][1])[:58]}")


main()
