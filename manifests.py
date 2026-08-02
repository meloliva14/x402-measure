"""Can an agent learn how to pay you by reading your manifest?

`/.well-known/x402.json` is a de facto convention with no agreed schema. This fetches every
host's manifest and asks one question of each: does it carry enough, in a machine-readable
shape, for a buyer to CONSTRUCT a payment without a human reading the page first?

WHY THIS AND NOT preflight.py. preflight reads the 402 challenge, which is the wire truth, and
never looks at the manifest. So a host can publish a manifest that says something completely
different from what it will actually accept and still score OK in our census. We know this is a
real failure mode rather than a hypothetical because WE SHIPPED IT: api.veritylayer.dev
advertised {"asset": "USDC", "price": "0.02"} in its manifest while the wire demanded the USDC
contract address and an atomic amount of "20000". A buyer building from our manifest could not
have signed anything. Found 2026-08-02, fixed the same day. This module is the generalisation of
that bug.

WHAT "PAYABLE FROM THE MANIFEST" MEANS HERE, stated up front because the whole file turns on it.
To build an x402 `exact` payment a buyer needs four things it cannot guess:

    network   which chain, ideally CAIP-2
    asset     the token CONTRACT, not a ticker. "USDC" is not an address and cannot be signed.
    amount    how much, in atomic units, or a price it can convert given known decimals
    payTo     who receives it

A manifest that names three of the four is not 75% payable, it is unpayable. Scoring is
all-or-nothing on purpose.

WHAT THIS DOES NOT CLAIM. A manifest missing payment terms is NOT a broken service. Most of
these hosts are perfectly payable by an agent that simply calls the endpoint and reads the 402,
which is the normal flow and the one the spec actually requires. The finding is narrower and
should always be stated as: discovery-by-manifest does not work on this network, so a cataloguer
or a buyer that wants to survey before spending has nothing to read. Anyone quoting this as
"N hosts are broken" is misreading it.

Read-only, keyless, free. One GET per host.

USAGE
    python manifests.py            # every host in sweep_results.json
    python manifests.py 200        # first 200, for a quick look
"""
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
OUT = HERE / "manifests.json"

TIMEOUT = 12
WORKERS = 12
UA = {"user-agent": "verity-measure/1.0 (+https://veritylayer.dev)"}

# Hosts serve wildly different TLS setups and a handful have expired or mismatched certs. A cert
# error is not the question this module is asking, and refusing to read those manifests would
# silently bias the census toward well-run hosts, which is the direction it must not err in.
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# A ticker is not signable. This list exists so "USDC" is never mistaken for an asset.
_TICKERS = {"usdc", "usdt", "dai", "eth", "weth", "usd", "usdbc"}


def fetch_manifest(host):
    url = f"https://{host}/.well-known/x402.json"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
            raw = r.read(400_000)
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 - unreachable is a result, not a crash
        return None, type(e).__name__
    try:
        return json.loads(raw), None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, f"unparseable JSON ({type(e).__name__})"


def _offers(man):
    """Every payment-bearing object in a manifest, whatever shape it chose.

    Four shapes seen in the wild so far: a top-level accepts[], an endpoints{} map, an
    endpoints[] list, and a resources[] list. Tolerate all of them. A host we cannot parse must
    be reported as unparsed, never scored as clean, so anything unrecognised returns empty and
    lands in its own bucket rather than in "no payment terms".
    """
    if isinstance(man, list):
        man = {"resources": man}
    if not isinstance(man, dict):
        return []
    out = []
    if isinstance(man.get("accepts"), list):
        out += [o for o in man["accepts"] if isinstance(o, dict)]
    for key in ("endpoints", "resources", "services", "routes"):
        node = man.get(key)
        vals = node.values() if isinstance(node, dict) else node if isinstance(node, list) else []
        for v in vals:
            if not isinstance(v, dict):
                continue
            inner = v.get("accepts")
            if isinstance(inner, list) and any(isinstance(o, dict) for o in inner):
                out += [o for o in inner if isinstance(o, dict)]
            else:
                # The offer fields may sit directly on the entry, or one level down in metadata.
                out.append(v)
                meta = v.get("metadata")
                if isinstance(meta, dict):
                    out.append(meta)
    return out


def _first(obj, *names):
    for n in names:
        v = obj.get(n)
        if v not in (None, "", [], {}):
            return v
    return None


def payability(man):
    """Can a buyer construct a payment from this document alone?

    Returns (verdict, missing_fields, evidence). Verdict is one of:
      payable        network + a CONTRACT asset + an amount + payTo, all machine-readable
      partial        some payment fields present, but not enough to sign
      none           no payment fields anywhere
    """
    offers = _offers(man)
    if not offers:
        return "none", ["network", "asset", "amount", "payTo"], {}

    best, best_missing, best_ev = "none", ["network", "asset", "amount", "payTo"], {}
    for o in offers:
        network = _first(o, "network", "chain", "chainId", "caip2")
        asset = _first(o, "asset", "assetAddress", "token", "tokenAddress", "currency")
        amount = _first(o, "amount", "maxAmountRequired", "price", "priceUsd", "cost")
        pay_to = _first(o, "payTo", "payto", "recipient", "address", "receiver")

        ev = {"network": network, "asset": asset, "amount": amount, "payTo": pay_to}
        # A ticker is not an address. This is the exact defect we shipped, so it is checked by
        # SHAPE and not by presence: a value only counts as an asset if it looks like a contract.
        asset_ok = bool(asset) and str(asset).strip().lower() not in _TICKERS \
            and str(asset).strip().startswith("0x")
        missing = [n for n, ok in (("network", bool(network)), ("asset", asset_ok),
                                   ("amount", bool(amount)), ("payTo", bool(pay_to))) if not ok]
        if not missing:
            return "payable", [], ev
        if len(missing) < len(best_missing):
            best, best_missing, best_ev = ("partial" if len(missing) < 4 else "none"), missing, ev
    return best, best_missing, best_ev


def schema_family(man):
    """A crude fingerprint of which invented shape this manifest uses."""
    if isinstance(man, list):
        return "bare-list"
    if not isinstance(man, dict):
        return "not-an-object"
    keys = set(man)
    ver = "x402Version" if "x402Version" in keys else "version" if "version" in keys else "no-version"
    container = next((k for k in ("accepts", "endpoints", "resources", "services", "routes")
                      if k in keys), "none")
    return f"{ver}+{container}"


def check(host):
    man, err = fetch_manifest(host)
    if man is None:
        return {"host": host, "served": False, "error": err}
    verdict, missing, ev = payability(man)
    return {"host": host, "served": True, "family": schema_family(man),
            "top_keys": sorted(man)[:8] if isinstance(man, dict) else ["(list)"],
            "payable": verdict, "missing": missing, "evidence": ev}


def main(argv):
    limit = int(argv[0]) if argv else None
    rows = json.loads(SWEEP.read_text(encoding="utf-8"))
    hosts = sorted({r["host"] for r in rows if r.get("host")})
    if limit:
        hosts = hosts[:limit]
    print(f"  fetching /.well-known/x402.json from {len(hosts)} hosts\n")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(check, hosts))

    served = [r for r in res if r["served"]]
    payable = [r for r in served if r["payable"] == "payable"]
    partial = [r for r in served if r["payable"] == "partial"]
    none_ = [r for r in served if r["payable"] == "none"]

    OUT.write_text(json.dumps({"hosts": len(res), "results": res}, indent=1), encoding="utf-8")

    print(f"  serve a manifest at all      : {len(served)}/{len(res)}")
    print(f"  PAYABLE from the manifest    : {len(payable)}")
    print(f"  partial (some fields, unsignable): {len(partial)}")
    print(f"  no payment terms at all      : {len(none_)}")
    if served:
        print(f"\n  -> {len(payable)/len(served)*100:.1f}% of manifest-serving hosts publish "
              f"enough for a buyer to construct a payment")

    print("\n  schema families (each is somebody's invention):")
    for fam, n in Counter(r["family"] for r in served).most_common(10):
        print(f"   {n:>4}x  {fam}")

    print("\n  what the partial ones are missing:")
    for field, n in Counter(f for r in partial for f in r["missing"]).most_common():
        print(f"   {n:>4}x  {field}")

    print(f"\n  wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
