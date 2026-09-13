#!/usr/bin/env python3
"""Pick control hosts for the per-day comparison against nohumans.directory.

WHY TWO LISTS AND NOT ONE. The obvious next control is "a stable host instead of a flapper".
It is half right. A host that never changes state produces ZERO mixed days on their side, so it
cannot test the landing model at all: it only re-tests the unmixed agreement, which already
stands at 106 of 106. Generalisation and statistical power pull in opposite directions here.

  A. STABLE, and the only host on its parent domain. Tests whether the agreement holds on a
     healthy independent operator rather than on a dying fleet. Three of the four hosts in the
     first comparison are subdomains of hergertsynthora.com, so generalisation is the real gap.
  B. A FLAPPER that is NOT in that fleet. More mixed days is more power on the landing model,
     and a different operator means the power is not bought from the same box.

The dimension this script CANNOT see is whether a host is actually being paid. Only an instrument
with a purchase ledger knows that, so that half of the choice belongs to whoever has one.
"""
import collections, json, os, sys

BASE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(BASE, "snapshots")


def parent(host: str) -> str:
    p = host.split(".")
    return ".".join(p[-3:]) if len(p) > 2 and p[-2] in ("co", "com", "deno") else ".".join(p[-2:])


def main() -> int:
    days = sorted(d for d in os.listdir(SNAP) if d[:2] == "20")
    seen: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for d in days:
        with open(os.path.join(SNAP, d, "observation.json"), encoding="utf-8") as f:
            for r in json.load(f)["observations"]:
                seen[r["host"]][d] = r.get("verdict")
    pc = collections.Counter(parent(h) for h in seen)

    def flips(v: dict[str, str]) -> int:
        s = [v[d] for d in days]
        return sum(1 for i in range(1, len(s)) if (s[i] == "OK") != (s[i - 1] == "OK"))

    stable = [h for h, v in seen.items() if all(x == "OK" for x in v.values())]
    stable_solo = sorted(h for h in stable if pc[parent(h)] == 1)
    flappers = sorted(
        ((flips(v), sum(1 for x in v.values() if x == "OK"), h)
         for h, v in seen.items()
         if "hergertsynthora" not in h
         and 0 < sum(1 for x in v.values() if x == "OK") < len(days)
         and flips(v) >= 4),
        reverse=True)

    print(f"window {days[0]}..{days[-1]} ({len(days)} days), population {len(seen)}")
    print(f"  OK on every day                         : {len(stable)}")
    print(f"  of those, sole host on its parent domain: {len(stable_solo)}")
    print(f"  flappers outside the fleet (>=4 flips)  : {len(flappers)}")
    for f, ok, h in flappers[:10]:
        print(f"    {h[:48]:48} flips={f:>2} OK {ok}/{len(days)} parent-hosts={pc[parent(h)]}")

    out = os.path.join(BASE, f"control_candidates_{days[-1]}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"window": [days[0], days[-1]], "days": len(days),
                   "stable_solo_parent": stable_solo,
                   "flappers_outside_the_fleet":
                       [{"host": h, "flips": fl, "ok_days": ok} for fl, ok, h in flappers]},
                  f, indent=1)
    print("->", os.path.basename(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
