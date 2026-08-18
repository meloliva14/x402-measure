"""Bind a Coston2 anchoring address to the archive key, signed.

WHY THIS EXISTS. wdhawkins46's notary endpoint sets the anchor's `for=` field to the PAYER's
address taken from the payment authorization, not to a free-form subject. So once the daily job
anchors its own day-digests, the on-chain record reads `for=<some 0x wallet>` and a third party has
no way to tell that wallet is this archive's. His words: "One signed line in your repo binding that
address to your key closes the gap."

This is that line. It is signed by the SAME Ed25519 key that signs every observation
(index-pubkey.json), so anyone who can already verify a snapshot can verify this with no new trust
and no new key to distribute.

WHAT IT DELIBERATELY IS NOT. It is not a proof that this archive controls the wallet's private key.
It is a statement, signed by the archive key, that the archive INTENDS anchors from that address to
be read as its own. Proving control of the wallet would need a signature from the wallet itself,
which is a different artifact and needs the wallet's key. Do not let this be described as the
stronger thing. If the stronger claim is ever needed, sign the same text with the wallet and
publish both halves.

    python bind_anchor_address.py 0xYourCoston2Address
"""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HERE = Path(__file__).parent
KEYFILE = HERE / ".index_key"                 # gitignored seed, same one snapshot.py uses
PUBKEY = HERE / "index-pubkey.json"
OUT = HERE / "anchor-address.json"

CHAIN = {"name": "Flare Testnet Coston2", "caip2": "eip155:114", "chain_id": 114}


def load_key() -> tuple[Ed25519PrivateKey, str, str]:
    seed = (os.getenv("VERITY_INDEX_KEY") or "").strip()
    if not seed and KEYFILE.exists():
        seed = KEYFILE.read_text(encoding="utf-8").strip()
    if not seed:
        sys.exit("  no archive key. Set VERITY_INDEX_KEY or run snapshot.py once locally.")
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed))
    pub_hex = priv.public_key().public_bytes(
        encoding=__import__("cryptography.hazmat.primitives.serialization",
                            fromlist=["Encoding"]).Encoding.Raw,
        format=__import__("cryptography.hazmat.primitives.serialization",
                          fromlist=["PublicFormat"]).PublicFormat.Raw).hex()
    key_id = "ed25519:" + hashlib.sha256(bytes.fromhex(pub_hex)).hexdigest()[:16]
    return priv, pub_hex, key_id


def canonical(o) -> bytes:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def main(argv):
    if len(argv) != 1:
        print(__doc__)
        return 1
    addr = argv[0].strip()
    if not (addr.startswith("0x") and len(addr) == 42):
        sys.exit(f"  {addr!r} is not a 20-byte 0x address. Refusing to sign a malformed binding.")

    priv, pub_hex, key_id = load_key()
    if PUBKEY.exists():
        want = json.loads(PUBKEY.read_text(encoding="utf-8"))["public_key_hex"]
        if want != pub_hex:
            sys.exit("  the loaded key is NOT the published archive key. Refusing: a binding signed "
                     "by the wrong key would be worse than none.")

    stmt = {
        "schema": "verity-index-anchor-binding/1",
        "statement": ("Anchors on this chain sent from this address are published by this archive. "
                      "This is a statement of intent signed by the archive key, NOT a proof of "
                      "control of the address; that would require a signature from the address."),
        "address": addr.lower(),
        "chain": CHAIN,
        "archive_key_id": key_id,
        "archive_public_key_hex": pub_hex,
        "archive": "https://github.com/meloliva14/x402-measure",
        "bound_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    payload = canonical(stmt)
    doc = {
        **stmt,
        "signature_hex": priv.sign(payload).hex(),
        "signed_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "verify": ("Recompute canonical JSON over every field except signature_hex, "
                   "signed_payload_sha256 and verify, then check the Ed25519 signature against "
                   "archive_public_key_hex, and confirm that key matches index-pubkey.json."),
    }
    # write_bytes, never write_text: on Windows write_text turns \n into \r\n and this file is
    # fetched and digested by third parties. Same trap that put a CRLF hash in digests.txt.
    OUT.write_bytes((json.dumps(doc, indent=1) + "\n").encode("utf-8"))
    print(f"  wrote {OUT.name}")
    print(f"    address : {addr.lower()}")
    print(f"    chain   : {CHAIN['name']} ({CHAIN['caip2']})")
    print(f"    signed  : {key_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
