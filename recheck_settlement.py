#!/usr/bin/env python3
"""Recheck every failing verdict in a settlement file against the chain, independently of settlement.py.

For each failing group in settlement_<day>.json this reads the chain again and reports whether the
failure still holds:
  signing_domain_mismatch   DOMAIN_SEPARATOR() still equals the recorded token value and differs
                            from the recorded listed value
  token_lacks_eip3009       authorizationState() still reverts
  no_token_account          the recorded associated token account still does not exist
  permit2_not_deployed      the recorded addresses still have no code
  payto_zero_address / domain_fields_missing   need no chain read; restated from the listing
EVM reads use the block recorded in the file when the RPC still serves it, else the latest block,
and the output says which. Solana reads are at the current slot.

Usage: python recheck_settlement.py settlement/settlement_<day>.json
"""
import json
import sys
import time
import urllib.request

UA = {"user-agent": "verity-measure/1.0 (+https://github.com/meloliva14/x402-measure)",
      "content-type": "application/json"}
SOLANA = "https://api.mainnet-beta.solana.com"


def rpc(url, method, params):
    req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                      "params": params}).encode(), headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=30))


def at_block(urls, method, params_without_block, block):
    """(response, block label) at the pinned block if served, else at latest."""
    for url in urls:
        for blk in (hex(block), "latest"):
            try:
                out = rpc(url, method, params_without_block + [blk])
            except Exception:  # noqa: BLE001
                continue
            err = str(out.get("error", "")).lower()
            if "error" in out and blk != "latest" and ("missing trie" in err or "not available" in err
                                                       or "header not found" in err or "pruned" in err
                                                       or "unknown block" in err):
                continue
            return out, ("pinned" if blk != "latest" else "latest")
    return None, None


def solana_absent(keys):
    """address -> (exists, slot), in batches of 100, backing off when the public endpoint rate-limits."""
    out = {}
    for i in range(0, len(keys), 100):
        batch = keys[i:i + 100]
        for attempt in range(6):
            try:
                got = rpc(SOLANA, "getMultipleAccounts", [batch, {"encoding": "base64",
                                                                  "dataSlice": {"offset": 0, "length": 0}}])
                slot = got["result"]["context"]["slot"]
                for k, v in zip(batch, got["result"]["value"]):
                    out[k] = (v is not None, slot)
                break
            except Exception:  # noqa: BLE001
                time.sleep(3 * (attempt + 1))
        else:
            sys.exit("  Solana RPC kept refusing; try again later.")
    return out


def main(path):
    F = json.load(open(path, encoding="utf-8"))
    pins = F["pins"]["evm"]
    sol = solana_absent(sorted({g["evidence"]["associated_token_account"] for g in F["failing"]
                                if g["reason"] == "no_token_account"}))
    held = changed = 0
    for g in F["failing"]:
        reason, net, ev = g["reason"], g["network"], g["evidence"]
        cid = net.split(":")[1] if net.startswith("eip155:") else {"base": "8453"}.get(net)
        note = ""
        if reason == "signing_domain_mismatch":
            out, where = at_block(pins[cid]["rpcs"], "eth_call", [{"to": g["asset"], "data": "0x3644e515"}], ev["block"])
            ok = out is not None and out.get("result", "").lower() == ev["token_domain_separator"] \
                and ev["token_domain_separator"] != ev["listed_domain_separator"]
            note = f"DOMAIN_SEPARATOR read at {where} block"
        elif reason == "token_lacks_eip3009":
            data = "0xe94a0102" + "0" * 63 + "1" + "0" * 64
            out, where = at_block(pins[cid]["rpcs"], "eth_call", [{"to": g["asset"], "data": data}], ev["block"])
            ok = out is not None and "error" in out and ("revert" in str(out["error"]).lower()
                                                          or out["error"].get("code") == 3)
            note = f"authorizationState() reverted at {where} block" if ok else "did not revert"
        elif reason == "no_token_account":
            exists, slot = sol[ev["associated_token_account"]]
            ok = not exists
            note = f"account still absent at slot {slot}" if ok else "account now exists"
        elif reason == "permit2_not_deployed":
            ok = True
            for addr in ev["no_code_at"]:
                out, where = at_block(pins[cid]["rpcs"], "eth_getCode", [addr], ev["block"])
                ok &= out is not None and out.get("result") in ("0x", "0x0")
            note = "still no code"
        else:
            ok, note = True, "from the listing itself"
        held += ok
        changed += not ok
        print(("HOLDS   " if ok else "CHANGED ") + f"{g['host']} {net} {reason} ({g['options']} options): {note}")
    print(f"{held} of {held + changed} failing groups still hold")
    return 0 if not changed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
