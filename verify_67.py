"""Re-derive the 67-live-hosts-dropped finding from files in this repo alone.

The claim (PR #2979, wg-identity#27): 67 hosts answering a payable 402 are absent
from the CDP discovery index -- klymax402.com 50, x402.press 11, gedx402.com 6.
hergertsynthora.com is excluded as an operator re-platforming, not an index miss.

Inputs, both in-repo:
  thirdparty/minia2auk_index_hosts_2026-08-26.json  (archived index listing, provenance inside)
  snapshots/2026-08-26/observation.json             (probe verdicts on the derivation day)

The reference day is 2026-08-26: the index side is minia2auk's 23:37Z pull of that
day, and the published derivation described the probe series as nineteen days,
which dates it 2026-08-08..2026-08-26. Exits nonzero if any figure moves.
"""
import json, sys

REF_DAY = "2026-08-26"
EXPECTED = {
    # domain: (mine, idx, idx_also_mine, mine_absent, absent_and_live)
    "klymax402.com":       (78, 40, 28, 50, 50),
    "x402.press":          (11,  0,  0, 11, 11),
    "gedx402.com":         (16,  7,  7,  9,  6),
    "hergertsynthora.com": (69, 12,  1, 68, 32),
}
COUNTED = ("klymax402.com", "x402.press", "gedx402.com")  # hergertsynthora excluded

arc = json.load(open("thirdparty/minia2auk_index_hosts_2026-08-26.json", encoding="utf-8"))
obs = json.load(open(f"snapshots/{REF_DAY}/observation.json", encoding="utf-8"))["observations"]
verdict = {o["host"]: o["verdict"] for o in obs}

failures = []
total = 0
extra_in_index = 0
print(f"reference day {REF_DAY}, cohort rows {len(verdict)}")
print(f"{'domain':24} {'mine':>4} {'idx':>4} {'both':>4} {'absent':>6} {'live':>4}")
for dom, exp in EXPECTED.items():
    idx = {f"{lab}.{dom}" for lab in arc["domains"][dom]["labels"]}
    mine = {h for h in verdict if h == dom or h.endswith("." + dom)}
    both = mine & idx
    absent = mine - idx
    live = {h for h in absent if verdict[h] == "OK"}
    got = (len(mine), len(idx), len(both), len(absent), len(live))
    mark = "" if got == exp else f"   EXPECTED {exp}"
    if got != exp:
        failures.append(f"{dom}: got {got}, expected {exp}")
    print(f"{dom:24} {got[0]:>4} {got[1]:>4} {got[2]:>4} {got[3]:>6} {got[4]:>4}{mark}")
    if dom in COUNTED:
        total += len(live)
    extra_in_index += len(idx - mine)

print(f"\nlive hosts absent from the index, three counted operators: {total}")
print(f"limit running the other way (in index, outside frozen cohort): {extra_in_index}")
if total != 67:
    failures.append(f"total: got {total}, expected 67")
if extra_in_index != 23:
    failures.append(f"index-only hosts across the four domains: got {extra_in_index}, expected 23")
if failures:
    print("\nFAILED:")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("all figures reproduce")
