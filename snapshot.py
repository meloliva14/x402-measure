"""Day N of a dated, signed, public record of what payment-gated endpoints actually served.

WHY THIS FILE EXISTS. Every other artifact in this repo is a MEASUREMENT — run it today, get
today's answer, overwrite yesterday's. sweep_results.json is even in .gitignore, so every run has
been destroying the only asset here whose input is wall-clock time. A competitor starting in
October can reproduce every script in this repo in a weekend. They can never have August.

WHAT THIS IS NOT. Not a score, not a grade, not a ranking, and it never uses a word like "risk"
or "fraud" or "trust". It records what an endpoint served at a moment, with the method attached,
and stops. Any judgement is the reader's, made with their own policy. That restraint is a design
constraint and not a stylistic one: a wrong public judgement about a named company is the one
mistake that would cost the credibility this whole thing rests on.

RAIL-AGNOSTIC ON PURPOSE. `rail` is a field from the first file rather than an assumption baked
into the schema, because "who am I about to pay" is not an x402 question. x402 is instance one
because that is where the ground truth already exists.

WHAT IS SIGNED. The exact bytes of observation.json, by a key that exists ONLY for this archive.
Deliberately NOT the receipt key: receipts.verify_receipt() rejects anything not signed by the
server's current key, so signing an immutable archive with a rotatable production key would mean
one rotation silently invalidates every historical snapshot. Different lifetime, different key.

    python snapshot.py            # today, UTC
    python snapshot.py --date 2026-08-08
"""
import argparse
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import preflight

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"
KEYFILE = HERE / ".index_key"                 # gitignored; the private seed
PUBKEY = HERE / "index-pubkey.json"           # committed; how a stranger verifies

SCHEMA = "verity-index-observation/1"
RAIL = "x402"
WORKERS = 14

# A run that only reached a fraction of its targets is not a smaller sweep, it is a different
# and unstated population. Publishing one as if it were the series would silently corrupt every
# comparison made against it later. Abort instead.
MIN_ANSWER_RATE = 0.80


# --- key handling ----------------------------------------------------------------------

def load_or_create_key() -> tuple[Ed25519PrivateKey, str, str]:
    """The archive key. Seed from env if present (that is how the cron will supply it),
    otherwise a local file, otherwise generated once and written down."""
    seed_hex = (os.getenv("VERITY_INDEX_KEY") or "").strip()
    if not seed_hex and KEYFILE.exists():
        seed_hex = KEYFILE.read_text(encoding="utf-8").strip()
    if seed_hex:
        priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))
        created = "(existing)"
    else:
        priv = Ed25519PrivateKey.generate()
        seed_hex = priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()).hex()
        KEYFILE.write_text(seed_hex, encoding="utf-8")
        created = datetime.now(timezone.utc).date().isoformat()
        print(f"  generated a new archive key -> {KEYFILE.name} (gitignored)")

    pub_hex = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw).hex()
    key_id = "ed25519:" + hashlib.sha256(bytes.fromhex(pub_hex)).hexdigest()[:16]

    if not PUBKEY.exists():
        PUBKEY.write_text(json.dumps({
            "key_id": key_id,
            "algorithm": "Ed25519",
            "public_key_hex": pub_hex,
            "created": created,
            "purpose": ("Signs Verity Index observation files only. This is NOT the VerityLayer "
                        "receipt key at /.well-known/verity-pubkey.json — that one signs verdicts "
                        "and is rotatable; this one signs an immutable archive and is not."),
        }, indent=1) + "\n", encoding="utf-8")
        print(f"  wrote {PUBKEY.name}")
    return priv, pub_hex, key_id


# --- observation -----------------------------------------------------------------------

def targets() -> tuple[list[dict], dict]:
    """The pinned population, from the committed targets.json.

    Deliberately NOT re-derived from sweep_results.json on each run. That file is gitignored, so
    a scheduled runner would not have it — but the deeper reason is that a target list which moves
    every run makes day-over-day comparison meaningless: the series would be measuring a shifting
    set of hosts rather than a change in their behaviour. Adding or removing targets is a commit.
    """
    src = HERE / "targets.json"
    if src.exists():
        doc = json.loads(src.read_text(encoding="utf-8"))
        return doc.get("targets", []), doc

    legacy = HERE / "sweep_results.json"   # pre-targets.json fallback, local runs only
    if not legacy.exists():
        sys.exit("  targets.json is absent and there is no sweep_results.json to fall back to")
    rows = json.loads(legacy.read_text(encoding="utf-8"))
    out, seen = [], set()
    for r in rows:
        h, u = r.get("host"), r.get("url")
        if not h or not u or h in seen:
            continue
        seen.add(h)
        out.append({"host": h, "url": u})
    return out, {"source": "sweep_results.json (fallback)"}


def observe(t: dict) -> dict:
    try:
        verdict, notes, _challenge = preflight.classify(t["url"])
    except Exception as e:  # noqa: BLE001
        return {"host": t["host"], "url": t["url"], "verdict": "UNREACHABLE",
                "notes": [f"{type(e).__name__} during classify"]}
    return {"host": t["host"], "url": t["url"], "verdict": verdict, "notes": list(notes)}


def build(date: str) -> dict:
    tg, tmeta = targets()
    print(f"  probing {len(tg)} hosts (one unauthenticated request each, nothing paid)\n")
    started = datetime.now(timezone.utc)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        rows = list(ex.map(observe, tg))
    ended = datetime.now(timezone.utc)

    counts = Counter(r["verdict"] for r in rows)
    answered = sum(v for k, v in counts.items() if k != "UNREACHABLE")
    rate = answered / max(len(rows), 1)
    print(f"  answered {answered}/{len(rows)} ({rate*100:.1f}%) in {time.time()-t0:.0f}s")
    for k, v in counts.most_common():
        print(f"    {k:<16} {v:>5}")
    if rate < MIN_ANSWER_RATE:
        sys.exit(f"\n  ABORT: only {rate*100:.1f}% answered, floor is {MIN_ANSWER_RATE*100:.0f}%. "
                 "A partial run is a different population, not a smaller one. Nothing written.")

    harvest = json.loads((HERE / "harvest_meta.json").read_text(encoding="utf-8")) \
        if (HERE / "harvest_meta.json").exists() else {}

    return {
        "schema": SCHEMA,
        "rail": RAIL,
        "date": date,
        "manifest": {
            "hosts_observed": len(rows),
            "answered": answered,
            "answer_rate": round(rate, 4),
            "verdicts": dict(counts.most_common()),
            "sweep_started_utc": started.isoformat(),
            "sweep_ended_utc": ended.isoformat(),
            "method": ("preflight.classify(url) — one unauthenticated request per host, GET with a "
                       "POST fallback. Nothing signed, nothing paid. A verdict describes what the "
                       "endpoint served at that moment and nothing about the operator."),
            "method_sha256": hashlib.sha256(
                (HERE / "preflight.py").read_bytes()).hexdigest(),
            "snapshot_script_sha256": hashlib.sha256(
                Path(__file__).read_bytes()).hexdigest(),
            "target_list_source": tmeta.get("source", "targets.json"),
            "target_list_count": tmeta.get("count", len(tg)),
            "target_list_sha256": hashlib.sha256(
                (HERE / "targets.json").read_bytes()).hexdigest()
            if (HERE / "targets.json").exists() else None,
            "target_list_collected_at_utc": (tmeta.get("collected_at_utc")
                                             or harvest.get("collected_at_utc")),
            "target_list_caveat": tmeta.get("source_caveat") or harvest.get("caveat"),
            "known_limits": [
                "One probe per host. A host that is briefly down reads as UNREACHABLE, which is "
                "why UNREACHABLE is recorded and never treated as a state change.",
                "Verdicts are point-in-time. Comparing two dates measures the pair of "
                "observations, not an operator's intent.",
                "The target list is itself a snapshot of a live registry and shifts between runs.",
            ],
        },
        "observations": sorted(rows, key=lambda r: r["host"]),
    }


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat())
    ap.add_argument("--skip-if-exists", action="store_true",
                    help="exit 0 instead of erroring when the date is already recorded. For the "
                         "scheduler, which fires several times a day on purpose so that one "
                         "delayed or dropped run cannot put a hole in the series.")
    a = ap.parse_args(argv)

    out = SNAPSHOTS / a.date
    if (out / "observation.json").exists():
        if a.skip_if_exists:
            print(f"  {a.date} already recorded — nothing to do.")
            return 0
        sys.exit(f"  {a.date} already exists. The archive is append-only; refusing to overwrite.")

    priv, pub_hex, key_id = load_or_create_key()

    doc = build(a.date)
    payload = canonical(doc)
    sig = priv.sign(payload).hex()

    out.mkdir(parents=True, exist_ok=True)
    (out / "observation.json").write_bytes(payload)
    (out / "signature.json").write_text(json.dumps({
        "schema": "verity-index-signature/1",
        "signs": "observation.json",
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload_bytes": len(payload),
        "algorithm": "Ed25519",
        "key_id": key_id,
        "public_key_hex": pub_hex,
        "signature_hex": sig,
        "signed_at_utc": datetime.now(timezone.utc).isoformat(),
        "verify": "python verify_snapshot.py " + a.date,
    }, indent=1) + "\n", encoding="utf-8")

    print(f"\n  wrote snapshots/{a.date}/observation.json  ({len(payload):,} bytes)")
    print(f"  signed with {key_id}")
    print(f"  verify: python verify_snapshot.py {a.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
