#!/usr/bin/env python3
"""Which network identifiers do live 402 challenges carry, and how many fit CAIP-2's own pattern?

WHY THIS EXISTS. A review of wg-domain-discovery PR #4 (OpenAPI publication) proposes widening the
annotation schema's network pattern from CAIP-2's `[-_a-zA-Z0-9]{1,32}` reference to 64 characters,
on the premise that Solana MainNet's CAIP-2 id carries the 44-character genesis hash. The schema's
pattern is CAIP-2's own, and the Solana namespace profile truncates the genesis hash to its first 32
characters. What deployed sellers actually put on the wire is a measurement, not an argument, so
this counts it.

METHOD. The census's own population and fetch, exactly as wire_version.py uses them: every host in
the latest signed snapshot at its pinned URL, fetched with preflight.get_402_traced (GET, then POST
when the GET does not produce a challenge, no POST after a 429, the SSRF fence). The challenge is
read from the PAYMENT-REQUIRED header first and the body second, as a v2 client reads it. Every
`network` value in accepts[] is recorded per host. "Fits CAIP-2" means the value matches
^[-a-z0-9]{3,8}:[-_a-zA-Z0-9]{1,32}$, the pattern CAIP-2 itself gives.

WHAT THIS DOES NOT CLAIM. A value that does not fit CAIP-2 is not necessarily broken for its own
buyers: v1 bare names such as `base` are a different, older vocabulary. Counts are hosts, not
payments, and a host that serves several networks is counted under each.

Read-only. No wallet, no key, no payment.

Usage: python network_ids.py
Writes network_ids_<UTC date>.json
"""
import collections
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import preflight

HERE = Path(__file__).parent
SNAP = HERE / "snapshots"
WORKERS = 14   # the census's own concurrency (snapshot.py)
CAIP2 = re.compile(r"^[-a-z0-9]{3,8}:[-_a-zA-Z0-9]{1,32}$")


def population():
    days = sorted(p.name for p in SNAP.iterdir() if p.name[:2] == "20")
    obs = json.loads((SNAP / days[-1] / "observation.json").read_text(encoding="utf-8"))["observations"]
    return [{"host": r["host"], "url": r["url"]} for r in obs], f"every host in the signed snapshot of {days[-1]}"


def read(row):
    out = {"host": row["host"], "url": row["url"]}
    try:
        status, headers, body, trace = preflight.get_402_traced(row["url"])
    except Exception as e:  # noqa: BLE001 - unreachable is a result, not a crash
        out.update(status=None, error=type(e).__name__)
        return out
    out["status"] = status
    if status != 402:
        return out
    hdr, bod = preflight.parse_challenge(headers, body)
    ch, where = (hdr, "header") if isinstance(hdr, dict) else ((bod, "body") if isinstance(bod, dict) else (None, None))
    accepts = ch.get("accepts") if ch else None
    if not isinstance(accepts, list) or not accepts:
        out["accepts"] = False
        return out
    nets = [a.get("network") for a in accepts if isinstance(a, dict) and a.get("network") is not None]
    out.update(accepts=True, where=where, networks=sorted({str(n) for n in nets}))
    return out


def main() -> int:
    hosts, basis = population()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        rows = list(ex.map(read, hosts))
    withacc = [r for r in rows if r.get("accepts")]
    per_net = collections.Counter(n for r in withacc for n in r["networks"])
    solana = {n: c for n, c in per_net.items() if n.lower().startswith("solana")}
    summary = {
        "hosts": len(rows),
        "answered_402": sum(1 for r in rows if r.get("status") == 402),
        "accepts_bearing_challenges": len(withacc),
        "read_from": dict(collections.Counter(r["where"] for r in withacc)),
        "hosts_per_network": dict(per_net.most_common()),
        "network_values_fitting_caip2": sorted(n for n in per_net if CAIP2.match(n)),
        "network_values_not_fitting_caip2": sorted(n for n in per_net if not CAIP2.match(n)),
        "hosts_with_any_value_not_fitting_caip2": sum(1 for r in withacc
                                                      if any(not CAIP2.match(n) for n in r["networks"])),
        "solana_spellings": {n: {"hosts": c, "reference_length": len(n.split(":", 1)[1]) if ":" in n else None}
                             for n, c in sorted(solana.items(), key=lambda x: -x[1])},
    }
    day = started[:10]
    path = HERE / f"network_ids_{day}.json"
    json.dump({"generated_utc": started, "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "population_basis": basis, "caip2_pattern": CAIP2.pattern,
               "summary": summary, "rows": rows},
              open(path, "w", encoding="utf-8", newline="\n"), indent=1)
    print(json.dumps(summary, indent=1))
    print(f"-> {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
