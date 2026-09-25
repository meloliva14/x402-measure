#!/usr/bin/env python3
"""Which key does the 402 challenge on the wire use for the protocol version, and how is it typed?

WHY THIS EXISTS. On 2026-08-06 I posted on x402#2979 (issuecomment-5199553316): "I probed 260 live
payment-gated hosts and got 139 readable challenges back. All 139 use x402Version ... every value
is typed int", and offered the re-run. The discovery spec gives that figure as its reason for keeping
`x402Version` as the field's name, and its footnote cites that comment. The 08-06 run was a scratch
script reading a sweep file this repo ignores as generated data, so this commits the probe and pins
the population it read, and anyone can re-run it.

TWO METHODS, because the 08-06 one is not the census's.

  --method 2026-08-06   What the 08-06 run did: one POST with body {} and Content-Type
                        application/json, the challenge read from the PAYMENT-REQUIRED header
                        first and the body second. A host is read only if that POST answers 402.
  --method census       (default) The daily census's own fetch, preflight.get_402_traced: GET,
                        then POST when the GET does not produce a challenge, no POST after a
                        429, and the SSRF fence.

  Both read the version the same way: the first of x402Version, version, x402_version and
  protocolVersion present at the top level of the challenge, and "typed" means a JSON integer.

  Declared differences from the 08-06 script. The request goes through preflight.fetch, so it
  carries that User-Agent and an Accept: application/json header the script did not send, waits
  20 s where the script waited 10 s, reads the whole body where the script read the first 200 KB,
  refuses private-address destinations on the first hop and on every redirect (the SSRF fence
  added on 2026-08-17), and restores base64 padding before decoding the header. A header that
  decodes to something other than a JSON object falls through to the body, where the script gave
  up on it. A JSON boolean no longer counts as an integer: the script tested
  isinstance(value, int), which Python answers True for a boolean.

TWO POPULATIONS.

  --population 2026-08-06   The 260 hosts the 08-06 run read: the first 260 rows with verdict OK
                            or V1 in sweep_results.json, in file order, pinned in
                            wire_version_population_2026-08-06.json with the source file's hash.
                            That file holds the same 1,521 hosts, in the same order and at the
                            same URLs, as the first signed snapshot (2026-08-08).
  --population census       (default) Every host in the latest signed snapshot, at its pinned URL.

WHAT A RE-RUN CAN AND CANNOT SAY. The 08-06 counts are a dated observation of a network that has
moved since, so a run today is a new dated figure, not a reproduction of 139. What it tests is the
finding itself: whether every challenge still spells the field x402Version and types it as an
integer. "Readable" is any JSON object on a 402, as on 08-06, and a few of those carry no accepts[]
and are not challenges any client could use, so the summary counts the accepts-bearing ones apart.

Read-only. No wallet, no key, no payment.

Usage: python wire_version.py [--method census|2026-08-06] [--population census|2026-08-06]
Writes wire_version_rerun-of-2026-08-06_<UTC date>.json for the 08-06 population and method,
wire_version_census_<UTC date>.json for the census defaults, and a descriptive name otherwise.
"""
import collections
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import preflight

HERE = Path(__file__).parent
SNAP = HERE / "snapshots"
PIN_0806 = HERE / "wire_version_population_2026-08-06.json"
VERSION_KEYS = ("x402Version", "version", "x402_version", "protocolVersion")
WORKERS = 14   # the census's own concurrency (snapshot.py), and what the 08-06 script used
METHODS = {
    "2026-08-06": "one POST with body {} (Content-Type application/json); header first, then body",
    "census": "preflight.get_402_traced: GET, then POST when the GET does not produce a challenge, "
              "no POST after a 429, SSRF fence; header first, then body",
}


def arg(flag, default):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def population(which):
    if which == "2026-08-06":
        pin = json.loads(PIN_0806.read_text(encoding="utf-8"))
        return [{"host": h["host"], "url": h["url"]} for h in pin["hosts"]], pin["basis"]
    days = sorted(p.name for p in SNAP.iterdir() if p.name[:2] == "20")
    obs = json.loads((SNAP / days[-1] / "observation.json").read_text(encoding="utf-8"))["observations"]
    return [{"host": r["host"], "url": r["url"]} for r in obs], f"every host in the signed snapshot of {days[-1]}"


def json_type(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "string"
    if v is None:
        return "null"
    return type(v).__name__


def fetch(url, method):
    if method == "2026-08-06":
        status, headers, body = preflight.fetch(url, "POST")
        return status, headers, body, {"verb": "POST", "requests": 1}
    return preflight.get_402_traced(url)


def version_of(ch):
    present = [k for k in VERSION_KEYS if k in ch]
    key = present[0] if present else None
    return key, present, (ch.get(key) if key else None)


def read(row, method):
    out = {"host": row["host"], "url": row["url"]}
    try:
        status, headers, body, trace = fetch(row["url"], method)
    except Exception as e:  # noqa: BLE001
        out.update(status=None, error=type(e).__name__)
        return out
    out.update(status=status, verb=trace.get("verb"), requests=trace.get("requests"))
    if status != 402:
        return out
    hdr, bod = preflight.parse_challenge(headers, body)
    if isinstance(hdr, dict):
        ch, where = hdr, "header"
    elif isinstance(bod, dict):
        ch, where = bod, "body"
    else:
        out["readable"] = False
        return out
    key, present, val = version_of(ch)
    out.update(readable=True, where=where, key=key, keys_present=present,
               value=val if isinstance(val, (bool, int, float, str)) or val is None else repr(val)[:60],
               json_type=json_type(val) if key else None,
               has_accepts=isinstance(ch.get("accepts"), list) and bool(ch.get("accepts")))
    # "Readable" is any JSON object on a 402, as on 08-06, and some of those are not x402 at all.
    # Where no version key is present, the top-level key NAMES (never values) say what it was.
    if not key:
        out["top_keys"] = sorted(ch)[:12]
    # A host can serve both dialects. The header is what this counts, as on 08-06; the body's own
    # spelling is kept beside it so a dual-dialect host is visible rather than folded in.
    if where == "header" and isinstance(bod, dict):
        bkey, _, bval = version_of(bod)
        out.update(body_key=bkey, body_json_type=json_type(bval) if bkey else None)
    return out


def main() -> int:
    method = arg("--method", "census")
    which = arg("--population", "census")
    if method not in METHODS or which not in ("census", "2026-08-06"):
        raise SystemExit(__doc__)
    hosts, basis = population(which)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"  probing {len(hosts)} hosts ({which} population) for the version key ON THE WIRE")
    print(f"  method {method}: {METHODS[method]}\n")
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        rows = list(ex.map(lambda r: read(r, method), hosts))

    got402 = [r for r in rows if r.get("status") == 402]
    readable = [r for r in rows if r.get("readable")]
    keyed = [r for r in readable if r["key"]]
    summary = {
        "hosts": len(rows),
        "answered_402": len(got402),
        "readable_challenges": len(readable),
        "no_402": sum(1 for r in rows if r.get("status") not in (None, 402)),
        "transport_or_blocked": sum(1 for r in rows if r.get("status") is None),
        "read_from": dict(collections.Counter(r["where"] for r in readable)),
        "version_key": dict(collections.Counter(r["key"] or "(none)" for r in readable)),
        "json_type": dict(collections.Counter(r["json_type"] for r in keyed)),
        "value": dict(collections.Counter(json.dumps(r["value"]) for r in keyed)),
        "more_than_one_version_key": sum(1 for r in readable if len(r["keys_present"]) > 1),
        "with_accepts": sum(1 for r in readable if r["has_accepts"]),
        "version_key_where_accepts_present": dict(collections.Counter(r["key"] or "(none)"
                                                                      for r in readable if r["has_accepts"])),
        "version_key_where_accepts_absent": dict(collections.Counter(r["key"] or "(none)"
                                                                     for r in readable if not r["has_accepts"])),
        "dual_dialect_body_key": dict(collections.Counter(r["body_key"] or "(none)"
                                                          for r in readable if "body_key" in r)),
    }
    print(f"  answered 402: {summary['answered_402']}")
    print(f"  readable challenges: {summary['readable_challenges']}\n")
    print("  version key used on the wire:")
    for k, c in collections.Counter(r["key"] or "(none)" for r in readable).most_common():
        print(f"   {c:>4}x  {k}")
    if keyed:
        print("\n  and how the value is typed:")
        for t, c in collections.Counter(r["json_type"] for r in keyed).most_common():
            print(f"   {c:>4}x  {t}")
        for r in [r for r in keyed if r["json_type"] != "int"][:10]:
            print(f"     not an integer: {r['host'][:44]} -> {r['value']!r}")
    print(f"\n  with a non-empty accepts[]: {summary['with_accepts']}"
          f" | version key there: {summary['version_key_where_accepts_present']}"
          f" | without accepts[]: {summary['version_key_where_accepts_absent']}")
    for r in [r for r in readable if not r["key"]]:
        print(f"     no version key: {r['host'][:44]} ({r['where']}) keys {r['top_keys']}")

    day = started[:10]
    name = {("2026-08-06", "2026-08-06"): f"wire_version_rerun-of-2026-08-06_{day}.json",
            ("census", "census"): f"wire_version_census_{day}.json"}.get(
        (which, method), f"wire_version_{which}-hosts_{method}-method_{day}.json")
    path = HERE / name
    json.dump({"generated_utc": started, "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "method": method, "method_note": METHODS[method],
               "population": which, "population_basis": basis,
               "version_keys_checked": list(VERSION_KEYS),
               "typed_means": "a JSON integer; a boolean is not one",
               "summary": summary, "rows": rows},
              open(path, "w", encoding="utf-8", newline="\n"), indent=1)
    print(f"\n  -> {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
