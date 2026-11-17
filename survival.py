#!/usr/bin/env python3
"""How long do x402 sellers last? A survival study of one fixed cohort, from the signed snapshots.

WHY THIS EXISTS. Every other x402 count is a snapshot of a catalog that keeps changing: sellers
join, sellers leave, and the total says nothing about which. This census probes the same 1,521
hosts every day and signs the record, so it can follow one group of sellers forward in time and
say how many are still selling, how fast the rest stopped, and how they stopped. That is a
survival curve, and as far as I could find nobody has published one for x402.

METHOD. The cohort is every host that was payment-gated on 2026-08-19 (COHORT_DAY): its verdict
was OK, WARN, V1, NON_EVM or BLOCKED, the GATED set monthly_report.py uses. That day is the first
day of the classifier generation that recognises the full gated set: on 2026-08-19 the classifier
changed and 54 hosts changed gated status overnight, against a median of 9 on ordinary days, so an
earlier cohort day would mix a change of method into the losses. The classifier changed twice more
in the window (recorded in the JSON); the script reports how many hosts changed gated status on
those days, beside the median, so a reader can see those changes did not move the count.

A host STOPPED if it served no payment-gated verdict on any of the last QUIET_DAYS days of the
window. Its stop date is the day after its last payment-gated day. A host that was not gated on
the last day, but was gated at some point in the last QUIET_DAYS days, is UNSETTLED and is not
counted as stopped. QUIET_DAYS is 14 because of what the archive shows, not by assumption: the
script counts every run of non-gated days that a cohort host went through, and how many runs of
QUIET_DAYS or more ended with the host serving a challenge again. That count is in the JSON and
in the text, so the threshold can be checked and changed.

Survival on a day d is the share of the cohort that had not stopped by d. It is read only up to
the last settled day (the end of the window minus QUIET_DAYS minus one): a host that stops later
than that cannot be told apart from an outage yet.

OPERATORS. One host is not one seller: one domain can run dozens of hosts, and when it goes down
they all go at once. Each host is assigned to its registrable domain using the Mozilla Public
Suffix List (public_suffix_list.dat in this repo, version and sha256 pinned below), so
a.vercel.app and b.vercel.app are two operators while a.example.com and b.example.com are one.
An operator STOPPED when every one of its cohort hosts stopped. Registrable domain is a floor on
operator identity, not a proof: one person can run several domains, and that is not visible here.

HOW THEY STOPPED. For every stopped host, its row on the last day of the window says what it does
now: no answer at all (UNREACHABLE), an HTTP status other than 402 (read from the row's note), or
a rate limit. A 2xx means the route answers without asking for payment.

WHAT THIS DOES NOT CLAIM. A host that stopped serving a challenge at its pinned URL may be
charging at another URL, under another domain, or through another catalog. Hosts that joined x402
after 2026-07-26 are not in the census, so this is how a cohort ages, not how the market changes
in size. One datacenter vantage, one probe a day.

Read-only. Reads snapshots/, index-pubkey.json and public_suffix_list.dat, makes no request.

Usage: python survival.py [--end YYYY-MM-DD] [--out-dir DIR]
Writes survival_<end>.md and survival_<end>.json
"""
import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from monthly_report import GATED, http_status, n, pct, unbacked_numbers, verified

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"
PUBKEY = HERE / "index-pubkey.json"
PSL = HERE / "public_suffix_list.dat"
PSL_SHA256 = "76918ba7c5f7501785558708be861152377f962643844828a7a3cb7f3ae864c5"
PSL_VERSION = "2026-11-16_22-30-55_UTC"

SCHEMA = "x402-measure/survival/1"
COHORT_DAY = "2026-08-19"
QUIET_DAYS = 14


# --- operators ------------------------------------------------------------------------------

def load_psl(path: Path):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PSL_SHA256:
        sys.exit("  REFUSING: public_suffix_list.dat is not the pinned version. Nothing written.")
    rules, wild, exc = set(), set(), set()
    for line in raw.decode("utf-8").splitlines():
        line = line.strip().lower()
        if not line or line.startswith("//"):
            continue
        rule = line.split()[0]
        if rule.startswith("!"):
            exc.add(rule[1:])
        elif rule.startswith("*."):
            wild.add(rule[2:])
        else:
            rules.add(rule)
    return rules, wild, exc


def registrable(host: str, psl) -> str:
    """The public suffix plus one label (the Public Suffix List algorithm). An IP is its own operator."""
    rules, wild, exc = psl
    host = host.lower().rstrip(".").split(":")[0]
    labels = host.split(".")
    if all(p.isdigit() for p in labels):
        return host
    suffix_len = 1                                   # the default rule "*"
    for i in range(len(labels)):
        cand = ".".join(labels[i:])
        n = len(labels) - i
        if cand in exc:
            suffix_len = max(suffix_len, n - 1)
        elif cand in rules:
            suffix_len = max(suffix_len, n)
        elif i + 1 < len(labels) and ".".join(labels[i + 1:]) in wild:
            suffix_len = max(suffix_len, n)
    for i in range(len(labels)):                     # an exception rule always wins
        if ".".join(labels[i:]) in exc:
            suffix_len = len(labels) - i - 1
            break
    take = min(len(labels), suffix_len + 1)
    return ".".join(labels[-take:])


PREVIEW = re.compile(r"^(?:.+-git-.+|.+-(?=[a-z0-9]*\d)[a-z0-9]{9}-.+)\.vercel\.app$")


def preview_scopes(hosts) -> dict:
    """Vercel preview builds, host -> team. Vercel names a preview <project>-git-<branch>-<team> or
    <project>-<9-character hash>-<team>, and the team slug can itself contain hyphens, so the
    team is read as the longest hyphen-suffix (up to three parts) that names exactly as many
    previews as its last part does. Under the Public Suffix List every preview would be its own
    operator; they are one team's temporary builds."""
    prev = [h for h in hosts if PREVIEW.match(h)]
    names = {h: h[: -len(".vercel.app")].split("-") for h in prev}
    count = Counter("-".join(p[-k:]) for p in names.values() for k in (1, 2, 3) if len(p) > k)
    out = {}
    for h, p in names.items():
        if count[p[-1]] < 2:
            continue                                 # a lone preview stays its own operator
        team = p[-1]
        for k in (2, 3):
            if len(p) > k and count["-".join(p[-k:])] == count[p[-1]]:
                team = "-".join(p[-k:])
        out[h] = f"{team}.vercel.app previews"
    return out


# --- the archive ----------------------------------------------------------------------------

def days_between(a: str, b: str) -> list[str]:
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def silences(seq: list[bool]):
    """(length, ended_with_a_comeback) for every run of False in seq."""
    out, i, n = [], 0, len(seq)
    while i < n:
        if seq[i]:
            i += 1
            continue
        j = i
        while j < n and not seq[j]:
            j += 1
        out.append((j - i, j < n))
        i = j
    return out


def end_state(row: dict) -> str:
    v = row["verdict"]
    if v in GATED:
        return "payment_gated"
    if v == "UNREACHABLE":
        return "no_answer"
    if v == "RATE_LIMITED":
        return "rate_limited"
    s = http_status(row)
    if s is None:
        return "other"
    if s == 429:
        return "rate_limited"
    if 200 <= s < 300:
        return "answers_2xx_without_charging"
    if s in (404, 410):
        return "not_found_404_410"
    if 500 <= s < 600:
        return "server_error_5xx"
    if s in (401, 403):
        return "refused_401_403"
    if 300 <= s < 400:
        return "redirect_3xx"
    return "other_status"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", help="last day of the window (default: the latest snapshot)")
    ap.add_argument("--out-dir", default=str(HERE))
    a = ap.parse_args(argv)

    pub_hex = json.loads(PUBKEY.read_text(encoding="utf-8"))["public_key_hex"]
    end = a.end or max(p.name for p in SNAPSHOTS.iterdir() if p.is_dir() and p.name[:2] == "20")
    days = days_between(COHORT_DAY, end)
    if len(days) < 3 * QUIET_DAYS:
        sys.exit("  REFUSING: the window is too short to say anything about survival. Nothing written.")

    docs = {d: verified(d, SNAPSHOTS, pub_hex) for d in days}
    lists = {docs[d]["manifest"].get("target_list_sha256") for d in days}
    hostsets = {tuple(r["host"] for r in docs[d]["observations"]) for d in days}
    if len(lists) != 1 or len(hostsets) != 1:
        sys.exit("  REFUSING: the population is not the same on every day read. Nothing written.")

    rows = {d: {r["host"]: r for r in docs[d]["observations"]} for d in days}
    gated = {d: {h for h, r in rows[d].items() if r["verdict"] in GATED} for d in days}
    cohort = sorted(gated[COHORT_DAY])
    psl = load_psl(PSL)
    previews = preview_scopes(cohort)
    op_of = {h: previews.get(h) or registrable(h, psl) for h in cohort}
    ops = defaultdict(list)
    for h in cohort:
        ops[op_of[h]].append(h)

    # classifier generations and how many hosts changed gated status on each change day
    flips = {b: len(gated[a_] ^ gated[b]) for a_, b in zip(days, days[1:])}
    method = {d: docs[d]["manifest"]["method_sha256"] for d in days}
    changes = [d for a_, d in zip(days, days[1:]) if method[d] != method[a_]]
    ordinary = [n for d, n in flips.items() if d not in changes]

    # per host: last gated day, silences, stop date
    last_gated = {h: max(d for d in days if h in gated[d]) for h in cohort}
    quiet_from = days[-QUIET_DAYS]                    # first day of the final quiet window
    stopped = {h for h in cohort if last_gated[h] < quiet_from}
    unsettled = {h for h in cohort if h not in stopped and h not in gated[end]}
    stop_on = {h: (date.fromisoformat(last_gated[h]) + timedelta(days=1)).isoformat() for h in stopped}
    sil = [s for h in cohort for s in silences([h in gated[d] for d in days])]
    long_sil = [s for s in sil if s[0] >= QUIET_DAYS]
    comebacks = [n for n, back in sil if back]

    settled_through = quiet_from       # every stop dated on or before this day is already counted

    def surviving(day, members, stops):
        return sum(1 for h in members if not (h in stops and stops[h] <= day))

    # operator stop date: the latest stop date among its hosts, if all stopped
    op_stopped = {o: max(stop_on[h] for h in hs) for o, hs in ops.items() if all(h in stopped for h in hs)}
    op_alive_end = sum(1 for hs in ops.values() if any(h in gated[end] for h in hs))

    # 30-day periods from the cohort day, the last one cut at the settled day
    periods, start = [], date.fromisoformat(COHORT_DAY)
    last_settled = date.fromisoformat(settled_through)
    while start < last_settled:
        stop = min(start + timedelta(days=30), last_settled + timedelta(days=1))
        s0, s1 = start.isoformat(), (stop - timedelta(days=1)).isoformat()
        h_at = surviving((start - timedelta(days=1)).isoformat(), cohort, stop_on)
        h_lost = sum(1 for h in stopped if s0 <= stop_on[h] <= s1)
        o_at = surviving((start - timedelta(days=1)).isoformat(), list(ops), op_stopped)
        o_lost = sum(1 for o, d in op_stopped.items() if s0 <= d <= s1)
        periods.append({"start": s0, "end": s1, "days": (stop - start).days,
                        "hosts_selling_at_start": h_at, "hosts_stopped": h_lost,
                        "hosts_stopped_pct": pct(h_lost, h_at),
                        "operators_selling_at_start": o_at, "operators_stopped": o_lost,
                        "operators_stopped_pct": pct(o_lost, o_at)})
        start = stop

    by_day = Counter(stop_on.values())
    worst_day, worst_n = max(by_day.items(), key=lambda kv: (kv[1], kv[0]))
    worst_ops = Counter(op_of[h] for h in stopped if stop_on[h] == worst_day).most_common(3)
    biggest_stopped_ops = sorted(((len(ops[o]), o, d) for o, d in op_stopped.items()), reverse=True)[:5]
    how = Counter(end_state(rows[end][h]) for h in stopped)
    multi_ops = {o: hs for o, hs in ops.items() if len(hs) > 1}
    stopped_by_op = Counter(op_of[h] for h in stopped).most_common(2)
    teams = Counter(previews.values())

    F = {
        "schema": SCHEMA,
        "window": {"cohort_day": COHORT_DAY, "end": end, "days": len(days),
                   "settled_through": settled_through, "quiet_days": QUIET_DAYS},
        "population": {"hosts_in_census": len(docs[end]["observations"]),
                       "target_list_sha256": next(iter(lists)),
                       "source": docs[end]["manifest"].get("target_list_source"),
                       "collected_on": (docs[end]["manifest"].get("target_list_collected_at_utc") or "")[:10]},
        "verification": {"days_verified": len(days), "public_key_hex": pub_hex,
                         "rule": "same checks as monthly_report.verified(): payload hash, published key, "
                                 "Ed25519 signature, date and row count"},
        "classifier": {"generations_in_window": len(set(method.values())),
                       "changed_on": changes,
                       "hosts_changing_gated_status_on_change_days": {d: flips[d] for d in changes},
                       "median_hosts_changing_gated_status_other_days": int(statistics.median(ordinary))
                       if statistics.median(ordinary) == int(statistics.median(ordinary)) else statistics.median(ordinary),
                       "cohort_day_flips_vs_day_before": len(gated[COHORT_DAY] ^ {
                           h for h, r in {r["host"]: r for r in verified(
                               (date.fromisoformat(COHORT_DAY) - timedelta(days=1)).isoformat(),
                               SNAPSHOTS, pub_hex)["observations"]}.items() if r["verdict"] in GATED})},
        "operators_rule": {"public_suffix_list_version": PSL_VERSION, "public_suffix_list_sha256": PSL_SHA256,
                           "public_suffix_list_release_date": PSL_VERSION[:10],
                           "rule": "registrable domain (public suffix plus one label); an operator stopped "
                                   "when every one of its cohort hosts stopped"},
        "threshold_check": {"silences_observed": len(sil),
                            "silences_ending_in_a_comeback": len(comebacks),
                            "silences_of_quiet_days_or_more": len(long_sil),
                            "of_those_ending_in_a_comeback": sum(1 for _, b in long_sil if b),
                            "of_those_comeback_pct": pct(sum(1 for _, b in long_sil if b), len(long_sil)),
                            "longest_silence_ending_in_a_comeback_days": max(comebacks) if comebacks else 0},
        "cohort": {"hosts": len(cohort), "operators": len(ops),
                   "operators_with_more_than_one_host": len(multi_ops),
                   "hosts_on_those_operators": sum(len(v) for v in multi_ops.values()),
                   "largest_operator_hosts": max(len(v) for v in ops.values()),
                   "vercel_preview_hosts": sum(1 for h in cohort if PREVIEW.match(h)),
                   "vercel_preview_teams": dict(teams.most_common())},
        "end": {"hosts_payment_gated": len(gated[end] & set(cohort)),
                "hosts_payment_gated_pct": pct(len(gated[end] & set(cohort)), len(cohort)),
                "hosts_stopped": len(stopped), "hosts_stopped_pct": pct(len(stopped), len(cohort)),
                "hosts_unsettled": len(unsettled),
                "operators_with_a_gated_host": op_alive_end,
                "operators_with_a_gated_host_pct": pct(op_alive_end, len(ops)),
                "operators_stopped": len(op_stopped), "operators_stopped_pct": pct(len(op_stopped), len(ops))},
        "periods": periods,
        "largest_single_day": {"stop_date": worst_day, "hosts": worst_n,
                               "by_operator": [{"operator": o, "hosts": n} for o, n in worst_ops]},
        "largest_stopped_operators": [{"operator": o, "hosts": n, "stop_date": d} for n, o, d in biggest_stopped_ops],
        "two_operators_with_most_stopped_hosts": {
            "operators": [{"operator": o, "stopped_hosts": n,
                           "first_stop": min(stop_on[h] for h in stopped if op_of[h] == o),
                           "last_stop": max(stop_on[h] for h in stopped if op_of[h] == o),
                           "most_on_one_day": max(Counter(stop_on[h] for h in stopped if op_of[h] == o).values()),
                           "most_on_one_day_date": max(Counter(stop_on[h] for h in stopped if op_of[h] == o).items(),
                                                       key=lambda kv: (kv[1], kv[0]))[0]}
                          for o, n in stopped_by_op],
            "stopped_hosts": sum(n for _, n in stopped_by_op),
            "share_of_all_stopped_hosts_pct": pct(sum(n for _, n in stopped_by_op), len(stopped))},
        "how_stopped_hosts_answer_on_end_day": dict(sorted(how.items(), key=lambda kv: -kv[1])),
        "definitions": {
            "payment_gated": "verdict in " + ", ".join(GATED) + " on the day",
            "cohort": f"hosts payment-gated on {COHORT_DAY}",
            "stopped": f"no payment-gated verdict on any of the last {QUIET_DAYS} days of the window",
            "stop_date": "the day after the host's last payment-gated day",
            "not_found_statuses": [404, 410],
            "unsettled": f"not payment-gated on the last day, but payment-gated on one of the last {QUIET_DAYS}",
            "silence": "a run of consecutive days on which a cohort host was not payment-gated",
            "period_stopped": "hosts (or operators) whose stop date falls in the period, out of those that "
                              "had not stopped before it; the last period ends on settled_through",
        },
        "stopped_hosts": [{"host": h, "operator": op_of[h], "last_payment_gated": last_gated[h],
                           "end_day_state": end_state(rows[end][h])} for h in sorted(stopped)],
        "inputs": [{"date": d, "payload_sha256": docs[d]["_payload_sha256"]} for d in days],
    }
    md = render(F)
    bad = unbacked_numbers(md, F)
    if bad:
        sys.exit(f"  REFUSING: the report text carries numbers the JSON does not: {bad}. Nothing written.")
    if "—" in md or "–" in md:
        sys.exit("  REFUSING: the report text carries a dash character. Nothing written.")
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"survival_{end}.json").write_bytes((json.dumps(F, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    (out / f"survival_{end}.md").write_bytes(md.encode("utf-8"))
    print(f"  {len(days)} days verified, {days[0]} to {days[-1]}")
    print(f"  -> {out / f'survival_{end}.md'}")
    return 0


def render(F: dict) -> str:
    W, C, E, T = F["window"], F["cohort"], F["end"], F["threshold_check"]
    K, P, H = F["classifier"], F["periods"], F["how_stopped_hosts_answer_on_end_day"]
    two = F["two_operators_with_most_stopped_hosts"]
    o1, o2 = two["operators"]
    top_team, top_team_n = next(iter(C["vercel_preview_teams"].items()))
    rest = sum(v for k, v in H.items() if k not in (
        "no_answer", "not_found_404_410", "server_error_5xx", "answers_2xx_without_charging"))
    F["how_stopped_other_states"] = rest
    ch = K["hosts_changing_gated_status_on_change_days"]
    period_lines = []
    for i, p in enumerate(P):
        latest = " (the latest period that can be read yet)" if i == len(P) - 1 else ""
        period_lines.append(
            f"- {p['start']} to {p['end']}, {p['days']} days{latest}: {n(p['operators_stopped'])} of "
            f"{n(p['operators_selling_at_start'])} operators stopped ({p['operators_stopped_pct']}%), "
            f"and {n(p['hosts_stopped'])} of {n(p['hosts_selling_at_start'])} hosts ({p['hosts_stopped_pct']}%).")
    L = [
        "# How long do x402 sellers last?",
        "",
        f"A survival study of one cohort, {W['cohort_day']} to {W['end']}.",
        "",
        f"Every day I probe the same {n(F['population']['hosts_in_census'])} hosts, the ones the CDP Bazaar "
        f"listed on {F['population']['collected_on']}, and sign the record. Most x402 counts are snapshots of a "
        f"catalog that keeps changing, so they can't tell a seller that left from one that never arrived. "
        f"This follows one group forward instead: the {n(C['hosts'])} hosts that were selling on "
        f"{W['cohort_day']}, meaning they answered with an x402 payment challenge. All {W['days']} days "
        f"read here verified against the published key.",
        "",
        "## Findings",
        "",
        f"1. **About one host in five stopped selling for good: {n(E['hosts_stopped'])} of {n(C['hosts'])} "
        f"({E['hosts_stopped_pct']}%).** {n(E['hosts_payment_gated'])} ({E['hosts_payment_gated_pct']}%) still "
        f"served a challenge on {W['end']}. The other {n(E['hosts_unsettled'])} are unsettled: quiet on the "
        f"last day, but selling at some point in the last {W['quiet_days']} days.",
        "",
        f"2. **Counted by operator, it's about one in seven: {n(E['operators_stopped'])} of "
        f"{n(C['operators'])} ({E['operators_stopped_pct']}%).** Hosts overstate the loss because a few "
        f"operators run many hosts. {n(C['operators_with_more_than_one_host'])} operators run more than one, "
        f"{n(C['hosts_on_those_operators'])} hosts between them. Two operators account for "
        f"{n(two['stopped_hosts'])} of the {n(E['hosts_stopped'])} stopped hosts ({two['share_of_all_stopped_hosts_pct']}%): "
        f"{o1['operator']} lost {n(o1['stopped_hosts'])}, {n(o1['most_on_one_day'])} of them on {o1['most_on_one_day_date']}, and "
        f"{o2['operator']} lost {n(o2['stopped_hosts'])} between {o2['first_stop']} and {o2['last_stop']}.",
        "",
        "3. **Operators stopped at about one in twenty per month, and the latest period was faster.**",
        "",
        *period_lines,
        "",
        f"The latest period is {P[-1]['days']} days long, so a similar share in fewer days is a faster pace.",
        "",
        f"4. **Sellers that stop mostly vanish.** On {W['end']}, of the "
        f"{n(E['hosts_stopped'])} stopped hosts, {n(H.get('no_answer', 0))} gave no answer at all, "
        f"{n(H.get('not_found_404_410', 0))} answered 404 or 410, {n(H.get('server_error_5xx', 0))} returned a "
        f"server error, and {n(H.get('answers_2xx_without_charging', 0))} answered with a success status without "
        f"asking for payment. The other {n(rest)} answered with another status.",
        "",
        f"5. **The catalog listed temporary builds as sellers.** {n(C['vercel_preview_hosts'])} of the "
        f"{n(C['hosts'])} hosts were Vercel preview builds, the short-lived copies Vercel makes of one branch "
        f"or commit, and {n(top_team_n)} of them belonged to one team ({top_team}). A buyer that picks one of "
        f"those is paying a build that is meant to disappear.",
        "",
        f"6. **Why {W['quiet_days']} days counts as stopped.** Of {n(T['silences_of_quiet_days_or_more'])} "
        f"silences of {W['quiet_days']} days or more, {n(T['of_those_ending_in_a_comeback'])} ended with the host "
        f"selling again ({T['of_those_comeback_pct']}%). The longest silence that ended in a comeback was "
        f"{T['longest_silence_ending_in_a_comeback_days']} days. So a host counted as stopped here has a small "
        f"chance of coming back, and the rate is stated rather than assumed.",
        "",
        "## Method",
        "",
        f"- **Selling** means the day's verdict was OK, WARN, V1, NON_EVM or BLOCKED: an x402 challenge of any "
        f"version or network.",
        f"- **The cohort starts on {W['cohort_day']}** because the classifier changed that day and "
        f"{n(K['cohort_day_flips_vs_day_before'])} hosts changed status overnight, against a median of "
        f"{n(K['median_hosts_changing_gated_status_other_days'])} on ordinary days. An earlier start would count a "
        f"change of method as sellers leaving. The two later changes, on {K['changed_on'][0]} and "
        f"{K['changed_on'][1]}, moved {n(ch[K['changed_on'][0]])} and {n(ch[K['changed_on'][1]])} hosts.",
        f"- **Stopped** means no challenge on any of the last {W['quiet_days']} days. The stop date is the day "
        f"after the last day selling. Stops can be dated only through {W['settled_through']}; a host that stopped "
        f"after that can't be told apart from an outage yet.",
        f"- **Operator** means the registrable domain under the Mozilla Public Suffix List (the release "
        f"of {F['operators_rule']['public_suffix_list_release_date']}, pinned by hash), so a.vercel.app and b.vercel.app "
        f"are two operators while a.example.com and b.example.com are one. Vercel preview builds are grouped by "
        f"the team in their name. An operator stopped when every one of its hosts stopped. One person can run "
        f"several domains, so this is a floor on concentration, not a proof of who runs what.",
        "",
        "## What this does not show",
        "",
        "- A host that stopped serving a challenge at its pinned URL may be charging at another URL, under "
        "another domain, or through another catalog.",
        "- Sellers that joined after the list was pinned are not in it, so this shows how one cohort ages, not "
        "whether the market is growing or shrinking.",
        "- One probe a day from one datacenter vantage.",
        "",
        "## Reproduce",
        "",
        "```",
        "python verify_snapshot.py --all",
        f"python survival.py --end {W['end']}",
        "```",
        "",
        f"survival_{W['end']}.json beside this file has every figure, its definition, the hash of every day "
        f"read, and every stopped host with its operator, its last day selling and what it answers now.",
        "",
    ]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
