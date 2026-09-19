#!/usr/bin/env python3
"""Hosts pinned to a templated route, and what they do to the not-gated count.

WHY. The census probes each host at one pinned URL, taken from the discovery listing. For some
hosts that URL is a route template, a path segment such as /:id or /:action, and the probe
requests the placeholder literally. A 404 there is an answer about the literal string ":id", not
about whether the real route charges, so such a host can sit in "gone at least fourteen straight
days serving no payment challenge" for as long as it stays pinned, whatever the real route does.

Found on 2026-09-19 while choosing controls for Ivan's 15-host export: of the 34 hosts that
answered 404 on every day of the 08-08..09-14 window under both readings, 20 were templated.

WHAT THIS DOES NOT DO. It moves no published number and edits no signed snapshot. Every verdict
stays what the probe saw. It prints the not-gated count with and without templated hosts beside
the published one, on the published basis: 429 rows are neutralised exactly as notgated_runs.py
does, by reusing origin_error_history's helpers rather than re-deriving them.

RULE. A path is templated when any of its segments starts with ':'. The script also counts the
other common template spellings ({name}, <name>, [name], *, and a colon inside a segment) and
reports them, so the rule is checked against the population rather than assumed. The pinned URL
of every host is checked for change across the window; the classification is per host only while
that count is zero.

A 402 is "served" for OK, WARN, V1, NON_EVM, BLOCKED, UNKNOWN_NETWORK and UNPARSEABLE, per the
verdict vocabulary in each day's manifest. NO_402, UNREACHABLE and RATE_LIMITED are not served.

Usage: python templated_routes.py [--until YYYY-MM-DD]   (writes templated_routes_<last-day>.json)
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlparse

import origin_error_history as oeh

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"
SERVED = {"OK", "WARN", "V1", "NON_EVM", "BLOCKED", "UNKNOWN_NETWORK", "UNPARSEABLE"}


def path_of(url: str) -> str:
    return unquote(urlparse(url).path)


def templated(path: str) -> bool:
    return any(seg.startswith(":") for seg in path.split("/"))


def other_shapes(path: str) -> list:
    out = []
    if any(":" in s and not s.startswith(":") for s in path.split("/")):
        out.append("colon_inside_segment")
    if re.search(r"\{[^}]*\}", path):
        out.append("braces")
    if re.search(r"<[^>]*>", path):
        out.append("angle")
    if re.search(r"\[[^\]]*\]", path):
        out.append("square")
    if "*" in path:
        out.append("star")
    return out


def main() -> int:
    until = None
    if "--until" in sys.argv:
        until = sys.argv[sys.argv.index("--until") + 1]
    days = sorted(p.name for p in SNAPSHOTS.iterdir() if p.name[:2] == "20")
    if until:
        days = [d for d in days if d <= until]
    V, S, URLS = {}, {}, {}
    for d in days:
        with open(SNAPSHOTS / d / "observation.json", encoding="utf-8") as f:
            rows = json.load(f)["observations"]
        V[d] = {r["host"]: ("RATE_LIMITED" if oeh.rate_limited(r) else r["verdict"]) for r in rows}
        S[d] = {r["host"]: oeh.status_of(r) for r in rows}
        for r in rows:
            URLS.setdefault(r["host"], set()).add(r["url"])

    changed = sorted(h for h, u in URLS.items() if len(u) > 1)
    paths = {h: path_of(sorted(u)[0]) for h, u in URLS.items()}
    T = {h for h, p in paths.items() if templated(p)}
    shapes = Counter(s for p in paths.values() for s in other_shapes(p))

    a = oeh.ever_hit_run(days, V, S, False)   # as published
    b = oeh.ever_hit_run(days, V, S, True)    # origin failures not counted as answers

    detail = []
    for h in sorted(T):
        vc = Counter(V[d][h] for d in days if h in V[d])
        no402 = Counter(S[d][h] for d in days if V[d].get(h) == "NO_402")
        detail.append({
            "host": h,
            "path": paths[h],
            "days_observed": sum(vc.values()),
            "verdicts": dict(sorted(vc.items())),
            "served_a_402_on_days": sum(n for v, n in vc.items() if v in SERVED),
            "no_402_statuses": dict(sorted(no402.items())),
            "in_notgated_as_published": h in a,
            "in_notgated_if_origin_errors_excluded": h in b,
        })

    served_any = [r for r in detail if r["served_a_402_on_days"] > 0]
    never = [r for r in detail if r["served_a_402_on_days"] == 0]
    s404 = [r for r in never if set(r["no_402_statuses"]) == {"404"}]
    # The artifact is narrower than "templated". A templated host that served a 402 on the literal
    # path on any day, before or after its dark run, shows that request can be answered with a
    # challenge, so its change is a real observed transition: same request, different answer. Only
    # a templated host that never served a 402 in the window leaves its dark run uninformative.
    never_h = {r["host"] for r in never}
    a_never, a_served = a & never_h, (a & T) - never_h
    b_never, b_served = b & never_h, (b & T) - never_h
    summary = {
        "generated": days[-1],
        "window": {"first": days[0], "last": days[-1], "days": len(days)},
        "rule": "templated = any path segment starts with ':'",
        "pinned_hosts": len(paths),
        "pinned_url_changes_in_window": len(changed),
        "other_template_shapes_found": dict(shapes),
        "templated_hosts": len(T),
        "templated_that_served_a_402_on_some_day": len(served_any),
        "templated_that_never_served_a_402": len(never),
        "templated_never_served_and_every_no_402_day_was_404": len(s404),
        "basis": ("429 rows neutralised exactly as notgated_runs.py does, via origin_error_history's "
                  "helpers, so the as-published count matches the published census on the same window"),
        "notgated_runs_as_published": len(a),
        "of_which_templated": len(a & T),
        "of_which_templated_and_never_served_a_402": len(a_never),
        "of_which_templated_and_served_a_402_on_some_day": len(a_served),
        "notgated_runs_as_published_excluding_never_served_templated": len(a - a_never),
        "notgated_runs_if_origin_errors_excluded": len(b),
        "of_which_templated_under_that_reading": len(b & T),
        "of_which_templated_and_never_served_under_that_reading": len(b_never),
        "notgated_runs_excluding_origin_errors_and_never_served_templated": len(b - b_never),
        "reading_note": ("the artifact class is templated AND never served a 402 in the window; a "
                         "templated host that served one on any day, before or after its dark run, "
                         "shows the literal path can be answered with a challenge, so its run is a real transition"),
        "templated_hosts_detail": detail,
    }
    print(f"  window {days[0]}..{days[-1]} ({len(days)} days); pinned hosts {len(paths)}; "
          f"pinned-URL changes {len(changed)}; other template shapes {dict(shapes) or 'none'}")
    print(f"  templated hosts: {len(T)}  (served a 402 on some day: {len(served_any)}; "
          f"never: {len(never)}, of which 404 on every not-gated day: {len(s404)})")
    print(f"  not-gated 14-day runs as published:        {len(a)}  templated {len(a & T)} "
          f"(never served a 402: {len(a_never)}, served one on some day: {len(a_served)})  -> {len(a - a_never)} without the uninformative ones")
    print(f"  same if origin failures are not answers:   {len(b)}  templated {len(b & T)} "
          f"(never served a 402: {len(b_never)}, served one on some day: {len(b_served)})  -> {len(b - b_never)}")

    out = HERE / f"templated_routes_{days[-1]}.json"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=1)
    print("->", out.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
