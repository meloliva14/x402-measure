#!/usr/bin/env python3
"""Re-derive every figure minia2auk restates in x402#2979 comment 5462514798.

Claims under test (their words):
  - collapsing takes the numerator down 28% (32 -> 23)
  - collapsing takes the denominator down 56% (1,521 -> 663)
  - 0.53% over 6,084 host-days
  - 0.87% over 2,652 operator-days
  - pooled 0.53% over 6,084 host-days, 0.33-0.72% range

Everything is recomputed from snapshots/*/observation.json and the archived
ICANN public suffix list. Nothing is taken from memory or from the comment.
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "snapshots")
PSL = os.path.join(HERE, "thirdparty", "public_suffix_list.dat")

WINDOWS = [
    ("2026-08-24", "2026-08-25"),
    ("2026-08-25", "2026-08-26"),
    ("2026-08-26", "2026-08-27"),
    ("2026-08-27", "2026-08-28"),
]


def load_psl_icann():
    """ICANN section only. The ICANN/PRIVATE split is the whole point of Rule 1:
    the private section would fold *.vercel.app and *.up.railway.app away too."""
    rules, wildcards, exceptions = set(), set(), set()
    in_icann = False
    with open(PSL, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line.startswith("// ===BEGIN ICANN DOMAINS==="):
                in_icann = True
                continue
            if line.startswith("// ===END ICANN DOMAINS==="):
                in_icann = False
                continue
            if not in_icann or not line or line.startswith("//"):
                continue
            if line.startswith("!"):
                exceptions.add(line[1:])
            elif line.startswith("*."):
                wildcards.add(line[2:])
            else:
                rules.add(line)
    assert rules, "PSL ICANN section parsed empty"
    return rules, wildcards, exceptions


RULES, WILDCARDS, EXCEPTIONS = load_psl_icann()


def registrable(host: str) -> str:
    """eTLD+1 under the ICANN section, per the PSL algorithm."""
    host = host.lower().rstrip(".")
    labels = host.split(".")
    for i in range(len(labels)):
        candidate = ".".join(labels[i:])
        if candidate in EXCEPTIONS:
            return ".".join(labels[i:])
        parent = ".".join(labels[i + 1:])
        if candidate in RULES:
            return ".".join(labels[i - 1:]) if i >= 1 else host
        if parent and parent in WILDCARDS:
            return ".".join(labels[i - 1:]) if i >= 1 else host
    return host


def observation(day: str) -> dict[str, str]:
    with open(os.path.join(SNAP, day, "observation.json"), encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["date"] == day, f"{day}: observation.json self-reports {doc['date']}"
    return {r["host"]: r["verdict"] for r in doc["observations"]}


# ---------------------------------------------------------------- the cohort
days = sorted({d for w in WINDOWS for d in w})
obs = {d: observation(d) for d in days}

sizes = {d: len(v) for d, v in obs.items()}
assert len(set(sizes.values())) == 1, f"cohort size not constant across windows: {sizes}"
COHORT = next(iter(sizes.values()))
assert COHORT == 1521, f"cohort is {COHORT}, comment says 1,521"

hosts = set(obs[days[0]])
for d in days:
    assert set(obs[d]) == hosts, f"{d}: host set differs from {days[0]}"

domains = {registrable(h) for h in hosts}
assert len(domains) == 663, f"registrable domains = {len(domains)}, comment says 663"

# ------------------------------------------------------- numerator, per window
# A fetch failure can only ever move a host toward UNREACHABLE, never toward OK
# (flap_census.py header). So a transition with UNREACHABLE on either end is not
# evidence of a verdict change, and is not counted. Everything else is.
def changed(a: str, b: str, h: str) -> bool:
    before, after = obs[a][h], obs[b][h]
    if before == after:
        return False
    return "UNREACHABLE" not in (before, after)


host_changes, operator_events = [], []
for a, b in WINDOWS:
    flipped = [h for h in hosts if changed(a, b, h)]
    host_changes.append(len(flipped))
    operator_events.append(len({registrable(h) for h in flipped}))

# The exclusion has to actually remove something, or it is not being applied.
raw = [sum(1 for h in hosts if obs[a][h] != obs[b][h]) for a, b in WINDOWS]
assert sum(raw) > sum(host_changes), "UNREACHABLE exclusion is a no-op"

assert host_changes == [10, 6, 5, 11], f"per-window host changes {host_changes}"
assert operator_events == [4, 6, 5, 8], f"per-window operator events {operator_events}"

NUM_HOST = sum(host_changes)
NUM_OP = sum(operator_events)
assert NUM_HOST == 32, f"pooled host changes {NUM_HOST}, comment says 32"
assert NUM_OP == 23, f"pooled operator events {NUM_OP}, comment says 23"

# ------------------------------------------------------------- the two clocks
HOST_DAYS = COHORT * len(WINDOWS)
OP_DAYS = len(domains) * len(WINDOWS)
assert HOST_DAYS == 6084, f"host-days {HOST_DAYS}, comment says 6,084"
assert OP_DAYS == 2652, f"operator-days {OP_DAYS}, comment says 2,652"

host_rate = 100.0 * NUM_HOST / HOST_DAYS
op_rate = 100.0 * NUM_OP / OP_DAYS
assert round(host_rate, 2) == 0.53, f"host rate {host_rate:.4f}%, comment says 0.53%"
assert round(op_rate, 2) == 0.87, f"operator rate {op_rate:.4f}%, comment says 0.87%"

# ------------------------------------------------------------- the two deltas
num_drop = 100.0 * (NUM_HOST - NUM_OP) / NUM_HOST
den_drop = 100.0 * (COHORT - len(domains)) / COHORT
assert round(num_drop) == 28, f"numerator drop {num_drop:.2f}%, comment says 28%"
assert round(den_drop) == 56, f"denominator drop {den_drop:.2f}%, comment says 56%"
assert den_drop > num_drop, "denominator must move further for the rate to rise"

# --------------------------------------------------------------- the range
per_window_host_rate = [100.0 * c / COHORT for c in host_changes]
lo, hi = min(per_window_host_rate), max(per_window_host_rate)
assert round(lo, 2) == 0.33, f"low window {lo:.4f}%, comment says 0.33%"
assert round(hi, 2) == 0.72, f"high window {hi:.4f}%, comment says 0.72%"

# ------------------------------------------- negative control: the guard bites
try:
    assert len({registrable(h) for h in hosts}) == 664
except AssertionError:
    pass
else:
    raise SystemExit("NEGATIVE CONTROL FAILED: a false claim passed")

_bad = registrable("x.up.railway.app")
assert _bad == "railway.app", f"ICANN-only collapse broken: got {_bad}"
assert registrable("x.workers.dev") == "workers.dev"
assert registrable("a.b.vercel.app") == "vercel.app"

print(f"cohort           {COHORT} hosts -> {len(domains)} ICANN registrable domains")
print(f"per window host  {host_changes}  pooled {NUM_HOST}")
print(f"per window oper  {operator_events}  pooled {NUM_OP}")
print(f"host rate        {NUM_HOST}/{HOST_DAYS} = {host_rate:.4f}%")
print(f"operator rate    {NUM_OP}/{OP_DAYS} = {op_rate:.4f}%")
print(f"numerator drop   {num_drop:.2f}%   denominator drop {den_drop:.2f}%")
print(f"window range     {lo:.4f}% .. {hi:.4f}%")
print("ALL ASSERTIONS PASS")
