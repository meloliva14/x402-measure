"""Check a Verity Index snapshot without trusting whoever produced it.

A signature nobody can check is decoration. This is the whole verification path, it depends on
nothing in this repo except the published public key, and it is deliberately short enough to
read in one sitting.

    python verify_snapshot.py 2026-08-08
    python verify_snapshot.py --all

Exit code 0 if every checked snapshot verifies, 1 otherwise.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"


def check(day: Path) -> bool:
    obs, sigf = day / "observation.json", day / "signature.json"
    if not obs.exists() or not sigf.exists():
        print(f"  {day.name}  MISSING FILES")
        return False

    payload = obs.read_bytes()          # exact bytes on disk; never re-serialised
    meta = json.loads(sigf.read_text(encoding="utf-8"))

    digest = hashlib.sha256(payload).hexdigest()
    if digest != meta.get("payload_sha256"):
        print(f"  {day.name}  HASH MISMATCH — observation.json has changed since signing")
        return False

    # The key is pinned by the snapshot itself, then cross-checked against the published
    # pubkey. Checking only the embedded key would let a forger ship their own key alongside
    # their own signature and pass.
    pub_hex = meta["public_key_hex"]
    published = HERE / "index-pubkey.json"
    if published.exists():
        want = json.loads(published.read_text(encoding="utf-8"))["public_key_hex"]
        if pub_hex != want:
            print(f"  {day.name}  KEY MISMATCH — signed by a key that is not the published one")
            return False

    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)).verify(
            bytes.fromhex(meta["signature_hex"]), payload)
    except InvalidSignature:
        print(f"  {day.name}  BAD SIGNATURE")
        return False

    doc = json.loads(payload)
    m = doc.get("manifest", {})
    n = len(doc.get("observations", []))
    if m.get("hosts_observed") != n:
        print(f"  {day.name}  COUNT MISMATCH — manifest says {m.get('hosts_observed')}, "
              f"file carries {n}")
        return False

    print(f"  {day.name}  OK   {n} hosts, {len(payload):,} bytes, {meta['key_id']}")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)

    if a.all or not a.date:
        days = sorted(d for d in SNAPSHOTS.glob("*") if d.is_dir()) if SNAPSHOTS.exists() else []
        if not days:
            print("  no snapshots found")
            return 1
    else:
        days = [SNAPSHOTS / a.date]

    ok = all([check(d) for d in days])
    print(f"\n  {len(days)} snapshot(s) checked — {'ALL VERIFIED' if ok else 'FAILURES ABOVE'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
