"""Minimal JSON-RPC + USDC log helpers. Standard library only.

Read-only. Nothing here signs, spends, or needs a key.
"""
import json
import urllib.request

# Public endpoints. Both are rate-limited; the fallback matters on long sweeps.
RPCS = {
    "base": ["https://mainnet.base.org", "https://base.drpc.org"],
    "base-sepolia": ["https://sepolia.base.org"],
}

# Canonical USDC per chain, and the ERC-20 Transfer topic.
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"          # Base mainnet
USDC_BASE_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

BLOCK_SECONDS = 2       # Base
MAX_RANGE = 9_000       # public RPCs cap eth_getLogs well under 10k blocks


def rpc(method, params, chain="base"):
    """Call `method`, falling back through the endpoint list before giving up."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    last = None
    for url in RPCS[chain]:
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "x402-measure"})
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.loads(r.read())
            if "error" in out:
                last = RuntimeError(str(out["error"]))
                continue
            return out["result"]
        except Exception as e:  # noqa: BLE001 - try the next endpoint, report the last failure
            last = e
            continue
    raise last or RuntimeError("all RPC endpoints failed")


def topic_addr(a):
    """An address, left-padded to a 32-byte log topic."""
    return "0x" + a.lower().replace("0x", "").rjust(64, "0")


def blocks_for_days(days, chain="base"):
    """(start_block, head_block) covering the last `days`."""
    head = int(rpc("eth_blockNumber", [], chain), 16)
    return max(0, head - (days * 86400) // BLOCK_SECONDS), head


def token_name(asset, chain="base"):
    """ERC-20 name(). Use this to check an x402 challenge's extra.name is honest --
    the EIP-712 domain must match the token contract or every signature fails to verify,
    and the value legitimately differs per chain (Base mainnet "USD Coin" vs Sepolia "USDC")."""
    h = rpc("eth_call", [{"to": asset, "data": "0x06fdde03"}, "latest"], chain)
    if not h or len(h) < 130:
        return None
    length = int(h[66:130], 16)
    return bytes.fromhex(h[130:130 + length * 2]).decode()


def revenue(addr, days, chain="base", asset=USDC):
    """Every USDC payment into `addr` over `days`.

    Returns (total_usd, n_payments, n_unique_payers).
    """
    start, head = blocks_for_days(days, chain)
    logs, frm = [], start
    while frm <= head:
        to = min(frm + MAX_RANGE - 1, head)
        logs.extend(rpc("eth_getLogs", [{
            "fromBlock": hex(frm), "toBlock": hex(to),
            "address": asset, "topics": [TRANSFER, None, topic_addr(addr)],
        }], chain))
        frm = to + 1
    total, payers = 0.0, set()
    for lg in logs:
        try:
            total += int(lg["data"], 16) / 1e6      # USDC has 6 decimals
        except (ValueError, KeyError, TypeError):
            continue
        payers.add("0x" + lg["topics"][1][-40:])
    return round(total, 2), len(logs), len(payers)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python rpc.py <address> [days]")
        raise SystemExit(1)
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    usd, n, uniq = revenue(sys.argv[1], days)
    print(f"  {sys.argv[1]}  last {days}d:  ${usd:,.2f}  {n} payments  {uniq} unique payers")
