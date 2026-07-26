"""Can a stock x402 v2 client actually pay this endpoint?

Reads the free 402 an endpoint already serves and answers one question: given that
challenge, could a reference `@x402/evm` 2.x buyer construct a payment at all?

This checks the step before settlement that nobody instruments. A failure here means a
standard buyer throws before any money moves -- which, in a seller's funnel, is
indistinguishable from "nobody wanted it".

No wallet, no key, no payment. Only the free 402 the endpoint already returns.

Grounded in the reference client, not in spec prose. From @x402/evm 2.x
(dist/cjs/index.js, `signEIP3009Authorization`):

    if (!requirements.extra?.name || !requirements.extra?.version) {
      throw new Error(
        `EIP-712 domain parameters (name, version) are required in payment
         requirements for asset ${requirements.asset}`)
    }

and `signERC3009` builds the EIP-712 domain from extra.name / extra.version. If those
are absent the buyer cannot sign, no matter how well-formed the rest of the challenge is.

USAGE
    python preflight.py https://api.example.com/paid-route
    python preflight.py URL1 URL2 URL3
    python preflight.py --openapi https://api.example.com/openapi.json

Exit code is 0 if every endpoint is payable, 1 otherwise.
"""
import base64
import json
import ssl
import sys
import urllib.error
import urllib.request

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = "x402-measure preflight (read-only; no payment is ever sent)"

EVM_SIGN_ERROR = ("EIP-712 domain parameters (name, version) are required in "
                  "payment requirements")

# x402 v1 named its networks; v2 uses CAIP-2 ("eip155:8453"). These are EVM chains --
# NOT non-EVM. An early version of this script classified network "base" as Solana simply
# because it did not start with "eip155", i.e. it failed open into a confidently wrong
# label. Keep the list explicit.
V1_EVM_NAMES = {
    "base", "base-sepolia", "base-goerli", "ethereum", "mainnet", "sepolia",
    "polygon", "polygon-amoy", "polygon-mumbai", "avalanche", "avalanche-fuji",
    "sei", "sei-testnet", "optimism", "arbitrum", "arbitrum-sepolia", "iotex", "peaq",
}


def fetch(url, method):
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json")
    if method == "POST":
        req.data = b"{}"
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def get_402(url):
    """Try GET, fall back to POST. Match the verb to the resource before concluding
    anything -- a POST-only route answers GET with 404/405 and looks broken when it isn't."""
    status, headers, body = fetch(url, "GET")
    if status in (400, 404, 405, 501):
        status, headers, body = fetch(url, "POST")
    return status, headers, body


def parse_challenge(headers, body):
    """v2 carries the challenge in the base64 PAYMENT-REQUIRED header; v1 put it in the body."""
    hdr = None
    for k, v in headers.items():
        if k.lower() == "payment-required":
            try:
                hdr = json.loads(base64.b64decode(v + "=="))
            except Exception:  # noqa: BLE001
                hdr = None
            break
    try:
        bod = json.loads(body)
    except Exception:  # noqa: BLE001
        bod = None
    return hdr, bod


def classify(url):
    try:
        status, headers, body = get_402(url)
    except Exception as e:  # noqa: BLE001
        return "UNREACHABLE", [type(e).__name__], None

    if status != 402:
        return "NO_402", [f"HTTP {status} - endpoint is not payment-gated right now"], None

    hdr, bod = parse_challenge(headers, body)
    ch = hdr if isinstance(hdr, dict) else (bod if isinstance(bod, dict) else None)
    where = "header" if isinstance(hdr, dict) else "body"
    if not ch:
        return "UNPARSEABLE", ["402 returned, but no readable challenge"], None

    notes = []
    accepts = ch.get("accepts")
    if not isinstance(accepts, list) or not accepts:
        return "BLOCKED", [f"x402Version={ch.get('x402Version')}, no accepts[] in the {where}"
                           " - a v2 client has nothing to iterate over"], ch
    a = accepts[0]
    net = str(a.get("network", ""))

    if net.startswith("solana") or net.startswith("sol:"):
        return "NON_EVM", [f"network={net} - different signer, not assessed"], ch

    if net in V1_EVM_NAMES:
        notes.append(f'network="{net}" is v1 naming; v2 uses CAIP-2 (e.g. eip155:8453)')
        if hdr is None:
            notes.append("challenge is in the body with no PAYMENT-REQUIRED header, so a v2 "
                         "buyer reads the header, finds nothing, and never sees your price")
        if a.get("amount") is None and a.get("maxAmountRequired") is not None:
            notes.append("uses v1 maxAmountRequired rather than v2 amount")
        return "V1", notes, ch

    if not net.startswith("eip155"):
        return "UNKNOWN_NETWORK", [f"network={net}"], ch

    for f in ("scheme", "asset", "payTo"):
        if not a.get(f):
            notes.append(f"missing accepts[0].{f}")
    if a.get("amount") is None:
        notes.append("missing accepts[0].amount")

    extra = a.get("extra") or {}
    if not extra.get("name") or not extra.get("version"):
        notes.append(f"extra={json.dumps(a.get('extra'))} -> {EVM_SIGN_ERROR} "
                     f"for asset {a.get('asset')}")
        return "BLOCKED", notes, ch

    notes.append(f"amount={a.get('amount')} asset={a.get('asset')} "
                 f"extra.name={extra.get('name')!r}")
    return ("OK" if len(notes) == 1 else "WARN"), notes, ch


def openapi_routes(url):
    """Every path in an OpenAPI doc, so a whole service can be checked rather than one route."""
    _, _, body = fetch(url, "GET")
    spec = json.loads(body)
    base = url.rsplit("/", 1)[0]
    out = []
    for path in (spec.get("paths") or {}):
        out.append(base.rstrip("/") + path)
    return out


VERDICT_NOTE = {
    "OK": "a stock v2 client can sign this",
    "WARN": "signable, with caveats",
    "BLOCKED": "a stock v2 client CANNOT construct a payment",
    "V1": "v1 challenge - a v2 client cannot read it at all",
    "NON_EVM": "not assessed",
    "NO_402": "not payment-gated",
    "UNPARSEABLE": "402 with no readable challenge",
    "UNREACHABLE": "no response",
    "UNKNOWN_NETWORK": "unrecognised network id",
}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--openapi":
        if len(argv) < 2:
            print("usage: python preflight.py --openapi <openapi.json url>")
            return 1
        urls = openapi_routes(argv[1])
        print(f"\n  {len(urls)} routes from {argv[1]}")
    else:
        urls = argv

    print("\n  x402 v2 CLIENT-COMPATIBILITY PREFLIGHT")
    print("  read-only - no wallet, no key, no payment sent\n")
    bad = 0
    for u in urls:
        verdict, notes, _ = classify(u)
        if verdict not in ("OK", "WARN", "NON_EVM", "NO_402"):
            bad += 1
        label = u if len(u) <= 62 else u[:59] + "..."
        print(f"  {label}")
        print(f"    {verdict:<16} {VERDICT_NOTE.get(verdict, '')}")
        for n in notes:
            print(f"      - {n}")
        print()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
