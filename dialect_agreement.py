"""When a host serves BOTH x402 dialects, do the two agree with each other?

gadaffihub measured on #2953 that 526 hosts (38.6% of those stating terms) emit a v1 body
challenge AND a v2 PAYMENT-REQUIRED header on the same response. Our own census cannot see that
population at all: preflight classifies a host as v1 OR v2, so every one of those 526 was filed
under whichever dialect got noticed first. That is a real blind spot and this file exists because
of his result, not ours.

His finding raises the question neither sweep has asked. "Serves both" is only good news if the
two say the SAME THING. If the body says one price and the header says another, a buyer's total
depends on which dialect its client happens to read, and the seller has no way to notice because
both populations pay something.

So this compares them field by field on hosts that serve both:

  agree       body and header state the same asset, amount, payTo and network
  DISAGREE    at least one of those differs. A v1 buyer and a v2 buyer are quoted differently.
  unknown     one side unparseable, or fields absent on one side and present on the other

Amounts are normalised before comparison because the two dialects legitimately spell the same
value differently: v1 carries `maxAmountRequired`, v2 carries `amount`, and both are atomic
strings. Comparing the raw field names would manufacture disagreements that do not exist.

Read-only. One unpaid request per host.
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
SWEEP = HERE / "sweep_results.json"
OUT = HERE / "dialect_agreement.json"

TIMEOUT = 12
WORKERS = 12
UA = {"user-agent": "verity-measure/1.0 (+https://veritylayer.dev)",
      "content-type": "application/json"}

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# The fields a buyer actually acts on. Anything else differing is cosmetic.
FIELDS = ("asset", "amount", "payTo", "network")


def _first_offer(challenge):
    if not isinstance(challenge, dict):
        return None
    acc = challenge.get("accepts")
    if isinstance(acc, list) and acc and isinstance(acc[0], dict):
        return acc[0]
    # v1 sometimes states terms at the top level rather than in accepts[]
    if any(k in challenge for k in ("maxAmountRequired", "amount", "payTo")):
        return challenge
    return None


# v1 named its networks; v2 uses CAIP-2. Two spellings of one chain, not a disagreement.
# The first run of this file reported 6 disagreements and ALL SIX were this: header eip155:8453
# against body "base". The docstring warned about manufacturing differences out of spelling and
# then the code did it anyway, on a field the warning did not happen to name.
_NETWORK_ALIASES = {
    "base": "eip155:8453", "base-mainnet": "eip155:8453", "8453": "eip155:8453",
    "base-sepolia": "eip155:84532", "84532": "eip155:84532",
    "avalanche": "eip155:43114", "avalanche-fuji": "eip155:43113",
    "iotex": "eip155:4689", "sei": "eip155:1329", "sei-testnet": "eip155:1328",
    "polygon": "eip155:137", "polygon-amoy": "eip155:80002",
}


def _canon_network(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    return _NETWORK_ALIASES.get(s, s)


def _canon_amount(v, decimals=6):
    """Atomic string if we can get one. v1 often states a human price, v2 an atomic integer.

    "$0.01 USDC per call" and "10000" are the same demand at 6 decimals. Treating them as a
    conflict would invent a pricing discrepancy where the seller is being consistent.
    """
    if v is None:
        return None
    s = str(v).strip().lower()
    if s.isdigit():
        return s
    import re
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m:
        return s
    try:
        from decimal import Decimal
        return str(int(Decimal(m.group()) * (10 ** decimals)))
    except Exception:  # noqa: BLE001
        return s


def _norm(offer):
    """Normalise an offer so the two dialects are comparable on MEANING, not spelling."""
    if not isinstance(offer, dict):
        return None
    amount = offer.get("amount")
    if amount is None:
        amount = offer.get("maxAmountRequired")     # v1 spelling of the same atomic value
    asset = offer.get("asset") or offer.get("assetAddress") or offer.get("token")
    return {
        "asset": str(asset).strip().lower() if asset is not None else None,
        "amount": _canon_amount(amount),
        "payTo": (str(offer.get("payTo") or offer.get("payto")
                      or offer.get("recipient") or "").strip().lower() or None),
        "network": _canon_network(offer.get("network") or offer.get("chain")),
    }


def probe(url):
    """Return (header_challenge, body_challenge) from a single unpaid request.

    Takes the RESOURCE URL, not the host. The first version of this probed https://{host}/ and
    returned zero both-dialect hosts out of 400, against gadaffihub's 526. A host root is almost
    never the paid route, so it 402s at nothing and every row files as "not-both". Reporting that
    zero as a contradiction of his number would have been the same error twice in one night.
    """
    req = urllib.request.Request(url, method="POST", data=b"{}", headers=UA)
    try:
        urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX)
        return None, None
    except urllib.error.HTTPError as e:
        if e.code != 402:
            return None, None
        hdr = None
        h = e.headers.get("PAYMENT-REQUIRED") or e.headers.get("payment-required")
        if h:
            try:
                hdr = json.loads(base64.b64decode(h))
            except Exception:  # noqa: BLE001
                try:
                    hdr = json.loads(h)
                except Exception:  # noqa: BLE001
                    hdr = None
        body = None
        try:
            body = json.loads(e.read(200_000))
        except Exception:  # noqa: BLE001
            body = None
        return hdr, body
    except Exception:  # noqa: BLE001
        return None, None


def check(row):
    host = row["host"]
    try:
        hdr, body = probe(row.get("url") or f"https://{host}/")
    except Exception as e:  # noqa: BLE001
        return {"host": host, "verdict": "error", "reason": type(e).__name__}
    if hdr is None or body is None:
        return {"host": host, "verdict": "not-both"}

    h, b = _norm(_first_offer(hdr)), _norm(_first_offer(body))
    if not h or not b:
        return {"host": host, "verdict": "unknown", "reason": "one side had no readable offer"}

    diffs = []
    for f in FIELDS:
        if h[f] is None or b[f] is None:
            continue                       # absent on one side is not a disagreement
        if h[f] != b[f]:
            diffs.append({"field": f, "header": h[f], "body": b[f]})
    compared = [f for f in FIELDS if h[f] is not None and b[f] is not None]
    if not compared:
        return {"host": host, "verdict": "unknown", "reason": "no overlapping fields"}
    return {"host": host, "verdict": "DISAGREE" if diffs else "agree",
            "compared": compared, "diffs": diffs}


def main(argv):
    limit = int(argv[0]) if argv else 400
    rows = json.loads(SWEEP.read_text(encoding="utf-8"))
    hosts = [r for r in rows if r.get("verdict") in ("OK", "V1") and r.get("url")][:limit]
    print(f"  probing {len(hosts)} live payment-gated hosts for BOTH dialects on one response\n")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(check, hosts))
    OUT.write_text(json.dumps({"checked": len(res), "results": res}, indent=1), encoding="utf-8")

    c = Counter(r["verdict"] for r in res)
    for v in ("agree", "DISAGREE", "unknown", "not-both", "error"):
        print(f"   {c.get(v,0):>5}  {v}")

    both = c.get("agree", 0) + c.get("DISAGREE", 0)
    print(f"\n  hosts serving both dialects with comparable terms: {both}")
    if both:
        print(f"  of those, DISAGREEING: {c.get('DISAGREE',0)} "
              f"({c.get('DISAGREE',0)/both*100:.1f}%)")
    dis = [r for r in res if r["verdict"] == "DISAGREE"]
    if dis:
        print("\n  which field disagrees:")
        for f, n in Counter(d["field"] for r in dis for d in r["diffs"]).most_common():
            print(f"   {n:>4}x  {f}")
        print("\n  examples:")
        for r in dis[:5]:
            d = r["diffs"][0]
            print(f"   {r['host'][:40]:<40} {d['field']}: header={str(d['header'])[:24]} "
                  f"body={str(d['body'])[:24]}")
    print(f"\n  wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
