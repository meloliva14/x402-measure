"""What would PR #2979 cost the network that already exists?

Validates every deployed host against the normative rules in the proposed `discovery` extension
(x402-foundation/x402#2979, also draft-hawkins-x402-dns-discovery), and reports the migration
cost in hosts rather than in opinions.

WHY THIS AND NOT manifests.py. manifests.py asks a product question: can a buyer construct a
payment from what this host publishes? This asks a spec question: would this host satisfy the
proposed rules as written? They disagree in both directions, which is the point. A host can be
perfectly payable and fail the spec (no `kind`, no `x402Version`), and a host can satisfy every
MUST and still publish nothing a buyer can pay from (`resources` is MAY).

WHAT IT CHECKS, taken from the PR text rather than from memory of it:

  manifest MUST be HTTPS
  x402Version                MUST
  kind                       MUST, one of facilitator | resource-server | both
  facilitator                MUST if kind includes facilitator
  facilitator.baseUrl        MUST, and MUST be same-domain or a subdomain of the manifest host
  facilitator.endpoints      MUST
  facilitator.kinds          MUST
  facilitator.assets         SHOULD
  updated                    SHOULD
  name / description         SHOULD
  DNS _x402.<domain> TXT     optional pointer; v= and wk= MUST, at most ONE v=x402-1 record,
                             wk MUST be in-domain

HOW TO READ THE OUTPUT. A "violation" here is a gap against a spec that is still in review and
that nobody has adopted yet. It is NOT a defect report and must never be sent to anyone as one.
The only honest use of this number is the one Mel offered in the thread: telling the working
group what its own proposal would cost the hosts that already exist.

DNS is queried over DNS-over-HTTPS so this stays dependency-free and works the same everywhere.
Read-only, keyless, free.

USAGE
    python spec_conformance.py            # every host in sweep_results.json
    python spec_conformance.py 150        # a sample, for a quick look
"""
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
SWEEP = HERE / "sweep_results.json"
OUT = HERE / "spec_conformance.json"

TIMEOUT = 12
WORKERS = 12
UA = {"user-agent": "verity-measure/1.0 (+https://veritylayer.dev)"}
_PATHS = ("/.well-known/x402", "/.well-known/x402.json")
_KINDS = {"facilitator", "resource-server", "both"}
_DOH = "https://dns.google/resolve"

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
        return json.loads(r.read(400_000)), r.status


def _registrable(host):
    """Crude eTLD+1. Good enough for the same-domain rule and honest about being crude."""
    parts = (host or "").lower().strip(".").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _in_domain(url, manifest_host):
    """The spec's constraint: same domain, or a subdomain of it."""
    try:
        h = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    if not h:
        return False
    return h == manifest_host.lower() or h.endswith("." + _registrable(manifest_host))


def fetch_manifest(host):
    for path in _PATHS:
        try:
            man, _ = _get_json(f"https://{host}{path}")
            return man, path, None
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
    return None, None, err


def dns_pointer(host):
    """The optional _x402 TXT pointer, over DNS-over-HTTPS so this needs no resolver library.

    Returns (records, error). A domain publishing more than one v=x402-1 record MUST be treated
    as unresolvable per the spec, so the count is kept rather than collapsed.
    """
    name = "_x402." + _registrable(host)
    try:
        d, _ = _get_json(f"{_DOH}?name={urllib.parse.quote(name)}&type=TXT",
                         headers={"accept": "application/dns-json"})
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__
    answers = [a.get("data", "").strip('"') for a in (d.get("Answer") or [])]
    return [a for a in answers if "v=x402-1" in a], None


def check(host):
    out = {"host": host, "manifest": False, "violations": [], "warnings": []}
    man, path, err = fetch_manifest(host)

    txt, txt_err = dns_pointer(host)
    out["dns_records"] = None if txt is None else len(txt)
    if txt:
        # "A domain MUST publish at most one v=x402-1 record."
        if len(txt) > 1:
            out["violations"].append("MUST: more than one v=x402-1 TXT record")
        for rec in txt:
            kv = dict(p.split("=", 1) for p in
                      (x.strip() for x in rec.split(";")) if "=" in p)
            if "wk" not in kv:
                out["violations"].append("MUST: TXT record has no wk=")
            elif not _in_domain(kv["wk"], host):
                out["violations"].append("MUST: TXT wk= points out of domain")

    if man is None:
        out["error"] = err
        return out
    out["manifest"] = True
    out["path"] = path
    if not isinstance(man, dict):
        out["violations"].append("MUST: manifest is not a JSON object")
        return out

    # --- manifest MUSTs -------------------------------------------------------------------
    if "x402Version" not in man:
        out["violations"].append("MUST: no x402Version")
    elif not isinstance(man["x402Version"], int):
        out["violations"].append("MUST: x402Version is not typed (got "
                                 f"{type(man['x402Version']).__name__})")

    kind = man.get("kind")
    if kind is None:
        out["violations"].append("MUST: no kind")
    elif kind not in _KINDS:
        out["violations"].append(f"MUST: kind is {kind!r}, not one of {sorted(_KINDS)}")

    if kind in ("facilitator", "both"):
        fac = man.get("facilitator")
        if not isinstance(fac, dict):
            out["violations"].append("MUST: kind includes facilitator but no facilitator block")
        else:
            base = fac.get("baseUrl")
            if not base:
                out["violations"].append("MUST: facilitator.baseUrl missing")
            else:
                if not str(base).startswith("https://"):
                    out["violations"].append("MUST: facilitator.baseUrl is not HTTPS")
                if not _in_domain(base, host):
                    out["violations"].append("MUST: facilitator.baseUrl is out of domain")
            if not isinstance(fac.get("endpoints"), dict):
                out["violations"].append("MUST: facilitator.endpoints missing")
            if fac.get("kinds") is None:
                out["violations"].append("MUST: facilitator.kinds missing")
            if fac.get("assets") is None:
                out["warnings"].append("SHOULD: facilitator.assets missing")

    # --- SHOULDs --------------------------------------------------------------------------
    if not man.get("updated"):
        out["warnings"].append("SHOULD: no updated timestamp")
    if not (man.get("name") or man.get("description")):
        out["warnings"].append("SHOULD: no name or description")

    out["conformant"] = not out["violations"]
    return out


def safe_check(host):
    try:
        return check(host)
    except Exception as e:  # noqa: BLE001 - one odd host must not end the sweep
        return {"host": host, "manifest": False, "violations": [],
                "error": f"checker error: {type(e).__name__}"}


def main(argv):
    limit = int(argv[0]) if argv else None
    rows = json.loads(SWEEP.read_text(encoding="utf-8"))
    hosts = sorted({r["host"] for r in rows if r.get("host")})
    if limit:
        hosts = hosts[:limit]
    print(f"  validating {len(hosts)} hosts against the PR #2979 rules\n")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(safe_check, hosts))

    OUT.write_text(json.dumps({"hosts": len(res), "results": res}, indent=1), encoding="utf-8")

    served = [r for r in res if r["manifest"]]
    conf = [r for r in served if r.get("conformant")]
    print(f"  serve a manifest            : {len(served)}/{len(res)}")
    print(f"  would PASS the spec as-is   : {len(conf)}")
    print(f"  would need changes          : {len(served) - len(conf)}")

    # THE HEADLINE NUMBER ON ITS OWN IS MISLEADING, so it never prints on its own.
    #
    # `kind` is a field this spec INVENTS. Exactly one host in the entire sweep publishes it,
    # which is not a finding about the network, it is arithmetic: nobody can already satisfy a
    # requirement that did not exist until last week. Reporting "0% pass" and stopping there
    # reads as "the proposal is unreasonable" when what it actually measures is "the proposal
    # is new".
    #
    # The number that means something is how many hosts are ONE net-new field away. Those hosts
    # already satisfy everything the spec asks that was askable before it was written.
    NET_NEW = ("no kind",)
    near = [r for r in served
            if r["violations"] and all(any(n in v for n in NET_NEW) for v in r["violations"])]
    if served:
        print(f"\n  -> {len(conf)/len(served)*100:.1f}% satisfy every proposed MUST today")
        print(f"  -> but {len(near)} ({len(near)/len(served)*100:.1f}%) violate NOTHING except "
              f"fields this spec introduces,")
        print(f"     so they are one mechanical edit from compliant. Quote this number, not the "
              f"one above.")

    print("\n  every MUST violation, by count:")
    for v, n in Counter(v for r in served for v in r["violations"]).most_common(12):
        print(f"   {n:>4}x  {v}")

    print("\n  SHOULD gaps:")
    for w, n in Counter(w for r in served for w in r["warnings"]).most_common(6):
        print(f"   {n:>4}x  {w}")

    withdns = [r for r in res if r.get("dns_records")]
    print(f"\n  publish an _x402 TXT pointer today: {len(withdns)}")
    print(f"  wrote {OUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
