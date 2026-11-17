"""How many x402 sellers in the census are paid to a wallet that owns an ERC-8004 agent identity?

Seller side of the question vet402 asked in #wg-identity on 2026-11-13 (vet402 answered it from
the buyer side: payTo addresses among the sellers it bought from).

  1. Roster: every host in the latest signed snapshot with verdict OK or V1 (the same roster
     collect_payto.py uses). Each gets an unauthenticated GET, then a POST if the GET did not
     produce a 402, the same order the census uses; the payTo is read from the PAYMENT-REQUIRED
     header, else from the body. Nothing signed, nothing paid.
  2. Every distinct EVM payTo is checked against the ERC-8004 Identity Registry on Base
     (0x8004A169FB4a3325136EB29fA0ceB6D2e539a432, an ERC-721): balanceOf(payTo) at one pinned
     block. "Owns an identity" means balanceOf > 0, i.e. the wallet is the OWNER of at least one
     agent NFT. An agent that only names the wallet in its metadata is not counted.
  3. The registry address is checked before use: its name() must be "AgentIdentity" and
     ownerOf(94639) must equal a match vet402 publishes, or nothing is written.
  4. The overlap with vet402's published matches (https://vet402.com/api/v1/observatory/state)
     is reported, with the time vet402 stamped on its data.

Usage: python erc8004_payto.py     writes erc8004_payto_<snapshot date>.json
"""
import base64, json, ssl, sys, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"
RPCS = ["https://base-rpc.publicnode.com", "https://mainnet.base.org", "https://base.drpc.org"]
VET402 = "https://vet402.com/api/v1/observatory/state"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {"user-agent": "verity-measure/1.0 (+https://veritylayer.dev)", "content-type": "application/json"}


def payto_of(row):
    """GET, then POST if the GET gave no 402 (the census order); payTo from header, else body."""
    for method, data in (("GET", None), ("POST", b"{}")):
        got = _try(row, method, data)
        if got is not False:
            return got
    return None


def _try(row, method, data):
    """None: a 402 with no readable payTo. False: no 402, try the next verb. dict: found."""
    req = urllib.request.Request(row["url"], method=method, data=data, headers=UA)
    try:
        urllib.request.urlopen(req, timeout=12, context=CTX)
        return False
    except urllib.error.HTTPError as e:
        if e.code != 402:
            return False
        p = None
        h = e.headers.get("PAYMENT-REQUIRED") or e.headers.get("payment-required")
        if h:
            try:
                p = (json.loads(base64.b64decode(h)).get("accepts") or [{}])[0].get("payTo")
            except Exception:
                p = None
        if not p:
            try:
                b = json.loads(e.read(200_000))
                p = ((b.get("accepts") or [b])[0]).get("payTo")
            except Exception:
                p = None
        return {"host": row["host"], "payTo": p} if p else None
    except Exception:
        return False


def rpc(method, params):
    last = None
    for url in RPCS:
        try:
            r = urllib.request.Request(url, data=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(), headers=UA)
            out = json.load(urllib.request.urlopen(r, timeout=20))
            if "result" in out:
                return out["result"]
            last = out.get("error")
        except Exception as ex:  # noqa: BLE001
            last = ex
    sys.exit(f"  REFUSING: every RPC failed for {method}: {last}. Nothing written.")


def call(data, block):
    return rpc("eth_call", [{"to": REGISTRY, "data": data}, block])


def abi_string(hexdata):
    b = bytes.fromhex(hexdata[2:]); n = int.from_bytes(b[32:64], "big")
    return b[64:64 + n].decode()


def main():
    snaps = HERE / "snapshots"
    day = sorted(p.name for p in snaps.iterdir() if p.name[:2] == "20")[-1]
    rows = json.loads((snaps / day / "observation.json").read_text(encoding="utf-8"))["observations"]
    roster = [r for r in rows if r.get("verdict") in ("OK", "V1") and r.get("url")]
    print(f"  roster: {len(roster)} hosts with verdict OK or V1 in the {day} snapshot")

    # vet402's published matches, read first so one of them can check the registry address
    v = json.load(urllib.request.urlopen(urllib.request.Request(VET402, headers=UA), timeout=30))["erc8004"]
    vet_payto = {m["payTo"].lower() for m in v["matches"] if m.get("chainId") == "eip155:8453"}

    block = rpc("eth_blockNumber", [])
    name = abi_string(call("0x06fdde03", block))
    probe = next(m for m in v["matches"] if m.get("chainId") == "eip155:8453" and m.get("matchKind") == "owner")
    owner = "0x" + call("0x6352211e" + hex(int(probe["agentId"]))[2:].rjust(64, "0"), block)[-40:]
    if name != "AgentIdentity" or owner.lower() != probe["payTo"].lower():
        sys.exit(f"  REFUSING: registry check failed (name {name!r}, ownerOf {owner} vs {probe['payTo']}).")
    print(f"  registry checked at block {int(block, 16):,}: name AgentIdentity, "
          f"ownerOf({probe['agentId']}) matches vet402")

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with ThreadPoolExecutor(max_workers=16) as ex:
        got = [r for r in ex.map(payto_of, roster) if r]
    wallets = {}
    for r in got:
        p = (r["payTo"] or "").lower()
        if p.startswith("0x") and len(p) == 42:
            wallets.setdefault(p, []).append(r["host"])
    print(f"  {len(got)} hosts answered with a payTo; {len(wallets)} distinct EVM wallets")

    def bal(p):
        return p, int(call("0x70a08231" + p[2:].rjust(64, "0"), block), 16)
    with ThreadPoolExecutor(max_workers=8) as ex:
        balances = dict(ex.map(bal, sorted(wallets)))

    owners = {p: n for p, n in balances.items() if n > 0}
    hosts_behind = sorted(h for p in owners for h in wallets[p])
    out = {
        "schema": "x402-measure/erc8004-payto/1",
        "question": "How many census sellers are paid to a wallet that owns an ERC-8004 agent identity on Base?",
        "roster": {"snapshot": day, "verdicts": ["OK", "V1"], "hosts": len(roster)},
        "probed_utc": started,
        "registry": {"address": REGISTRY, "chain": "eip155:8453", "block": int(block, 16),
                     "check": f"name() == AgentIdentity and ownerOf({probe['agentId']}) == {probe['payTo']}"},
        "definition": "owns an identity = balanceOf(payTo) > 0 on the registry at the pinned block "
                      "(owner of at least one agent NFT; metadata-only links not counted)",
        "hosts_with_payto": len(got),
        "distinct_evm_wallets": len(wallets),
        "wallets_owning_an_identity": len(owners),
        "hosts_paid_to_such_a_wallet": len(hosts_behind),
        "agents_owned_by_those_wallets": sum(owners.values()),
        "owners": [{"payTo": p, "agents_owned": n, "hosts": sorted(wallets[p])}
                   for p, n in sorted(owners.items(), key=lambda x: (-len(wallets[x[0]]), x[0]))],
        "vet402": {"source": VET402, "checkedAt": v.get("checkedAt"),
                   "matched_payto_base": len(vet_payto),
                   "overlap_with_census_owner_wallets": len(vet_payto & set(owners)),
                   "overlap_with_any_census_wallet": len(vet_payto & set(wallets))},
    }
    path = HERE / f"erc8004_payto_{day}.json"
    path.write_bytes((json.dumps(out, indent=1) + "\n").encode("utf-8"))
    print(f"  wallets owning an identity: {len(owners)} of {len(wallets)}; "
          f"hosts paid to them: {len(hosts_behind)} of {len(got)}")
    print(f"  vet402 overlap: {out['vet402']['overlap_with_census_owner_wallets']} of its "
          f"{len(vet_payto)} matched wallets are census owner wallets")
    print(f"  wrote {path.name}")


if __name__ == "__main__":
    main()
