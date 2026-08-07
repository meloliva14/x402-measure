"""Does the platform-suffix list still describe the network, or has it rotted?

x402-foundation/x402#2979 ships a static list of platform suffixes with an acceptance test in
prose: if the label directly above an entry changes hands between unrelated parties, the entry
is at the right depth; if a constant label sits above it, the boundary is one level deeper.

A static list plus a test nobody runs is a static list. This runs the test.

It found two entries wrong on its first pass, both of which two careful human reads had missed:

    railway.app   ->  up.railway.app    66 hosts, all under a constant 'up'
    run.app       ->  a.run.app          3 hosts, all under a constant 'a'

Platforms change URL shapes and new ones appear, so the answer today is not the answer in six
months. The point of having this in the repo is that the census re-runs anyway, and drift shows
up as a diff rather than as somebody eventually noticing.

Exit code is 1 when an entry looks wrong, so this can gate a scheduled run.

Read-only, no network.
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
SWEEP = HERE / "sweep_results.json"

# The list as it stands in the spec after the two corrections.
SUFFIXES = ("vercel.app", "workers.dev", "up.railway.app", "onrender.com", "fly.dev",
            "replit.app", "netlify.app", "a.run.app", "sslip.io", "nip.io")

# Wildcard DNS. Every name under these resolves for whoever asks, so there is no account level
# and the operator-boundary test does not apply. Right answer, different mechanism. Annotated
# rather than silently skipped, because a maintainer who runs the test on them and sees a
# strange result deserves to know why before they "fix" it.
WILDCARD = {"sslip.io", "nip.io"}

# Below this a suffix has too few hosts for "the label above changes hands" to mean anything.
MIN_HOSTS = 3


def load_hosts():
    rows = json.loads(SWEEP.read_text(encoding="utf-8"))
    return sorted({r["host"].lower() for r in rows if r.get("host")})


def audit(hosts, suffixes=SUFFIXES):
    out = []
    for s in suffixes:
        hs = [h for h in hosts if h.endswith("." + s)]
        if s in WILDCARD:
            out.append({"suffix": s, "hosts": len(hs), "verdict": "wildcard-dns-exempt"})
            continue
        if len(hs) < MIN_HOSTS:
            out.append({"suffix": s, "hosts": len(hs), "verdict": "too-few-hosts-to-judge"})
            continue
        above = Counter(h[:-(len(s) + 1)].split(".")[-1] for h in hs)
        if len(above) == 1:
            constant = next(iter(above))
            out.append({"suffix": s, "hosts": len(hs), "verdict": "BOUNDARY-TOO-SHALLOW",
                        "constant_label": constant, "should_be": f"{constant}.{s}"})
        else:
            out.append({"suffix": s, "hosts": len(hs), "verdict": "ok",
                        "distinct_labels_above": len(above)})
    return out


def unlisted_candidates(hosts, suffixes=SUFFIXES, min_tenants=8):
    """Suffixes NOT on the list that behave like platforms: many hosts, many distinct tenants.

    A new platform showing up is the other way this list rots, and it is invisible to an audit
    that only checks the entries already present.
    """
    cand = Counter()
    for h in hosts:
        p = h.split(".")
        if len(p) < 3:
            continue
        s = ".".join(p[-2:])
        if any(h.endswith("." + x) for x in suffixes):
            continue
        cand[s] += 1
    out = []
    for s, n in cand.items():
        if n < min_tenants:
            continue
        tenants = {h[:-(len(s) + 1)].split(".")[-1] for h in hosts if h.endswith("." + s)}
        # Many hosts AND many distinct immediate labels is what a shared platform looks like.
        # One company with many subdomains looks the same from here, so this SUGGESTS, never
        # concludes. The list is a human decision; this only says where to look.
        if len(tenants) >= min_tenants:
            out.append({"suffix": s, "hosts": n, "distinct_labels": len(tenants)})
    return sorted(out, key=lambda r: -r["hosts"])


def main():
    hosts = load_hosts()
    rows = audit(hosts)
    print(f"  auditing {len(SUFFIXES)} listed suffixes against {len(hosts):,} hosts\n")
    bad = [r for r in rows if r["verdict"] == "BOUNDARY-TOO-SHALLOW"]
    for r in rows:
        note = ""
        if r["verdict"] == "BOUNDARY-TOO-SHALLOW":
            note = f"  every host sits under '{r['constant_label']}' -> should be {r['should_be']}"
        elif r["verdict"] == "ok":
            note = f"  {r['distinct_labels_above']} distinct labels above"
        print(f"   {r['verdict']:<22} {r['suffix']:<18} {r['hosts']:>4} hosts{note}")

    cands = unlisted_candidates(hosts)
    if cands:
        print("\n  suffixes NOT listed that look platform-shaped (suggestion only, not a verdict):")
        for c in cands[:8]:
            print(f"   {c['hosts']:>4} hosts / {c['distinct_labels']:>4} distinct labels  {c['suffix']}")
        print("   A single company with many subdomains looks identical from here. Check by hand.")

    if bad:
        print(f"\n  {len(bad)} entry/entries look wrong. Exiting 1.")
        return 1
    print("\n  every listed entry still sits at the depth where operators change hands.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
