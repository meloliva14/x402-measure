"""Probe a snapshot's payment-gated hosts with a bare GET and no verb fallback.

This measures how much of the gated population a GET-only scanner misreads as
not payment gated. The census itself never has this blindness because
preflight.fetch retries as POST whenever GET does not produce a 402 (see the
2026-08-18 note in preflight.py), so the only way to see the GET-only view is
to run this pass deliberately.

Results that have been posted to the x402 working-group record:
  2026-09-01 snapshot: 356 of 1,312 gated hosts did not serve their 402 to a
    bare GET (27.1%). Raw results: getonly_2026-09-01.json
  2026-09-03 snapshot: 352 of 1,328 (26.5%). Raw results:
    getonly_2026-09-03.json. Every one of the 352 was already in the 09-01
    set of 356; no host moved in either direction between the two passes.

Usage: python get_only_pass.py [YYYY-MM-DD]   (defaults to the latest snapshot)
A live re-probe drifts with the network; the pinned part is the denominator,
which is the snapshot's gated set (verdicts OK, WARN, V1, NON_EVM, BLOCKED).
"""
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import preflight

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"
GATED = ("OK", "WARN", "V1", "NON_EVM", "BLOCKED")


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else sorted(p.name for p in SNAPSHOTS.iterdir())[-1]
    obs = json.load(open(SNAPSHOTS / day / "observation.json", encoding="utf-8"))["observations"]
    gated = [r for r in obs if r["verdict"] in GATED]
    print(f"gated hosts in the {day} snapshot: {len(gated)}")

    def probe(r):
        try:
            s, _, _ = preflight.fetch(r["url"], "GET")
            return (r["host"], s, None)
        except Exception as e:
            return (r["host"], None, type(e).__name__)

    res = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for f in as_completed([ex.submit(probe, r) for r in gated]):
            res.append(f.result())

    ok = [x for x in res if x[1] == 402]
    non = [x for x in res if x[1] is not None and x[1] != 402]
    err = [x for x in res if x[1] is None]
    print(f"  402 to a bare GET      : {len(ok)}")
    print(f"  some other HTTP status : {len(non)}  {dict(Counter(x[1] for x in non).most_common())}")
    print(f"  transport error        : {len(err)}")
    print(f"  misread by a GET-only scanner: {len(non)}/{len(gated)} = {len(non)/len(gated)*100:.1f}%")

    out = HERE / f"getonly_{day}.json"
    json.dump(
        {
            "snapshot": day,
            "probed": len(res),
            "got402": len(ok),
            "non402": sorted(({"host": h, "status": s} for h, s, _ in non), key=lambda x: x["host"]),
            "errors": sorted(h for h, _, e in err),
        },
        open(out, "w"),
        indent=1,
    )
    print(f"-> {out.name}")


if __name__ == "__main__":
    main()
