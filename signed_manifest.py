"""Does a host's signed manifest verify, and over which bytes?

Martin stood up the first live instance of the detached-signature hook on #wg-domain-discovery
(x402.magentix.ai) and asked for independent verdicts. Walter ran the second implementation. This
is the third.

THIS IS PART OF THE DAILY JOB AS OF 2026-08-16. snapshot.py calls check() across the pinned
population and writes the result into snapshots/<date>/observation.json under
manifest.signed_manifests, so it is signed and append-only like the rest of the archive.

The old warning is kept here because it is the whole reason not to trust a docstring. Before
2026-08-15 this file claimed to be "wired into the daily sweep" and the 2026-08-12 commit message
said "in the sweep". Both were false when written: nothing called this script, and it had been run
exactly once, against one host named on the command line. The wiring that paragraph described as
the right fix is the wiring that now exists. A file describing itself is evidence and not proof, so
the dates anyone may quote are the ones inside snapshots/<date>/observation.json.

ADOPTION AS OF 2026-08-18, from the daily record: of the 972 census hosts that serve a discovery
manifest, ZERO serve a signed one, on every day the census has run (08-16: 894 unsigned and 78
unreachable, 08-17: 897 and 75, 08-18: 899 and 73). x402.magentix.ai verifies
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
  unreachable            could not fetch. A fact about the host or the network.
  refused                this prober declined to fetch, on its own policy. A fact about MY
                         configuration and never about the operator, so it is never merged
                         into any of the above.

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

# --- SSRF fence -----------------------------------------------------------------------------
#
# WHY THIS EXISTS. Until 2026-08-18 this script fetched 972 third-party hosts three times a day
# from a CI runner through a bare urlopen, which follows redirects wherever they point. preflight.py
# was fenced on 2026-08-17 and this one was not: same repo, same population, same runner, and the
# runner has a cloud metadata endpoint on it. Any host in the census could have steered it.
#
# The address-space policy is imported rather than restated so that exactly one definition of
# "non-public" exists across both probers. The private names are imported deliberately: renaming
# them in preflight.py would change its method_sha256, which is stamped into every observation, and
# a cosmetic rename would read as a method change in a series whose value is that it has none.
from preflight import BlockedDestination, _check_url as _fence_url


class _FencedRedirect(urllib.request.HTTPRedirectHandler):
    """Validate every hop. A redirect chain is only as safe as its least-checked link."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _fence_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(
    _FencedRedirect, urllib.request.HTTPSHandler(context=_CTX))


def _get(url: str) -> bytes:
    _fence_url(url)                      # the first hop is a destination too
    with _OPENER.open(urllib.request.Request(url, headers=UA), timeout=TIMEOUT) as r:
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
    except BlockedDestination as e:
        return {**out, "verdict": "refused", "note": f"refused by prober policy: {e}"}
    except Exception as e:  # noqa: BLE001
        return {**out, "verdict": "unreachable", "note": type(e).__name__}
    out["manifest_bytes"] = len(man)
    out["manifest_sha256"] = hashlib.sha256(man).hexdigest()

    try:
        sraw = _get(f"{base}/x402.sig")
    except BlockedDestination as e:
        # MUST precede the handlers below. Without it a refusal falls through into `unsigned`,
        # which is a false statement about a named operator: it reports that they publish no
        # signature when the truth is that I declined to look. The manifest fetch already cleared
        # the fence and _PUBLIC_OK caches only successes, so arriving here means the name resolved
        # differently between two requests, which is the DNS-rebinding shape itself.
        return {**out, "verdict": "refused", "note": f"refused by prober policy: {e}"}
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
