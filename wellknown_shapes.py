#!/usr/bin/env python3
"""What shapes do deployed /.well-known/x402 documents have, and which proposal schemas accept them?

WHY THIS EXISTS. wg-domain-discovery issue #11 asks how a client tells a #2979 manifest from a
discovery entry today, given the hosts already serving the bare path, and two proposals in that group
(PR #4 and PR #8) each describe the document at that path and cite this census for what is deployed.
What a client sees at the path is a measurement, and so is how many deployed documents a proposal's
schema accepts. This records both, so the figures can be checked rather than quoted.

METHOD. The fetch is manifests.py's own (same User-Agent, TLS policy, 12 s timeout, 400 KB cap), on
the bare path only, over every host in the latest signed snapshot: the same 1,521 hosts as the
2026-09-22 and 2026-10-06 runs. For every JSON object it records which of the two carriers is
present (`resources`, the #2979 manifest list; `openapi`, the PR #4 entry link), how `x402Version` is
typed, and the top-level key names (names only, never values). Each schema passed with --schema is
then applied with its own declared draft, and a failing document is recorded with the validator of
jsonschema's best-match error and its path.

WHAT THIS DOES NOT CLAIM. A document a schema rejects is not broken: it serves whatever it serves
today. The count says how many of today's documents that schema would accept unchanged.

Read-only, keyless, one GET per host.

Usage: python wellknown_shapes.py [--schema LABEL=path.json ...]
Writes wellknown_shapes_<UTC date>.json
"""
import collections
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jsonschema

import manifests as M

HERE = Path(__file__).parent
SNAP = HERE / "snapshots"


def population():
    days = sorted(p.name for p in SNAP.iterdir() if p.name[:2] == "20")
    obs = json.loads((SNAP / days[-1] / "observation.json").read_text(encoding="utf-8"))["observations"]
    return [r["host"] for r in obs], f"every host in the signed snapshot of {days[-1]}"


def schemas_from_argv():
    out = {}
    for i, a in enumerate(sys.argv):
        if a == "--schema":
            label, path = sys.argv[i + 1].split("=", 1)
            schema = json.loads(Path(path).read_text(encoding="utf-8"))
            cls = jsonschema.validators.validator_for(schema)
            cls.check_schema(schema)
            out[label] = {"path": path, "validator": cls(schema), "draft": cls.__name__}
    return out


SCHEMAS = schemas_from_argv()


def fetch(host):
    out = {"host": host}
    try:
        req = urllib.request.Request(f"https://{host}/.well-known/x402", headers=M.UA)
        with urllib.request.urlopen(req, timeout=M.TIMEOUT, context=M._CTX) as r:
            raw = r.read(400_000)
            out["status"] = r.status
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
    out["object"] = isinstance(doc, dict)
    if not out["object"]:
        return out
    has_r, has_o = "resources" in doc, "openapi" in doc
    out["carriers"] = "both" if has_r and has_o else "resources" if has_r else "openapi" if has_o else "neither"
    out["resources_is_array"] = isinstance(doc.get("resources"), list) if has_r else None
    v = doc.get("x402Version")
    out["x402Version"] = ("absent" if "x402Version" not in doc else "int 2" if type(v) is int and v == 2
                          else f"{type(v).__name__} {v!r}"[:40])
    out["top_keys"] = sorted(doc)[:40]
    out["schemas"] = {}
    for label, s in SCHEMAS.items():
        err = jsonschema.exceptions.best_match(s["validator"].iter_errors(doc))
        out["schemas"][label] = {"valid": True} if err is None else {
            "valid": False, "validator": err.validator, "path": "/" + "/".join(str(p) for p in err.absolute_path)}
    return out


def main() -> int:
    hosts, basis = population()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with ThreadPoolExecutor(max_workers=M.WORKERS) as ex:
        rows = list(ex.map(fetch, hosts))
    objs = [r for r in rows if r.get("object")]
    carriers = collections.Counter(r["carriers"] for r in objs)
    summary = {
        "hosts": len(rows),
        "bare_path_json": sum(1 for r in rows if r.get("json")),
        "bare_path_json_object": len(objs),
        "carriers": dict(carriers),
        "x402Version_by_carriers": {c: dict(collections.Counter(r["x402Version"] for r in objs if r["carriers"] == c))
                                    for c in carriers},
        "schemas": {label: {"draft": s["draft"], "path": s["path"],
                            "valid": sum(1 for r in objs if r["schemas"][label]["valid"]),
                            "first_failure_by_validator": dict(collections.Counter(
                                r["schemas"][label]["validator"] for r in objs if not r["schemas"][label]["valid"]))}
                    for label, s in SCHEMAS.items()},
    }
    path = HERE / f"wellknown_shapes_{started[:10]}.json"
    json.dump({"generated_utc": started, "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "population_basis": basis, "summary": summary, "rows": rows},
              open(path, "w", encoding="utf-8", newline="\n"), indent=1)
    print(json.dumps(summary, indent=1))
    print(f"-> {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
