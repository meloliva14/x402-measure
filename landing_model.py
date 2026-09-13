#!/usr/bin/env python3
"""Where does a daily sample land inside a day that an intraday instrument calls MIXED?

THE MODEL, AND WHAT BROKE IN IT. If a daily probe is ONE request taken at a moment independent of
the endpoint's state, the chance it sees a challenge is the day's 402 share p, so across mixed
days the expected count of challenge-landings is sum(p) with variance sum(p(1-p)). That model was
handed to nohumans.directory on 2026-09-12 and it failed on their control host
api.osf-master-server.com on 2026-09-13: 19 landings on 19 mixed days against an expected 12.47,
3.3 standard deviations out.

Two things in OUR instrument break the assumption, and neither is a fault in theirs:

  1. THE PROBE IS NOT ONE REQUEST. It is a GET, then a POST when the GET did not produce a
     challenge, plus one retry on transport failure, and it records a challenge if ANY of them saw
     one. k independent draws give 1-(1-p)^k, which on osf moves the expectation to 16.30 (k=2)
     or 17.76 (k=3). Before schema /3 the row did not record k, so for history k is a RANGE.
  2. THE PROBE RUNS AT A FIXED HOUR (scheduled 04:17 UTC, finishing by about 05:05). A sample
     taken at the same time every day is not a uniform draw over the day. If a host's failures
     cluster elsewhere in the day, the sample systematically misses them. That cannot be corrected
     from a whole-day share at all; it needs the intraday instrument's share INSIDE our window.
  3. THE POST FALLBACK IS MODELLED AS A SECOND DRAW AT THE SAME SHARE. That assumes the day's
     402 share is not verb-specific. If a host gates one verb and not the other, or the intraday
     instrument probes with one verb only, the share is verb-specific and the bracket needs
     their verb before it means anything. Asked, not assumed.

So this module gives an honest bracket instead of a false point: expected landings under the
smallest and largest draw count a row could have had, and the z for each. A result that is
anomalous under BOTH bounds is anomalous. A result inside 2 sd at the k-high bound is reported
as "no contradiction the bracket can see", never as agreement, because the fixed sampling hour
is not corrected and the verb assumption is unverified.

What history can and cannot say about k per row:
  - row has probe.requests (schema /3 onward): k is that number, exactly; 0 means no draw.
  - row has no probe and no `retried` flag: one attempt, GET then maybe POST -> k in {1, 2}.
  - row has `retried`: two attempts of 1-2 requests each -> k in {2, 3, 4}. (The first attempt
    failed at transport, so it may not have reached the endpoint at all; 2 is the honest floor.)
"""
import math

SAMPLING_WINDOW_UTC = ("04:17", "05:05")


def k_bounds(row: dict) -> tuple[int, int]:
    """Smallest and largest number of draws this row could represent."""
    probe = row.get("probe")
    if isinstance(probe, dict) and isinstance(probe.get("requests"), int) and probe["requests"] >= 0:
        # Exact from schema /3 on. Zero is real: a policy refusal made no request, so that row is
        # no draw at all and contributes nothing to the expectation. None (unknown) falls through.
        return probe["requests"], probe["requests"]
    if row.get("retried"):
        return 2, 4
    return 1, 2


def p_land(p: float, k: int) -> float:
    """Chance that at least one of k independent draws sees a challenge on a day with share p."""
    return 1.0 - (1.0 - p) ** k


def summarise(mixed: list[dict]) -> dict:
    """mixed: rows carrying `share` (their 402 share), `our_served` (bool) and, optionally, the
    original observation row under `row` so k can be bounded. Returns observed, the expectation
    bracket, sd and z at both bounds, and the sampling-window caveat."""
    obs = sum(1 for m in mixed if m["our_served"])
    out = {"mixed_days": len(mixed), "observed": obs,
           "sampling_window_utc": list(SAMPLING_WINDOW_UTC),
           "note": ("expectation is a bracket over the draw count k the instrument could have "
                    "taken; the fixed sampling hour is NOT corrected here and needs the intraday "
                    "share inside the window to address; the POST fallback is modelled as a "
                    "second draw at the same share, which assumes the share is not verb-specific")}
    for label, pick in (("k_lo", 0), ("k_hi", 1)):
        ps = [p_land(m["share"], k_bounds(m.get("row", {}))[pick]) for m in mixed]
        exp = sum(ps)
        var = sum(q * (1 - q) for q in ps)
        sd = math.sqrt(var) if var > 0 else 0.0
        out[f"expected_{label}"] = round(exp, 4)
        out[f"sd_{label}"] = round(sd, 4)
        out[f"z_{label}"] = round((obs - exp) / sd, 4) if sd > 0 else None
    out["k_range_used"] = sorted({k_bounds(m.get("row", {})) for m in mixed})
    return out


def verdict_line(s: dict) -> str:
    """One honest sentence for a report."""
    zl, zh = s.get("z_k_lo"), s.get("z_k_hi")
    if zl is None or zh is None:
        return (f"{s['observed']} of {s['mixed_days']} mixed days landed on a challenge; "
                f"expectation bracket {s['expected_k_lo']}..{s['expected_k_hi']} (sd 0 at a bound)")
    both_out = min(abs(zl), abs(zh)) >= 2.0
    tag = "ANOMALOUS under every draw count the instrument could have taken" if both_out \
        else ("not anomalous at the k-high bound (|z| < 2); the fixed sampling hour is uncorrected, "
              "so read this as no contradiction the bracket can see, not as agreement")
    return (f"{s['observed']} of {s['mixed_days']} mixed days landed on a challenge; "
            f"expected {s['expected_k_lo']} (k low, z {zl:+.2f}) to {s['expected_k_hi']} "
            f"(k high, z {zh:+.2f}): {tag}")


if __name__ == "__main__":
    # tiny self-check: with k=1 exactly, the bracket collapses to the classic sum(p).
    demo = [{"share": 0.5, "our_served": True, "row": {"probe": {"requests": 1}}}] * 4
    s = summarise(demo)
    assert s["expected_k_lo"] == s["expected_k_hi"] == 2.0, s
    print("landing_model self-check ok")
