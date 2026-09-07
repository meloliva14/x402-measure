"""How do manifests at /.well-known/x402 name the networks they accept?

Written for the wg-domain-discovery discussion of an `x402Versions` array nested inside
`acceptedNetworks`. That shape presumes a container key the ecosystem agrees on. Over the
pinned census population it does not: the same idea is spelled many different ways, and
`acceptedNetworks` is one of the rarest.

Two separate things get measured, because they answer differently:
  1. Does the host serve a parseable JSON manifest at /.well-known/x402 at all.
  2. Does that manifest name networks under ANY key, and under which spelling.

A key counts as network-declaring when its name mentions network/chain/accepts. Asset-only
and prose keys (assetSymbol, payment_networks_description) are excluded, so this is a
LOWER BOUND on hosts declaring networks: a manifest burying them under an idiosyncratic
name this filter does not catch is missed.

A live re-probe drifts by a few hosts between runs (timeouts, 502s), so the count is dated
rather than quoted flat.

Usage: python manifest_keys.py [snapshot-date]   (defaults to the latest snapshot)
Writes manifest_keys_<snapshot>.json
"""
import json
import re
import ssl
import sys
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = {"user-agent": "verity-measure/1.0 (+https://veritylayer.dev)"}
NET = re.compile(r"network|chain|accepts?$|acceptednetworks", re.I)
SKIP = ("asset", "description")


def fetch(host: str):
    try:
        req = urllib.request.Request(f"https://{host}/.well-known/x402", headers=UA)
        with urllib.request.urlopen(req, timeout=12, context=CTX) as r:
            if r.status != 200:
                return None
            return (host, json.loads(r.read(300_000)))
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else sorted(p.name for p in SNAPSHOTS.iterdir())[-1]
    obs = json.load(open(SNAPSHOTS / day / "observation.json", encoding="utf-8"))["observations"]
    hosts = sorted({r["host"] for r in obs})

    docs = []
    with ThreadPoolExecutor(max_workers=24) as ex:
        for f in as_completed([ex.submit(fetch, h) for h in hosts]):
            got = f.result()
            if got and isinstance(got[1], dict):
                docs.append(got)

    spellings = Counter()
    declaring = set()
    for host, doc in docs:
        keys = [k for k in doc if NET.search(k) and not any(s in k.lower() for s in SKIP)]
        if keys:
            declaring.add(host)
            spellings.update(keys)

    out = {
        "snapshot": day,
        "population": len(hosts),
        "manifests_parsed": len(docs),
        "declaring_networks": len(declaring),
        "distinct_spellings": len(spellings),
        "accepted_networks_exactly": spellings.get("acceptedNetworks", 0),
        "spellings": dict(spellings.most_common()),
    }
    dest = HERE / f"manifest_keys_{day}.json"
    json.dump(out, open(dest, "w"), indent=1)
    print(f"population {len(hosts)}  manifests {len(docs)}  declaring {len(declaring)}"
          f"  spellings {len(spellings)}  acceptedNetworks {out['accepted_networks_exactly']}")
    print(f"-> {dest.name}")


if __name__ == "__main__":
    main()
