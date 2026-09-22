#!/usr/bin/env python3
"""Run Paddock's verify_before_pay over sample.csv and write parity.jsonl.

WHO PADDOCK IS, in their own words (Mancy, 2026-09-22): "Paddock (paddock.finance) — pre-payment
verification for AI agents. One call checks an x402 endpoint's wallet, chain, token and price
against what actually settled, before the agent pays." API documentation is at
https://paddock.finance/docs and the shorter page at https://paddock.finance/verify.

VERSION. This sample ran under verify_before_pay/0.11. Every response carries schema_version, and
the field-name fix below landed in 0.12.

WHOSE SETTLEMENT COUNT IS WHICH. Paddock's settlement counts are a nightly approximation. Checked
against the full-window chain scan in parity_scan.py they ran over by 19% on one of these wallets
and short by roughly 90% on the facilitator-heavy ones (Paddock, 2026-09-22, who asked that this
be said plainly). The scan is the more accurate count; their strength is the pre-payment check.

THE TWO FIELDS THAT MOVED. Paddock's loop reads .checks.settlement_recency and
.checks.circular_signal. Neither exists in verify_before_pay/0.11: the response carries
checks.settlement and checks.circular instead, and no key anywhere in it contains "recency" or
"signal". Run as written, every row's last two fields would be null. This fills their field names
from the blocks that actually hold the data and records schema_version on every line so the
mapping is checkable rather than asserted:

    settlement_recency <- checks.settlement  (status, last_observed_settlement_date,
                          days_since_last_observed, observed_settlements_7d/30d, days_present_*)
    circular_signal    <- checks.circular    (status, in_coverage, operator_funded_pct, cluster)

Confirmed by Paddock on 2026-09-22: the loop and their own documentation carried the same wrong
keys, and both are fixed in 0.12. The mapping above is kept because this file ran against 0.11.

THE KEY. Read from a file outside this repo, passed with --key-file, or the PADDOCK_KEY
environment variable. It is never written to the output, printed, or committed.

Usage: python paddock_parity.py --key-file <path>   (reads sample.csv, writes parity.jsonl)
"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://paddock.finance/api/mcp/verify-before-pay"
REC = ("status", "last_observed_settlement_date", "days_since_last_observed",
       "observed_settlements_7d", "observed_settlements_30d",
       "days_present_7d", "days_present_30d", "snapshot_days_scanned", "as_of")
CIRC = ("status", "in_coverage", "operator_funded_pct", "cluster",
        "methodology_version", "detection_date", "as_of")


def arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def pick(obj, keys):
    if not isinstance(obj, dict):
        return None
    return {k: obj.get(k) for k in keys}


def main() -> int:
    kf = arg("--key-file")
    key = open(kf, encoding="utf-8").read().strip() if kf else os.environ.get("PADDOCK_KEY", "")
    if not key:
        raise SystemExit("no key: pass --key-file or set PADDOCK_KEY")
    rows = list(csv.DictReader(open("sample.csv", encoding="utf-8")))
    out = open("parity.jsonl", "w", encoding="utf-8", newline="\n")
    ok = err = 0
    for r in rows:
        q = urllib.parse.urlencode({"pay_to": r["pay_to"], "expect_network": r["chain"]})
        req = urllib.request.Request(f"{API}?{q}", headers={
            "X-Paddock-Key": key, "User-Agent": "x402-measure", "Accept": "application/json"})
        line = {"pay_to": r["pay_to"],
                "your_distinct_payers": int(r["distinct_payers"]),
                "your_settlements": int(r["settlements"])}
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                d = json.loads(resp.read())
            checks = d.get("checks") or {}
            line.update({"route": d.get("route"), "reason_codes": d.get("reason_codes"),
                         "settlement_recency": pick(checks.get("settlement"), REC),
                         "circular_signal": pick(checks.get("circular"), CIRC),
                         "checked_at": d.get("checked_at"),
                         "schema_version": d.get("schema_version")})
            ok += 1
        except urllib.error.HTTPError as e:
            line["error"] = f"HTTP {e.code}"
            err += 1
        except Exception as e:  # noqa: BLE001
            line["error"] = type(e).__name__
            err += 1
        out.write(json.dumps(line) + "\n")
        print(f"  {r['pay_to'][:12]}... {line.get('route') or line.get('error')}", flush=True)
        time.sleep(0.4)
    out.close()
    print(f"\n  {ok} answered, {err} failed -> parity.jsonl")
    return 0 if err == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
