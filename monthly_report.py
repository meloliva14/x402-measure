#!/usr/bin/env python3
"""State of x402 deployments: one dated monthly report, computed from the signed daily snapshots only.

WHY THIS EXISTS. Figures from this census are quoted in x402 Foundation working-group threads, each
one cut by hand from whichever script answered the question that week. A monthly report with fixed
definitions, a fixed window and a prior-month comparison makes the figures citable by date, and
makes a change between two months a measurement rather than a recollection. Every number in it is
derived here, from the signed files, so a reader who distrusts one can rerun it.

METHOD. The window ends on --end (default: the latest snapshot) and starts the day after the same
date one calendar month earlier, so the 2026-11 issue reads 2026-10-17 to 2026-11-16. The prior
window is the calendar month before that, and the hosts-that-stopped comparison for the prior
month needs one more month before it, so three windows are read. Every day in all three is
verified the way verify_snapshot.py verifies it (payload hash, published key, Ed25519 signature,
row count), over the same bytes that are then parsed, and the date inside the file must match the
folder. One missing or unverified day and the script exits without writing anything. A day whose
target list differs from the others also stops it: a different population is a different census.

State figures are read on the last day of each window, so each one reproduces from a single
signed file. Figures over a whole window (prices, hosts that stopped or started) read every day.
"Payment-gated" is the GATED set notgated_runs.py and rate_limited_history.py already use (OK,
WARN, V1, NON_EVM, BLOCKED); UNKNOWN_NETWORK and UNPARSEABLE are counted in the JSON beside it
and are not folded in. "Signable" is the OK verdict, as in the README headline. A price is
accepts[0].amount at the pinned URL, read out of the note preflight.decide() writes on an OK row;
the asset is read from the same note. The HTTP status of a not-gated row is read out of its note,
because a 5xx and a 429 say nothing about whether a route is gated (origin_error_history.py,
notgated_runs.py), and the note carries the status under both eras' labelling.

WHAT THIS DOES NOT CLAIM. It describes 1,521 hosts pinned from one registry on one date, from one
datacenter vantage, once a day. It is not the state of x402. A host that stopped serving a
challenge at its pinned URL may be charging somewhere else, and a host with no usable answer may
be down for reasons that have nothing to do with x402. A changed price is a changed accepts[0]
at one route, which for some hosts is dynamic pricing rather than a decision. The network of an
OK row is not recorded, so the chain behind an asset is inferred from its contract address.
payTo is not recorded in the snapshots at all, so nothing here says anything about wallets.

Read-only. Reads snapshots/ and index-pubkey.json, makes no request, signs nothing.

Usage: python monthly_report.py [--end YYYY-MM-DD] [--out-dir DIR]
Writes state_of_x402_<YYYY-MM>.md and state_of_x402_<YYYY-MM>.json
"""
import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import rpc

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"
PUBKEY = HERE / "index-pubkey.json"

SCHEMA = "x402-measure/monthly-report/1"
COHORT_DAY = "2026-08-19"          # survival.py's cohort, quoted from the 2026-12 issue on
FIRST_ISSUE = "2026-11"            # issue numbers count from here, so issue N is derivable
GATED = ("OK", "WARN", "V1", "NON_EVM", "BLOCKED")
USDC_DECIMALS = 6                  # same constant demand_sweep.py and rpc.py divide by
ASSETS = {rpc.USDC.lower(): "base_usdc", rpc.USDC_BASE_SEPOLIA.lower(): "base_sepolia_usdc"}
PRICE_NOTE = re.compile(r"^amount=(\S+) asset=(\S+) extra\.name=")
HTTP_NOTE = re.compile(r"^HTTP (\d{3}) - ")


# --- reading the archive -----------------------------------------------------------------

def verified(day: str, snapshots: Path, pub_hex: str) -> dict:
    """The parsed observation for `day`, or SystemExit. Same checks as verify_snapshot.check(),
    run over the bytes in hand, so the file that verified is the file that gets counted."""
    obs, sigf = snapshots / day / "observation.json", snapshots / day / "signature.json"
    if not obs.exists() or not sigf.exists():
        sys.exit(f"  REFUSING: {day} is missing from the archive. Nothing written.")
    payload = obs.read_bytes()
    meta = json.loads(sigf.read_text(encoding="utf-8"))
    if hashlib.sha256(payload).hexdigest() != meta.get("payload_sha256"):
        sys.exit(f"  REFUSING: {day} observation.json does not match its signed hash. Nothing written.")
    if meta.get("public_key_hex") != pub_hex:
        sys.exit(f"  REFUSING: {day} is signed by a key that is not the published one. Nothing written.")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(
            bytes.fromhex(meta["signature_hex"]), payload)
    except InvalidSignature:
        sys.exit(f"  REFUSING: {day} signature does not verify. Nothing written.")
    doc = json.loads(payload)
    if doc.get("date") != day:
        sys.exit(f"  REFUSING: {day} carries date {doc.get('date')!r}. Nothing written.")
    if doc["manifest"].get("hosts_observed") != len(doc.get("observations", [])):
        sys.exit(f"  REFUSING: {day} row count does not match its manifest. Nothing written.")
    doc["_payload_sha256"] = meta["payload_sha256"]
    return doc


def month_back(d: date) -> date:
    """The same day one calendar month earlier, clamped to the end of a shorter month."""
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError(d)


def window(end: date) -> list[str]:
    start = month_back(end) + timedelta(days=1)
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


# --- reading one row ---------------------------------------------------------------------

def price(row: dict):
    """(amount, asset) from an OK row's note, or None. The note is the last one on the row
    because a retried row carries the retry note first."""
    if row["verdict"] != "OK" or not row.get("notes"):
        return None
    m = PRICE_NOTE.match(row["notes"][-1])
    return (m.group(1), m.group(2).lower()) if m else None


def http_status(row: dict):
    for n in row.get("notes") or []:
        m = HTTP_NOTE.match(n)
        if m:
            return int(m.group(1))
    return None


def answered_without_challenge(row: dict) -> bool:
    """NO_402 on a status that says something about the route: not 5xx, not 429."""
    s = http_status(row)
    return row["verdict"] == "NO_402" and s is not None and s != 429 and not 500 <= s < 600


def pct(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


def usdc(atomic) -> str:
    q = Decimal(str(atomic)) / (Decimal(10) ** USDC_DECIMALS)
    s = format(q.normalize(), "f")
    return s


# --- figures -----------------------------------------------------------------------------

def day_state(doc: dict) -> dict:
    rows = doc["observations"]
    v = Counter(r["verdict"] for r in rows)
    gated = sum(v[k] for k in GATED)
    ok = [r for r in rows if r["verdict"] == "OK"]
    prices = [p for p in (price(r) for r in ok) if p]
    assets = Counter(ASSETS.get(a, "other") for _, a in prices)
    base = sorted(int(amt) for amt, a in prices if a == rpc.USDC.lower() and amt.isdigit())
    med = statistics.median(base) if base else None
    sm = doc["manifest"].get("signed_manifests") or {}
    smv = sm.get("verdicts") or {}
    return {
        "date": doc["date"],
        "hosts_observed": len(rows),
        "answered": doc["manifest"]["answered"],
        "verdicts": dict(sorted(v.items())),
        "payment_gated": gated,
        "signable": v["OK"],
        "signable_share_pct": pct(v["OK"], gated),
        "blocked": v["BLOCKED"],
        "signable_with_caveats": v["WARN"],
        "v1_only": v["V1"],
        "both_dialects": sum(1 for r in ok if r.get("v1") == "V1_OK"),
        "ok_rows_without_price_note": len(ok) - len(prices),
        "signable_by_asset": {k: assets.get(k, 0) for k in ("base_usdc", "base_sepolia_usdc", "other")},
        "other_assets": dict(sorted(Counter(a for _, a in prices if a not in ASSETS).items())),
        "median_price_base_usdc": {"hosts": len(base), "atomic": med,
                                   "usdc": usdc(med) if med is not None else None},
        "manifest_population": sm.get("population"),
        "manifest_status": sm.get("status"),
        "manifest_answered_2xx": (sm.get("checked", 0) - smv.get("unreachable", 0)
                                  - smv.get("refused", 0)) if sm else None,
        "manifest_carrying_a_signature": sm.get("carrying_a_signature"),
    }


def churn(docs: dict, this: list[str], before: list[str]) -> dict:
    """Hosts that served a challenge on some day of `before` and on no day of `this`, and the
    reverse. Any-day membership on both sides, so a host flapping to UNREACHABLE for a day or a
    week is never counted as having stopped."""
    hosts = [r["host"] for r in docs[this[-1]]["observations"]]
    rows = {d: {r["host"]: r for r in docs[d]["observations"]} for d in this + before}
    g_now = {h for h in hosts if any(rows[d][h]["verdict"] in GATED for d in this)}
    g_then = {h for h in hosts if any(rows[d][h]["verdict"] in GATED for d in before)}
    stopped = sorted(g_then - g_now)
    spoke = [h for h in stopped if any(answered_without_challenge(rows[d][h]) for d in this)]
    return {
        "served_a_challenge_in_prior_window": len(g_then),
        "served_a_challenge_in_window": len(g_now),
        "stopped": len(stopped),
        "stopped_answered_without_challenge": len(spoke),
        "stopped_no_usable_answer": len(stopped) - len(spoke),
        "started": len(g_now - g_then),
        "stopped_hosts": stopped,
        "started_hosts": sorted(g_now - g_then),
    }


def price_moves(docs: dict, days: list[str]) -> dict:
    """Per host, every OK reading of accepts[0] across the window, in date order."""
    seq: dict[str, list] = {}
    for d in days:
        for r in docs[d]["observations"]:
            p = price(r)
            if p:
                seq.setdefault(r["host"], []).append(p)
    read = {h: s for h, s in seq.items() if len(s) >= 2}
    same_asset = {h: s for h, s in read.items() if len({a for _, a in s}) == 1}
    varied = sorted(h for h, s in same_asset.items() if len({amt for amt, _ in s}) > 1)

    def num(x):
        return Decimal(x) if re.fullmatch(r"\d+(\.\d+)?", x) else None

    up = down = 0
    for h in varied:
        a, b = num(same_asset[h][0][0]), num(same_asset[h][-1][0])
        if a is not None and b is not None:
            up += b > a
            down += b < a
    return {
        "hosts_read_on_two_or_more_days": len(read),
        "asset_changed": len(read) - len(same_asset),
        "read_on_two_or_more_days_one_asset": len(same_asset),
        "more_than_one_price": len(varied),
        "ended_higher": up,
        "ended_lower": down,
        "ended_where_it_started": len(varied) - up - down,
        "hosts": varied,
    }


# --- the report --------------------------------------------------------------------------

def n(x) -> str:
    return f"{x:,}"


def delta(now, then) -> str:
    d = now - then
    return "unchanged" if d == 0 else f"{'up' if d > 0 else 'down'} {n(abs(d))}"


def render(F: dict) -> str:
    c, p = F["state"]["window_end"], F["state"]["prior_window_end"]
    ch, chp = F["stopped_or_started"]["window"], F["stopped_or_started"]["prior_window"]
    pr, prp = F["price_changes"]["window"], F["price_changes"]["prior_window"]
    W, P = F["window"], F["prior_window"]
    same = F["classifier"]["identical_across_window_and_prior"]
    mc, mp = c["median_price_base_usdc"], p["median_price_base_usdc"]
    sa, sp = c["signable_by_asset"], p["signable_by_asset"]
    L = [
        f"# State of x402 deployments, {F['issue']}",
        "",
        f"Issue {F['issue_number']}. This covers {W['start']} to {W['end']} ({W['days']} days) and compares it "
        f"with {P['start']} to {P['end']} ({P['days']} days).",
        "",
        f"Every day I probe the same {n(c['hosts_observed'])} hosts, the ones the CDP Bazaar listed on "
        f"{F['population']['collected_on']}, and sign the record. Every figure here is computed by a script "
        f"from those signed records, and the script refuses to report on a day whose signature does not verify. "
        f"All {F['verification']['days_verified']} days it read verified."
        + (" The classifier was byte-identical on every day of both months." if same else
           " The classifier changed during these two months, so read the comparisons with that in mind."),
        "",
        f"State figures are read on the last day of each month: {c['date']}, against {p['date']}. "
        f"On {c['date']}, {n(c['answered'])} of {n(c['hosts_observed'])} hosts gave an answer of any kind "
        f"({n(p['answered'])} on {p['date']}).",
        "",
        "## Figures",
        "",
        f"1. **Payment-gated hosts: {n(c['payment_gated'])}**, {delta(c['payment_gated'], p['payment_gated'])} "
        f"from {n(p['payment_gated'])}. A host counts if it answered with an x402 challenge of any version or "
        f"network (verdict OK, WARN, V1, NON_EVM or BLOCKED).",
        "",
        f"2. **Signable by a stock v2 client: {n(c['signable'])} of {n(c['payment_gated'])} "
        f"({c['signable_share_pct']}%)**, against {n(p['signable'])} of {n(p['payment_gated'])} "
        f"({p['signable_share_pct']}%). Signable means verdict OK: a stock @x402/evm 2.x buyer could build a "
        f"payment from the challenge with no caveats. Hosts signable only with caveats (verdict WARN) are not "
        f"counted: {n(c['signable_with_caveats'])} this month, {n(p['signable_with_caveats'])} before. "
        f"{n(c['blocked'])} hosts served a v2 challenge it cannot sign ({n(p['blocked'])} before).",
        "",
        f"3. **v1 only: {n(c['v1_only'])} hosts**, {delta(c['v1_only'], p['v1_only'])} from "
        f"{n(p['v1_only'])}. These serve a v1 challenge in the body and a v2 client cannot read it at all. "
        f"Separately, {n(c['both_dialects'])} signable hosts also serve a body the v1 client x402-fetch can "
        f"read, so both generations of buyer can pay them ({n(p['both_dialects'])} before).",
        "",
        f"4. **Stopped serving a challenge: {n(ch['stopped'])} hosts** served one on at least one day of the "
        f"prior month and on no day of this one. {n(ch['stopped_answered_without_challenge'])} of them answered "
        f"with another HTTP status at least once; {n(ch['stopped_no_usable_answer'])} gave no usable answer all "
        f"month (no connection, a 5xx origin error, or a 429). **Started: {n(ch['started'])}**, a challenge this "
        f"month after none the month before. In the prior month the same counts were {n(chp['stopped'])} "
        f"stopped and {n(chp['started'])} started"
        + (f", measured against a baseline month ({F['baseline_for_prior_churn']['start']} to "
           f"{F['baseline_for_prior_churn']['end']}) in which the classifier ran in "
           f"{F['classifier']['baseline_method_versions']} versions, so that pair is the less exact one."
           if F["classifier"]["baseline_method_versions"] > 1 else "."),
        "",
        f"5. **Price changes: {n(pr['more_than_one_price'])} of {n(pr['read_on_two_or_more_days_one_asset'])} "
        f"signable hosts** showed more than one price at their pinned URL during the month. Price means "
        f"accepts[0].amount, and a host counts if it was signable on at least two days with the same asset. "
        f"{n(pr['ended_higher'])} ended the month higher than they started it, {n(pr['ended_lower'])} lower, "
        f"and {n(pr['ended_where_it_started'])} back where they started. Prior month: "
        f"{n(prp['more_than_one_price'])} of {n(prp['read_on_two_or_more_days_one_asset'])}. "
        f"{n(pr['asset_changed'])} hosts switched asset during the month and are left out of this count.",
        "",
        f"6. **Median price: {mc['usdc']} USDC**, over the {n(mc['hosts'])} signable hosts quoting the Base "
        f"mainnet USDC contract on {c['date']} ({mp['usdc']} USDC over {n(mp['hosts'])} on {p['date']}).",
        "",
        f"7. **Assets: {n(sa['base_usdc'])} of {n(c['signable'])} signable hosts quote the Base mainnet USDC "
        f"contract, {n(sa['base_sepolia_usdc'])} quote the Base Sepolia testnet USDC contract, and "
        f"{n(sa['other'])} quote something else** ({n(sp['base_usdc'])}, {n(sp['base_sepolia_usdc'])} and "
        f"{n(sp['other'])} before). The snapshot records the contract address, not the network, so the chain "
        f"is read from the address. A testnet challenge is signable and moves no real money.",
        "",
        f"8. **Discovery manifests: {n(c['manifest_answered_2xx'])} of the {n(c['manifest_population'])} hosts "
        f"pinned as manifest publishers** answered /.well-known/x402 with a success status "
        f"({n(p['manifest_answered_2xx'])} before). That counts a response, not a valid manifest. Hosts serving "
        f"a signature document: {n(F['manifest_signatures']['window_max'])} on every day of the month, and "
        f"{n(F['manifest_signatures']['prior_window_max'])} in the month before.",
        "",
        *([f"9. **Still selling from the August cohort: {n(F['cohort']['still_gated'])} of "
           f"{n(F['cohort']['hosts'])} hosts** that were payment-gated on {F['cohort']['day']} were "
           f"payment-gated on {c['date']} ({F['cohort']['still_gated_pct']}%). The survival study "
           f"(survival.py) follows this cohort day by day, by host and by operator.", ""]
          if "cohort" in F else []),
        "## What this does not show",
        "",
        "- Wallets. The snapshots do not record payTo, so nothing here says whether a payout address moved "
        "or is shared. That needs a different instrument.",
        "- Networks in general. Only the first accepts[] entry is classified, and for a signable host the "
        "network itself is not written down, only the asset. A host offering Solana second is invisible here.",
        "- Hosts outside the pinned list. Hosts that joined the Bazaar after the list was pinned are not in "
        "this census, so started counts only hosts already on it.",
        "- Intent. A host that stopped serving a challenge at its pinned URL may be charging somewhere else.",
        "",
        "Method and data: meloliva14/x402-measure",
        "",
        *(["The census states its definitions (unit, population, probe, verdicts, and where the payment "
           "terms are read) in measurement_card.json beside this file.", ""] if F["issue"] >= "2026-12" else []),
        "To reproduce, from a clone:",
        "",
        "```",
        "python verify_snapshot.py --all",
        f"python monthly_report.py --end {W['end']}",
        "```",
        "",
        f"Every figure above, with its definition and the hash of each day it read, is in "
        f"state_of_x402_{F['issue']}.json beside this file.",
        "",
    ]
    return "\n".join(L)


# --- the guard -----------------------------------------------------------------------------

def leaves(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from leaves(v)
    elif isinstance(o, list):
        for v in o:
            yield from leaves(v)
    else:
        yield o


def unbacked_numbers(md: str, figures: dict) -> list[str]:
    """Every number in the Markdown that is not a value in the JSON. Dates and dotted versions
    must appear among the JSON's strings; plain numbers must equal a JSON number (sign ignored,
    because the prose says up or down). Digits glued to letters (v2, x402, 2.x, eip155) are
    names, not figures."""
    vals = list(leaves(figures))
    strings = [v for v in vals if isinstance(v, str)]
    nums = {abs(Decimal(str(v))) for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)}
    nums |= {abs(Decimal(v)) for v in strings if re.fullmatch(r"-?\d+(\.\d+)?", v)}
    bad = []
    text = re.sub(r"(?m)^\d+\. ", " ", md)          # list markers are positions, not figures
    for tok in re.findall(r"\d{4}-\d{2}-\d{2}|\d{4}-\d{2}(?!\d)", text):
        if not any(tok in s for s in strings):
            bad.append(tok)
    text = re.sub(r"\d{4}-\d{2}-\d{2}|\d{4}-\d{2}(?!\d)", " ", text)
    # host names are names, even when a label is hyphenated digits (agents.204-168-199-108.sslip.io):
    # dot-joined labels ending in a label that starts with a letter, so 12.5 stays a figure
    text = re.sub(r"(?<![\w.-])(?:[A-Za-z0-9-]+\.)+[A-Za-z][A-Za-z0-9-]*", " ", text)
    text = re.sub(r"[A-Za-z@/_.]*[A-Za-z][\w.@/]*\d[\w.@/]*|\d+[A-Za-z][\w.]*", " ", text)
    for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        if abs(Decimal(tok.replace(",", ""))) not in nums:
            bad.append(tok)
    return bad


# --- main ----------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", help="last day of the window (default: the latest snapshot)")
    ap.add_argument("--out-dir", default=str(HERE))
    ap.add_argument("--snapshots", default=str(SNAPSHOTS), help=argparse.SUPPRESS)
    ap.add_argument("--pubkey", default=str(PUBKEY), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    snaps = Path(a.snapshots)
    pub_hex = json.loads(Path(a.pubkey).read_text(encoding="utf-8"))["public_key_hex"]
    end = date.fromisoformat(a.end) if a.end else max(
        date.fromisoformat(p.name) for p in snaps.iterdir() if p.is_dir() and p.name[:2] == "20")
    cur = window(end)
    prev = window(date.fromisoformat(cur[0]) - timedelta(days=1))
    base = window(date.fromisoformat(prev[0]) - timedelta(days=1))
    days = base + prev + cur

    docs = {d: verified(d, snaps, pub_hex) for d in days}
    lists = {docs[d]["manifest"].get("target_list_sha256") for d in days}
    hostsets = {tuple(r["host"] for r in docs[d]["observations"]) for d in days}
    if len(lists) != 1 or len(hostsets) != 1:
        sys.exit("  REFUSING: the population is not the same on every day read. Nothing written.")

    def methods(ds):
        return sorted({docs[d]["manifest"]["method_sha256"] for d in ds})

    def span(ds):
        return {"start": ds[0], "end": ds[-1], "days": len(ds)}

    issue = end.isoformat()[:7]
    fy, fm = map(int, FIRST_ISSUE.split("-"))
    sm_now = [docs[d]["manifest"].get("signed_manifests") or {} for d in cur]
    sm_then = [docs[d]["manifest"].get("signed_manifests") or {} for d in prev]
    m0 = docs[cur[-1]]["manifest"]
    F = {
        "schema": SCHEMA,
        "issue": issue,
        "issue_number": (end.year - fy) * 12 + end.month - fm + 1,
        "window": span(cur),
        "prior_window": span(prev),
        "baseline_for_prior_churn": span(base),
        "population": {
            "hosts": len(docs[cur[-1]]["observations"]),
            "source": m0.get("target_list_source"),
            "collected_on": (m0.get("target_list_collected_at_utc") or "")[:10],
            "target_list_sha256": next(iter(lists)),
            "vantage": sorted({docs[d]["manifest"]["vantage"]["class"] for d in cur + prev}),
        },
        "verification": {"days_verified": len(days), "public_key_hex": pub_hex,
                         "rule": "sha256 of observation.json equals the signed payload_sha256; the "
                                 "signing key equals index-pubkey.json; the Ed25519 signature verifies "
                                 "over those bytes; the file's date and row count match"},
        "classifier": {
            "window_method_sha256": methods(cur),
            "prior_window_method_sha256": methods(prev),
            "baseline_method_sha256": methods(base),
            "baseline_method_versions": len(methods(base)),
            "identical_across_window_and_prior": len(methods(cur + prev)) == 1,
        },
        "definitions": {
            "payment_gated": "verdict in " + ", ".join(GATED) + " on the day",
            "signable": "verdict OK: a stock @x402/evm 2.x buyer can construct a payment from the challenge",
            "blocked": "verdict BLOCKED: a v2 challenge a stock v2 client cannot sign",
            "v1_only": "verdict V1: a v1 challenge in the body, unreadable to a v2 client",
            "both_dialects": "verdict OK and v1 verdict V1_OK (x402-fetch 1.2.0 reads the body as well)",
            "stopped": "served a payment-gated verdict on at least one day of the prior window and on no "
                       "day of the window",
            "stopped_answered_without_challenge": "of those, NO_402 with an HTTP status other than 429 or "
                                                  "5xx on at least one day of the window",
            "stopped_no_usable_answer": "of those, every day of the window UNREACHABLE, 5xx or 429",
            "started": "payment-gated on at least one day of the window and on no day of the prior window",
            "price": "accepts[0].amount from an OK row's note, in atomic units of accepts[0].asset",
            "more_than_one_price": "signable on at least two days of the window with one asset, and more "
                                   "than one amount among those days",
            "median_price_base_usdc": "median accepts[0].amount over OK rows whose asset is "
                                      + rpc.USDC + f", divided by 10^{USDC_DECIMALS}",
            "signable_by_asset": "OK rows by accepts[0].asset: base_usdc " + rpc.USDC + ", base_sepolia_usdc "
                                 + rpc.USDC_BASE_SEPOLIA + ", case-insensitive",
            "manifest_answered_2xx": "signed_manifests.checked minus its unreachable and refused verdicts: a "
                                     "success status at /.well-known/x402, not a validated manifest",
            "manifest_carrying_a_signature": "signed_manifests.carrying_a_signature",
        },
        "state": {"window_end": day_state(docs[cur[-1]]), "prior_window_end": day_state(docs[prev[-1]])},
        "stopped_or_started": {"window": churn(docs, cur, prev), "prior_window": churn(docs, prev, base)},
        "price_changes": {"window": price_moves(docs, cur), "prior_window": price_moves(docs, prev)},
        "manifest_signatures": {
            "window_max": max(s.get("carrying_a_signature", 0) for s in sm_now),
            "prior_window_max": max(s.get("carrying_a_signature", 0) for s in sm_then),
            "window_days_status_ok": sum(1 for s in sm_now if s.get("status") == "ok"),
            "prior_window_days_status_ok": sum(1 for s in sm_then if s.get("status") == "ok"),
        },
        "rate_limit_status": 429,
        "inputs": [{"date": d, "payload_sha256": docs[d]["_payload_sha256"]} for d in days],
    }

    if issue >= "2026-12":
        # the survival study's cohort (survival.COHORT_DAY), read from its own signed file
        c0 = verified(COHORT_DAY, snaps, pub_hex)
        if c0["manifest"].get("target_list_sha256") not in lists:
            sys.exit("  REFUSING: the cohort day is a different population. Nothing written.")
        g0 = {r["host"] for r in c0["observations"] if r["verdict"] in GATED}
        g1 = {r["host"] for r in docs[cur[-1]]["observations"] if r["verdict"] in GATED}
        F["cohort"] = {"day": COHORT_DAY, "payload_sha256": c0["_payload_sha256"], "hosts": len(g0),
                       "still_gated": len(g0 & g1), "still_gated_pct": pct(len(g0 & g1), len(g0)),
                       "definition": "payment-gated on the cohort day and on the last day of the window"}

    now, then = F["state"]["window_end"], F["state"]["prior_window_end"]
    F["change_vs_prior_window_end"] = {
        k: now[k] - then[k] for k in ("answered", "payment_gated", "signable", "blocked", "v1_only",
                                      "both_dialects", "manifest_answered_2xx")}
    md = render(F)
    bad = unbacked_numbers(md, F)
    if bad:
        sys.exit(f"  REFUSING: the report text carries numbers the JSON does not: {bad}. Nothing written.")
    if "—" in md or "–" in md:
        sys.exit("  REFUSING: the report text carries a dash character. Nothing written.")

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"state_of_x402_{issue}.json").write_bytes(
        (json.dumps(F, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    (out / f"state_of_x402_{issue}.md").write_bytes(md.encode("utf-8"))
    print(f"  {len(days)} days verified, {days[0]} to {days[-1]}")
    print(f"  -> {out / f'state_of_x402_{issue}.md'}")
    print(f"  -> {out / f'state_of_x402_{issue}.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
