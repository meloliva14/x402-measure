"""Is "treat a partial resource entry as a bare pointer" a clarification or a breaking change?

whawk46 asked this directly on #2979 and said he cannot answer it from one deployment: does any
host in the middle state serve partial payment fields that a real client actually depends on? If
so, telling consumers to ignore those fields breaks something that works today.

WHAT CANNOT BE MEASURED, said first because the honest answer starts here. We cannot see other
people's clients. Nothing observable from outside tells us whether anyone is reading a given
host's partial manifest fields. Any claim that "nobody depends on this" would be an assertion
dressed as a measurement, and this file will not make one.

WHAT CAN BE MEASURED, and it bounds the question tightly. A client depending on a partial field
can only be working if that field AGREES with what the host's own 402 actually demands. So:

  agrees      a dependent client would work today, and ignoring the field could break it.
              This is the population whawk46's question is really about.
  disagrees   a dependent client is ALREADY broken, because it would build a payment the host
              rejects. Telling consumers to ignore the field cannot break it further; it fixes
              it. "Treat as bare pointer" is a clarification for these, not a regression.
  unknown     no readable 402 to compare against. Counted separately, never folded into either.

If the disagree column dominates, the rule is safe and the spec can say so with evidence. If the
agree column is large, the rule needs a deprecation path and he should know before it ships.

Read-only. One unpaid probe per host.
"""
import base64
import json
import ssl
import sys
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
MANIFESTS = HERE / "manifests.json"
OUT = HERE / "partial_vs_wire.json"

TIMEOUT = 12
WORKERS = 12
UA = {"user-agent": "verity-measure/1.0 (+https://veritylayer.dev)",
      "content-type": "application/json"}

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def challenge(url):
    req = urllib.request.Request(url, method="POST", data=b"{}", headers=UA)
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX)
        return None
    except urllib.error.HTTPError as e:
        if e.code != 402:
            return None
        h = e.headers.get("PAYMENT-REQUIRED") or e.headers.get("payment-required")
        if h:
            try:
                return json.loads(base64.b64decode(h))
            except Exception:  # noqa: BLE001
                pass
        try:
            return json.loads(e.read(200_000))
        except Exception:  # noqa: BLE001
            return None
    except Exception:  # noqa: BLE001
        return None


def _norm(v):
    return str(v).strip().lower() if v is not None else None


_PATHS = ("/.well-known/x402", "/.well-known/x402.json")


def _offer_with_url(host):
    """Re-fetch the manifest and pair a partial offer with the resource URL it describes.

    The first version of this file probed https://{host}/ and got 119 unknowns out of 205,
    because a host's root is almost never the paid route. The offer and the URL it refers to
    have to travel together or there is nothing to compare the offer against. Returning zero
    decidable rows and calling it "no evidence of breakage" would have been the exact failure
    this repo exists to avoid.
    """
    for path in _PATHS:
        try:
            req = urllib.request.Request(f"https://{host}{path}", headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
                man = json.loads(r.read(400_000))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(man, list):
            man = {"resources": man}
        if not isinstance(man, dict):
            continue
        for key in ("resources", "endpoints", "services", "routes"):
            node = man.get(key)
            vals = (node.values() if isinstance(node, dict)
                    else node if isinstance(node, list) else [])
            for v in vals:
                if not isinstance(v, dict):
                    continue
                url = v.get("resource") or v.get("url") or v.get("path")
                offer = v
                inner = v.get("accepts")
                if isinstance(inner, list) and inner and isinstance(inner[0], dict):
                    offer = inner[0]
                if not url:
                    continue
                if str(url).startswith("/"):
                    url = f"https://{host}{url}"
                if any(offer.get(f) for f in ("payTo", "asset", "network")):
                    return offer, str(url)
    return None, None


def check(row):
    host = row["host"]
    offer, url = _offer_with_url(host)
    if not offer or not url:
        return {"host": host, "verdict": "nothing-actionable"}
    # Only the fields a client could actually act on. A partial entry with none of these is
    # not something anything could depend on, so it is out of scope for the question.
    claimed = {k: offer.get(k) for k in ("payTo", "asset", "network") if offer.get(k)}
    if not claimed:
        return {"host": host, "verdict": "nothing-actionable"}

    ch = challenge(url)
    if not isinstance(ch, dict):
        return {"host": host, "verdict": "unknown", "reason": "no readable 402 at the resource url"}
    acc = (ch.get("accepts") or [{}])
    acc = acc[0] if isinstance(acc, list) and acc and isinstance(acc[0], dict) else {}
    if not acc:
        return {"host": host, "verdict": "unknown", "reason": "402 has no accepts[]"}

    diffs = []
    for field, said in claimed.items():
        live = acc.get(field)
        if live is None:
            continue
        if _norm(said) != _norm(live):
            diffs.append({"field": field, "manifest": said, "wire": live})

    comparable = [f for f in claimed if acc.get(f) is not None]
    if not comparable:
        return {"host": host, "verdict": "unknown", "reason": "no overlapping fields to compare"}
    return {"host": host, "verdict": "disagrees" if diffs else "agrees",
            "compared": comparable, "diffs": diffs}


def safe(row):
    try:
        return check(row)
    except Exception as e:  # noqa: BLE001
        return {"host": row.get("host"), "verdict": "unknown",
                "reason": f"checker error: {type(e).__name__}"}


def main(argv):
    limit = int(argv[0]) if argv else None
    d = json.loads(MANIFESTS.read_text(encoding="utf-8"))
    partial = [r for r in d["results"] if r.get("payable") == "partial"]
    if limit:
        partial = partial[:limit]
    print(f"  {len(partial)} hosts in the middle state the new rule abolishes\n")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(safe, partial))
    OUT.write_text(json.dumps({"checked": len(res), "results": res}, indent=1), encoding="utf-8")

    c = Counter(r["verdict"] for r in res)
    for v in ("agrees", "disagrees", "unknown", "nothing-actionable"):
        print(f"   {c.get(v,0):>4}  {v}")

    decidable = c.get("agrees", 0) + c.get("disagrees", 0)
    if decidable:
        print(f"\n  of the {decidable} we could actually compare:")
        print(f"   {c.get('disagrees',0)/decidable*100:.1f}% already disagree with their own 402, "
              f"so a client depending on them is ALREADY broken")
        print(f"   {c.get('agrees',0)/decidable*100:.1f}% agree, and are the only population "
              f"where 'treat as bare pointer' could regress anything")

    print("\n  which fields disagree:")
    for f, n in Counter(d_["field"] for r in res for d_ in (r.get("diffs") or [])).most_common():
        print(f"   {n:>4}x  {f}")
    print(f"\n  wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
