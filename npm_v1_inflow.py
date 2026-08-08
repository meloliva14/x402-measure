"""How fast is the unscoped x402 middleware still creating v1-only servers?

gadaffihub traced the 95 body-only sellers to their root cause on issue #2953: 75 of them emit
byte-identical JSON across Vercel, Cloudflare and Railway because they are all running the same
library. The v2 middleware moved to the `@x402/*` scope; the original unscoped packages are still
published, still resolve, and still install clean. He filed #3091 asking for one `npm deprecate`
per package.

Nobody has sized that ask. A deprecation is worth exactly the installs it prevents, and npm
publishes that number. This asks the registry three questions per package:

  1. is it still installable, and what is the latest version
  2. is it deprecated yet
  3. how many downloads last week, which is the rate of NEW v1-only servers being created

WHAT THE DOWNLOAD NUMBER IS NOT. It is not a count of humans, and it never will be. CI installs,
mirrors, Docker rebuilds and scrapers all land in it, so the true rate of new deployments is
LOWER, probably by a lot. It is still the right number for this argument, because the question is
not "how many servers exist" but "is the inflow still non-zero", and the direction of the error
does not touch that.

WHAT IT ALSO SHOWS. Deprecation only reaches people who install AFTER it lands. It does nothing
for anyone already deployed, which is the entire population gadaffihub measured. So the ask fixes
the inflow and not the stock, and that distinction belongs in the issue rather than being
discovered later.

Read-only, keyless, free. Public npm registry.
"""
import json
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone

REGISTRY = "https://registry.npmjs.org"
DOWNLOADS = "https://api.npmjs.org/downloads/point/last-week"

# The unscoped originals, and their scoped v2 replacements for contrast.
UNSCOPED = ["x402-express", "x402-hono", "x402-next", "x402-fetch", "x402-axios",
            "x402-koa", "x402-fastify", "x402"]
SCOPED = ["@x402/express", "@x402/hono", "@x402/next", "@x402/fetch", "@x402/axios"]

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
UA = {"user-agent": "verity-measure/1.0 (+https://veritylayer.dev)"}


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=15, context=_CTX) as r:
            return json.loads(r.read(2_000_000)), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__


def inspect(pkg):
    meta, err = _get(f"{REGISTRY}/{urllib.parse.quote(pkg, safe='@')}")
    if meta is None:
        return {"pkg": pkg, "exists": False, "error": err}
    latest = (meta.get("dist-tags") or {}).get("latest")
    ver = (meta.get("versions") or {}).get(latest) or {}
    # npm marks a deprecation as a string on the version document. Absence means live.
    dep = ver.get("deprecated")
    times = meta.get("time") or {}
    dl, dlerr = _get(f"{DOWNLOADS}/{urllib.parse.quote(pkg, safe='@')}")
    return {
        "pkg": pkg,
        "exists": True,
        "latest": latest,
        "published": (times.get(latest) or "")[:10],
        "deprecated": bool(dep),
        "deprecation_message": dep if isinstance(dep, str) else None,
        "downloads_last_week": (dl or {}).get("downloads") if dl else None,
        "downloads_error": dlerr,
    }


import urllib.parse  # noqa: E402  (after the helpers, used inside them)


def main():
    print(f"  npm registry, checked {datetime.now(timezone.utc).isoformat()[:16]}Z\n")
    print("  UNSCOPED (the v1-only originals gadaffihub identified):")
    live_inflow = 0
    rows = []
    for p in UNSCOPED:
        r = inspect(p)
        rows.append(r)
        if not r["exists"]:
            print(f"   {p:<16} not on the registry ({r['error']})")
            continue
        dw = r["downloads_last_week"]
        flag = "DEPRECATED" if r["deprecated"] else "still live"
        print(f"   {p:<16} {str(r['latest']):<9} pub {r['published']}  {flag:<11} "
              f"downloads/wk: {dw if dw is not None else '?'}")
        if not r["deprecated"] and isinstance(dw, int):
            live_inflow += dw

    print("\n  SCOPED (the v2 replacements, for contrast):")
    for p in SCOPED:
        r = inspect(p)
        if not r["exists"]:
            print(f"   {p:<16} not on the registry ({r['error']})")
            continue
        print(f"   {p:<16} {str(r['latest']):<9} pub {r['published']}  "
              f"downloads/wk: {r['downloads_last_week']}")

    undep = [r for r in rows if r.get("exists") and not r["deprecated"]]
    print(f"\n  undeprecated unscoped packages still installable: {len(undep)}")
    print(f"  combined downloads last week across those: {live_inflow:,}")
    print("  That is the rate the deprecation in #3091 would put a warning in front of.")
    print("  It is an upper bound on new v1-only servers: CI, mirrors and rebuilds are in it.")
    print("  It says nothing about the already-deployed hosts, who will never see a warning.")

    out = {"checked": datetime.now(timezone.utc).isoformat(), "unscoped": rows}
    open("npm_v1_inflow.json", "w", encoding="utf-8").write(json.dumps(out, indent=1))
    print("\n  wrote npm_v1_inflow.json")


main()
