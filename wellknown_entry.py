#!/usr/bin/env python3
"""How many deployed /.well-known/x402 documents meet a proposed discovery-entry rule set?

WHY THIS EXISTS. wg-domain-discovery PR #4 (OpenAPI publication) defines the document at
/.well-known/x402 as a small entry: JSON served as application/json, with `x402Version` the integer 2
and `openapi` a required, nonempty array of URL strings. Clients MUST ignore members they do not
recognise. On 2026-09-22 this census counted 786 hosts answering the bare path with JSON, and that
figure was then cited in the PR thread as evidence the entry fits what is deployed. The honest test
of that is to grade every deployed document against the entry rules as written, and to record what
the near misses actually carry, so the text can be aligned with practice rather than asserted to fit.

METHOD. The fetch is manifests.py's own (same User-Agent, TLS policy, 12 s timeout, 400 KB cap), on
the bare path only. The population is every host in the latest signed snapshot, which is the same
1,521 hosts manifests.py read on 2026-09-22, so "answers the bare path with JSON" means exactly
what it meant then. Each JSON object is then graded on the three rules, and any `openapi` member
is recorded with its value, its shape (string, array, object) and whether it is an absolute URL.

WHAT THIS DOES NOT CLAIM. A document that fails the entry rules is not broken. Most of these hosts
publish a #2979-style manifest with `resources`, which is a different document with a different job.
The count answers one question: how many of today's documents a client of the proposed entry would
accept as an entry.

Read-only, keyless, one GET per host.

Usage: python wellknown_entry.py [--rules pr4-cec8145]
Writes wellknown_entry_<UTC date>.json
"""
import collections
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import manifests as M

HERE = Path(__file__).parent
SNAP = HERE / "snapshots"
RULES = sys.argv[sys.argv.index("--rules") + 1] if "--rules" in sys.argv else "pr4-cec8145"


def population():
    days = sorted(p.name for p in SNAP.iterdir() if p.name[:2] == "20")
    obs = json.loads((SNAP / days[-1] / "observation.json").read_text(encoding="utf-8"))["observations"]
    return [r["host"] for r in obs], f"every host in the signed snapshot of {days[-1]}"


def is_abs_url(u):
    return isinstance(u, str) and u.startswith(("https://", "http://"))


def grade(host):
    out = {"host": host}
    try:
        req = urllib.request.Request(f"https://{host}/.well-known/x402", headers=M.UA)
        with urllib.request.urlopen(req, timeout=M.TIMEOUT, context=M._CTX) as r:
            raw = r.read(400_000)
            out["status"] = r.status
            out["content_type"] = (r.headers.get("Content-Type") or "").lower()
    except urllib.error.HTTPError as e:
        out["status"] = e.code
        return out
    except Exception as e:  # noqa: BLE001 - unreachable is a result, not a crash
        out["error"] = type(e).__name__
        return out
    try:
        doc = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        out["json"] = False
        return out
    out["json"] = True
    if not isinstance(doc, dict):
        out["object"] = False
        return out
    out["object"] = True
    v = doc.get("x402Version")
    oa = doc.get("openapi")
    out["x402Version_int_2"] = type(v) is int and v == 2
    if "x402Version" in doc:
        out["x402Version_value"] = v if isinstance(v, (bool, int, float, str)) or v is None else repr(v)[:60]
    out["content_type_json"] = out["content_type"].split(";")[0].strip() == "application/json"
    out["resources_member"] = "resources" in doc
    if "openapi" in doc:
        out["openapi_value"] = oa[:200] if isinstance(oa, str) else json.dumps(oa)[:200]
        if isinstance(oa, str):
            out["openapi_shape"] = "string"
            out["openapi_absolute"] = is_abs_url(oa)
        elif isinstance(oa, list):
            out["openapi_shape"] = "array"
            out["openapi_absolute"] = bool(oa) and all(is_abs_url(u) for u in oa)
        else:
            out["openapi_shape"] = type(oa).__name__
            out["openapi_absolute"] = False
    out["entry_valid"] = (out["x402Version_int_2"] and out["content_type_json"]
                          and out.get("openapi_shape") == "array" and out["openapi_absolute"])
    out["valid_if_string_allowed"] = (out["x402Version_int_2"] and out["content_type_json"]
                                      and out.get("openapi_shape") in ("array", "string")
                                      and out.get("openapi_absolute", False))
    return out


def main() -> int:
    hosts, basis = population()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with ThreadPoolExecutor(max_workers=M.WORKERS) as ex:
        rows = list(ex.map(grade, hosts))
    objs = [r for r in rows if r.get("object")]
    oa = [r for r in objs if "openapi_shape" in r]
    summary = {
        "hosts": len(rows),
        "bare_path_json": sum(1 for r in rows if r.get("json")),
        "bare_path_json_object": len(objs),
        "x402Version_int_2": sum(1 for r in objs if r["x402Version_int_2"]),
        "content_type_json": sum(1 for r in objs if r["content_type_json"]),
        "openapi_member": len(oa),
        "openapi_shapes": dict(collections.Counter(r["openapi_shape"] for r in oa)),
        "openapi_absolute": sum(1 for r in oa if r.get("openapi_absolute")),
        "entry_valid": sum(1 for r in objs if r["entry_valid"]),
        "valid_if_single_string_allowed": sum(1 for r in objs if r["valid_if_string_allowed"]),
        "resources_member": sum(1 for r in objs if r["resources_member"]),
    }
    day = started[:10]
    path = HERE / f"wellknown_entry_{day}.json"
    json.dump({"generated_utc": started, "population_basis": basis, "rules": RULES,
               "rules_text": "JSON object served as application/json; x402Version integer 2; "
                             "openapi a nonempty array of URL strings (PR #4 at cec8145)",
               "summary": summary, "rows": rows},
              open(path, "w", encoding="utf-8", newline="\n"), indent=1)
    print(json.dumps(summary, indent=1))
    print(f"-> {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
