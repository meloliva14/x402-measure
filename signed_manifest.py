"""Does a host's signed manifest verify, and over which bytes?

Martin stood up the first live instance of the detached-signature hook on #wg-domain-discovery
(x402.magentix.ai) and asked for independent verdicts. Walter ran the second implementation. This
is the third.

THIS IS NOT PART OF THE DAILY JOB, AND NOTHING FROM IT IS A DAILY SERIES. An earlier version of
this docstring claimed it was "wired into the daily sweep", and the 2026-08-12 commit message said
"in the sweep". Both were false: neither snapshot.py nor .github/workflows/snapshot.yml calls this
script, and before 2026-08-15 it had been run exactly once, against one host named on the command
line. The only date anyone may quote from it is `checked_utc` inside signed_manifests.json.

Wiring it into the cron is not a one-line change, so do not attempt it in passing. The workflow's
commit step stages only snapshots/ and digests.txt, so a modified signed_manifests.json would sit
unstaged and make `git pull --rebase` fail on every run afterwards. The right fix is to write the
result into snapshots/<date>/ so it is signed and append-only like the rest of the archive, which
is a change to the observation schema and needs to be proven with a real run first.

LAST FULL SWEEP 2026-08-15: of the 972 census hosts that serve a discovery manifest, ZERO serve a
signed one (898 unsigned, 74 unreachable from a residential vantage). x402.magentix.ai verifies
`authentic` but is NOT in the 1,521-host target list, so it is not in that denominator and must
never be counted as though it were. Adoption inside the measured network is zero.

THE VERDICT THAT IS NOT ALLOWED TO BE WRONG. Publishing "signature-invalid" about a named host is
an accusation. It says either the operator is serving something that does not match what they
signed, or somebody tampered with it in transit. If the true cause was that MY canonicalisation
disagreed with THEIRS, that accusation is false and it is aimed at a real company.

So this never reports invalid on a failed verify alone. It first asks whether our canonical bytes
even agree with the publisher's own published content_digest:

  authentic              signature verifies over our RFC 8785 canonical bytes
  authentic-over-served  verifies over the served bytes instead (a different, weaker profile:
                         any CDN re-serialisation would break it, worth reporting as its own thing)
  signature-invalid      does NOT verify, AND our canonical sha256 MATCHES the published
                         content_digest. Only then do we know our canonicalisation agreed and the
                         failure is really theirs.
  canon-mismatch         does NOT verify, and our digest disagrees with theirs. That is OUR
                         disagreement to resolve, not their defect. Undetermined, never invalid.
  unsigned               manifest served, no .sig alongside it
  no-key                 .sig names a kid we cannot resolve in DNS
  unreachable            could not fetch

WHY THE SERVED-BYTE DIGESTS ARE RECORDED. Walter anchored the repo-published pair because a WAF
ban on his address stops him fetching the live host. Recording sha256 over the exact served bytes
lets anyone compare an anchor built from a repo copy against what the host actually returns.

WHAT THIS DOES NOT DO. Our JCS is an implementation, not the reference. `canon-mismatch` exists
precisely because a disagreement is more likely to be ours than theirs.

    python signed_manifest.py                      # every host with a manifest
    python signed_manifest.py x402.magentix.ai     # one host
"""
import base64
import hashlib
import json
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

HERE = Path(__file__).parent
OUT = HERE / "signed_manifests.json"
TIMEOUT = 15
WORKERS = 10
UA = {"user-agent": "verity-measure/1.0 (+https://veritylayer.dev)"}

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                timeout=TIMEOUT, context=_CTX) as r:
        return r.read(2_000_000)


def jcs(o) -> str:
    """RFC 8785 canonicalisation.

    Keys sort by UTF-16 code unit, which is NOT the same as Python's default string order once
    you leave the BMP. Encoding to utf-16-be before comparing gets that right.
    """
    if isinstance(o, dict):
        items = sorted(o.items(), key=lambda kv: kv[0].encode("utf-16-be"))
        return "{" + ",".join(f"{jcs(k)}:{jcs(v)}" for k, v in items) + "}"
    if isinstance(o, list):
        return "[" + ",".join(jcs(x) for x in o) + "]"
    if isinstance(o, bool):
        return "true" if o else "false"
    if o is None:
        return "null"
    if isinstance(o, str):
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, int):
        return str(o)
    if isinstance(o, float):
        # RFC 8785 defers to ECMAScript Number::toString. Integral floats lose the ".0".
        return str(int(o)) if o == int(o) else repr(o)
    raise TypeError(f"not JSON: {type(o)}")


def dns_key(kid: str) -> bytes | None:
    """Resolve the verifying key from DNS, out of band from the document that names it.

    Taking it from the .sig would make the signature self-certifying and prove nothing.
    """
    try:
        d = json.loads(_get(f"https://dns.google/resolve?name={kid}&type=TXT"))
    except Exception:  # noqa: BLE001
        return None
    for a in d.get("Answer", []):
        if a.get("type") != 16:
            continue
        rec = dict(p.strip().split("=", 1) for p in a["data"].strip('"').split(";") if "=" in p)
        k = rec.get("k")
        if k:
            try:
                return base64.urlsafe_b64decode(k + "=" * (-len(k) % 4))
            except Exception:  # noqa: BLE001
                return None
    return None


def _verify(pub: bytes, sig: bytes, msg: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, msg)
        return True
    except (InvalidSignature, ValueError):
        return False


def check(host: str) -> dict:
    base = f"https://{host}/.well-known"
    out = {"host": host}
    try:
        man = _get(f"{base}/x402")
    except Exception as e:  # noqa: BLE001
        return {**out, "verdict": "unreachable", "note": type(e).__name__}
    out["manifest_bytes"] = len(man)
    out["manifest_sha256"] = hashlib.sha256(man).hexdigest()

    try:
        sraw = _get(f"{base}/x402.sig")
    except urllib.error.HTTPError as e:
        return {**out, "verdict": "unsigned", "note": f"HTTP {e.code} on .sig"}
    except Exception as e:  # noqa: BLE001
        return {**out, "verdict": "unsigned", "note": type(e).__name__}
    out["sig_bytes"] = len(sraw)
    out["sig_sha256"] = hashlib.sha256(sraw).hexdigest()

    try:
        sig = json.loads(sraw)
        doc = json.loads(man)
    except Exception:  # noqa: BLE001
        return {**out, "verdict": "unsigned", "note": ".sig path served non-JSON"}

    # A 200 at the .sig path does NOT mean the host published a signature. Several servers route
    # every /.well-known/x402* path to one handler: tools.bip-rep.com returns its 21KB manifest
    # there, and agent-card-validator-mcp.mtree.workers.dev returns a validator response. Calling
    # those "signed but the key will not resolve" invents an attempt the operator never made.
    # A signature document has to carry a signature.
    if not isinstance(sig, dict) or not sig.get("sig") or not sig.get("kid"):
        return {**out, "verdict": "unsigned",
                "note": (".sig path returns 200 but the body is not a signature document "
                         f"(top-level keys: {list(sig)[:6] if isinstance(sig, dict) else type(sig).__name__}); "
                         "looks like catch-all routing rather than a published signature")}

    out["kid"] = sig.get("kid")
    out["sig_input"] = sig.get("sig_input")
    out["canon"] = sig.get("canon")
    out["declared_version"] = sig.get("schema") or sig.get("version")   # absent today; see thread

    pub = dns_key(sig.get("kid", ""))
    if pub is None or len(pub) != 32:
        return {**out, "verdict": "no-key", "note": f"no Ed25519 key at {sig.get('kid')!r}"}

    raw = sig.get("sig") or ""
    try:
        sigbytes = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception:  # noqa: BLE001
        return {**out, "verdict": "canon-mismatch", "note": "signature is not base64url"}

    canon = jcs(doc).encode("utf-8")
    out["canonical_bytes"] = len(canon)
    out["canonical_sha256"] = hashlib.sha256(canon).hexdigest()

    published = ((sig.get("content_digest") or {}).get("value")
                 if isinstance(sig.get("content_digest"), dict) else sig.get("content_digest"))
    out["publisher_content_digest"] = published
    out["our_canon_agrees_with_publisher"] = (published == out["canonical_sha256"]
                                              if published else None)

    if _verify(pub, sigbytes, canon):
        out["verdict"] = "authentic"
    elif _verify(pub, sigbytes, man):
        out["verdict"] = "authentic-over-served"
    elif published and published == out["canonical_sha256"]:
        # Our canonicalisation provably matched theirs, so the failure is not ours to own.
        out["verdict"] = "signature-invalid"
    else:
        out["verdict"] = "canon-mismatch"
        out["note"] = ("did not verify, and our canonical digest does not match the publisher's "
                       "content_digest, so this is a canonicalisation disagreement rather than a "
                       "finding about the host")
    return out


def main(argv: list[str]) -> int:
    if argv:
        hosts = argv
    else:
        src = HERE / "manifests.json"
        if not src.exists():
            sys.exit("  manifests.json absent; run manifests.py first")
        d = json.loads(src.read_text(encoding="utf-8"))
        hosts = [r["host"] for r in d["results"] if r.get("served")]

    print(f"  checking {len(hosts)} host(s) for a signed manifest\n")
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(check, hosts))

    from collections import Counter
    c = Counter(r["verdict"] for r in res)
    for k, v in c.most_common():
        print(f"    {k:<24} {v}")

    signed = [r for r in res if r["verdict"] in
              ("authentic", "authentic-over-served", "signature-invalid", "canon-mismatch")]
    if signed:
        print("\n  hosts carrying a .sig:")
        for r in signed:
            print(f"    {r['host']:<34} {r['verdict']}")
            print(f"      manifest {r.get('manifest_bytes')}b sha256:{r.get('manifest_sha256','')[:16]}…"
                  f"  sig {r.get('sig_bytes')}b sha256:{r.get('sig_sha256','')[:16]}…")
            if r.get("our_canon_agrees_with_publisher") is not None:
                print(f"      our canonicalisation agrees with publisher's digest: "
                      f"{r['our_canon_agrees_with_publisher']}")

    OUT.write_bytes((json.dumps(
        {"checked_utc": datetime.now(timezone.utc).isoformat(),
         "counts": dict(c), "results": res}, indent=1) + "\n").encode("utf-8"))
    print(f"\n  wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
