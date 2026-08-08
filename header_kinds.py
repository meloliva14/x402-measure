"""Two checks on gadaffihub's 2026-08-08 correction, issue #2953.

He corrected his own "serves both" figure down by 3x and published the fix. Two things in the
new comment are checkable, and testing them is more useful than agreeing.

CHECK 1 — the .map() mechanism, which is the load-bearing claim.
He reports x402@1.2.0 does `accepts.map(x => PaymentRequirementsSchema.parse(x))`, so ONE
unparseable entry aborts the whole array, making a seller who hedges with both shapes strictly
worse off than v1-only. If that is .map and not .filter, the trap is real. Read the tarball.

CHECK 2 — his own stated limit, which he flagged and did not measure.
"www-authenticate containing x402 counts as a header for me, which is looser than the spec."
His 703/715 "the header path is effectively universal" rests on that. If a chunk of those are
www-authenticate rather than PAYMENT-REQUIRED, a spec-current buyer reading only
PAYMENT-REQUIRED sees fewer. Measurable from our own census.
"""
import base64
import io
import json
import re
import ssl
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = {"user-agent": "verity-measure/1.0 (+https://veritylayer.dev)",
      "content-type": "application/json"}


def get(url, raw=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
        d = r.read(20_000_000)
    return d if raw else json.loads(d)


def check_map_vs_filter():
    print("  CHECK 1: does x402@1.2.0 use .map() over accepts[]?\n")
    for pkg in ("x402", "x402-fetch", "x402-axios"):
        try:
            m = get(f"https://registry.npmjs.org/{pkg}")
            v = m["dist-tags"]["latest"]
            blob = get(m["versions"][v]["dist"]["tarball"], raw=True)
        except Exception as e:  # noqa: BLE001
            print(f"   {pkg}: fetch failed {type(e).__name__}")
            continue
        body = []
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            for mem in tf.getmembers():
                if mem.isfile() and mem.size < 3_000_000 and re.search(r"\.(js|mjs|cjs|ts)$", mem.name):
                    try:
                        body.append(tf.extractfile(mem).read().decode("utf-8", "ignore"))
                    except Exception:  # noqa: BLE001
                        pass
        b = "\n".join(body)
        # The exact shape he quoted, and the safer alternative.
        maps = re.findall(r"accepts\s*\.\s*map\s*\(", b)
        filters = re.findall(r"accepts\s*\.\s*filter\s*\(", b)
        parse_calls = re.findall(r"PaymentRequirementsSchema\s*\.\s*(parse|safeParse)\s*\(", b)
        print(f"   {pkg}@{v}")
        print(f"     accepts.map(   : {len(maps)}")
        print(f"     accepts.filter(: {len(filters)}")
        print(f"     schema calls   : {Counter(parse_calls) or 'none'}")
        for m_ in re.finditer(r".{0,90}accepts\s*\.\s*map\s*\(.{0,110}", b):
            print(f"     context: {re.sub(r'\\s+', ' ', m_.group())[:190]}")
            break


def header_kind(row):
    """Which header, if any, carries the challenge: PAYMENT-REQUIRED or www-authenticate?"""
    url = row.get("url")
    if not url:
        return None
    req = urllib.request.Request(url, method="POST", data=b"{}", headers=UA)
    try:
        urllib.request.urlopen(req, timeout=12, context=CTX)
        return {"host": row["host"], "kind": "no-402"}
    except urllib.error.HTTPError as e:
        if e.code != 402:
            return {"host": row["host"], "kind": "no-402"}
        hs = {k.lower(): v for k, v in e.headers.items()}
        pr = "payment-required" in hs
        wa = "www-authenticate" in hs and "x402" in (hs.get("www-authenticate") or "").lower()
        kind = ("both" if pr and wa else "payment-required" if pr
                else "www-authenticate-only" if wa else "neither")
        return {"host": row["host"], "kind": kind}
    except Exception:  # noqa: BLE001
        return {"host": row["host"], "kind": "unreachable"}


def check_header_kinds(n=350):
    print(f"\n  CHECK 2: of live 402s, which header actually carries it? (sample {n})\n")
    rows = json.load(open(r"G:\VERITY\x402-measure\sweep_results.json", encoding="utf-8"))
    live = [r for r in rows if r.get("verdict") in ("OK", "V1") and r.get("url")][:n]
    with ThreadPoolExecutor(max_workers=12) as ex:
        res = [r for r in ex.map(header_kind, live) if r]
    c = Counter(r["kind"] for r in res)
    for k, v in c.most_common():
        print(f"   {v:>5}  {k}")
    gated = sum(v for k, v in c.items() if k not in ("no-402", "unreachable"))
    if gated:
        pr = c.get("payment-required", 0) + c.get("both", 0)
        print(f"\n   of {gated} live 402s: {pr} carry PAYMENT-REQUIRED "
              f"({pr/gated*100:.1f}%), {c.get('www-authenticate-only',0)} only www-authenticate")


check_map_vs_filter()
check_header_kinds()
