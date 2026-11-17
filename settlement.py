#!/usr/bin/env python3
"""Can x402 payments land? A settlement census of every payment option the CDP Bazaar lists.

WHY THIS EXISTS. Every x402 census, this one included, asks whether a seller answers with a valid
payment challenge. None asks whether a payment built from that challenge could reach the seller.
A challenge can be perfectly formed and still be unpayable: the token on that chain signs under a
different name than the challenge says, so every signature fails; the seller's Solana wallet has
no account for the token, so the transfer fails; the transfer method needs a contract that is not
deployed on that chain. The buyer's client cannot see any of this from the challenge. The chain
can. This script asks the chain, for every option the CDP Bazaar lists, using public data only:
no key, no signature, no payment.

WHAT IS CHECKED. One verdict per payment option, from the first check that fails:

  EVM, scheme exact or upto (the spec's two schemes), on a chain with a public RPC we can reach:
    payto_malformed / asset_malformed   not a 20-byte hex address
    payto_zero_address                  payTo is 0x0, which USDC refuses and nobody controls
    payto_is_the_token                  payTo is the token contract itself
    asset_not_a_contract                no code at the asset address on that chain
    domain_fields_missing               EIP-3009 with no extra.name or extra.version: the official
                                        @x402/evm client throws before signing (eip3009.ts)
    token_lacks_eip3009                 EIP-3009 requested, but the token has no
                                        authorizationState(), so it has no transferWithAuthorization
    signing_domain_mismatch             keccak of the EIP-712 domain built from extra.name,
                                        extra.version, the chain id and the asset differs from the
                                        token's own DOMAIN_SEPARATOR(): every signature fails
    permit2_not_deployed                Permit2 requested (or scheme upto, which is Permit2 only),
                                        but the canonical Permit2 contract or the x402 Permit2 proxy
                                        the official client signs for has no code on that chain
    payto_blacklisted                   the token's isBlacklisted(payTo) is true
  Solana mainnet, scheme exact:
    payto_malformed / asset_malformed   not a 32-byte base58 key
    asset_not_a_mint                    the asset account does not exist or is not owned by the
                                        Token or Token-2022 program
    no_token_account                    the payTo's associated token account for that mint does not
                                        exist, and the option does not set extra.ataCreationRequired.
                                        The client transfers to that account and does not create it
                                        (scheme_exact_svm.md, section 5.4), so the transfer fails.

A RECEIVABLE option passed every check above. That is not proof a payment would settle: the
facilitator can still refuse it for reasons the chain does not show. An UNRECEIVABLE option
failed one, and the reason and the on-chain evidence are written beside it. An UNCHECKED option
is outside what this script can judge (another scheme or transfer method, a network without a
public RPC, a network string no registry lists, Circle Gateway batching), and the reason is
written beside it.

PINNING. Every EVM read for a chain is made at one block number, and every Solana read in one
getMultipleAccounts batch carries its slot; both are recorded. The Bazaar listing is recorded by
its sha256 and resource count. Anyone can recheck an UNRECEIVABLE verdict with one eth_call or one
getAccountInfo.

WHAT THIS DOES NOT CLAIM. This is the Bazaar's listing, not each seller's live 402; a seller may
serve different terms live. It does not try a payment. A token that is upgradeable can change its
behaviour later. XRPL, Stellar, Algorand and other non-EVM, non-Solana networks are not checked.

Read-only: reads public HTTP and RPC endpoints, signs nothing, sends nothing.

Usage: python settlement.py [--out-dir DIR]   writes settlement_<UTC date>.md and .json
"""
import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from monthly_report import n, pct, unbacked_numbers

HERE = Path(__file__).parent
SCHEMA = "x402-measure/settlement/1"
BAZAAR = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"
UA = {"user-agent": "verity-measure/1.0 (+https://github.com/meloliva14/x402-measure)",
      "content-type": "application/json"}

# chain id -> public RPCs, tried in order; each must report the expected eth_chainId before use
EVM_RPCS = {
    1: ["https://ethereum-rpc.publicnode.com", "https://cloudflare-eth.com"],
    10: ["https://optimism-rpc.publicnode.com", "https://mainnet.optimism.io"],
    50: ["https://erpc.xinfin.network", "https://rpc.xinfin.network"],
    56: ["https://bsc-rpc.publicnode.com", "https://bsc-dataseed1.bnbchain.org"],
    130: ["https://unichain-rpc.publicnode.com", "https://mainnet.unichain.org"],
    137: ["https://polygon-bor-rpc.publicnode.com", "https://polygon.drpc.org"],
    143: ["https://rpc.monad.xyz", "https://monad-mainnet.drpc.org"],
    146: ["https://sonic-rpc.publicnode.com", "https://rpc.soniclabs.com"],
    196: ["https://rpc.xlayer.tech", "https://xlayerrpc.okx.com"],
    480: ["https://worldchain-mainnet.g.alchemy.com/public", "https://480.rpc.thirdweb.com"],
    999: ["https://rpc.hyperliquid.xyz/evm", "https://hyperliquid.drpc.org"],
    1329: ["https://evm-rpc.sei-apis.com", "https://sei-evm-rpc.publicnode.com"],
    1868: ["https://rpc.soneium.org"],
    4326: ["https://mainnet.megaeth.com/rpc"],
    4663: ["https://robinhood-rpc.publicnode.com", "https://rpc.mainnet.chain.robinhood.com"],
    5042: ["https://rpc.mainnet.arc.io", "https://rpc.drpc.mainnet.arc.io"],
    8217: ["https://public-en.node.kaia.io"],
    8453: ["https://base-rpc.publicnode.com", "https://mainnet.base.org"],
    42161: ["https://arbitrum-one-rpc.publicnode.com", "https://arb1.arbitrum.io/rpc"],
    42220: ["https://celo-rpc.publicnode.com", "https://forno.celo.org"],
    42793: ["https://node.mainnet.etherlink.com"],
    43114: ["https://avalanche-c-chain-rpc.publicnode.com", "https://api.avax.network/ext/bc/C/rpc"],
    57073: ["https://rpc-gel.inkonchain.com", "https://rpc-qnd.inkonchain.com"],
    84532: ["https://base-sepolia-rpc.publicnode.com", "https://sepolia.base.org"],
    1187947933: ["https://skale-base.skalenodes.com/v1/base"],
}
TESTNET_CHAINS = {84532, 46630, 5042002, 11155111}
V1_EVM_NAMES = {"base": 8453, "base-sepolia": 84532, "polygon": 137, "polygon-amoy": 80002,
                "avalanche": 43114, "avalanche-fuji": 43113, "sei": 1329, "iotex": 4689,
                "peaq": 3338, "xlayer": 196, "abstract": 2741, "story": 1514}
SOL_MAINNET = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
SOL_NAMES = {SOL_MAINNET, "solana"}
SOL_OTHER = {"solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1", "solana:4uhcVJyU9pJkvQyS88uRDiswHXSCkY3z",
             "solana-devnet"}                               # devnet and testnet: not checked
SOL_RPCS = ["https://api.mainnet-beta.solana.com", "https://solana.drpc.org"]
TOKEN_PROGRAMS = {"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"}
ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
PERMIT2 = "0x000000000022d473030f116ddee9f6b43ac78ba3"
PERMIT2_PROXY = {"exact": "0x402085c248eea27d92e8b30b2c58ed07f9e20001",   # x402ExactPermit2Proxy
                 "upto": "0x4020a4f3b7b90cca423b9fabcc0ce57c6c240002"}    # x402UptoPermit2Proxy
SEL = {"DOMAIN_SEPARATOR": "0x3644e515", "authorizationState": "0xe94a0102",
       "isBlacklisted": "0xfe575a87", "name": "0x06fdde03"}
HEX20 = re.compile(r"^0x[0-9a-fA-F]{40}$")
REASONS_UNRECEIVABLE = ["payto_malformed", "asset_malformed", "payto_zero_address", "payto_is_the_token",
                        "asset_not_a_contract", "domain_fields_missing", "token_lacks_eip3009",
                        "signing_domain_mismatch", "permit2_not_deployed", "payto_blacklisted",
                        "asset_not_a_mint", "no_token_account"]


# --- keccak-256 (Ethereum's, not SHA3), pure Python ----------------------------------------------

_RC = [0x1, 0x8082, 0x800000000000808A, 0x8000000080008000, 0x808B, 0x80000001, 0x8000000080008081,
       0x8000000000008009, 0x8A, 0x88, 0x80008009, 0x8000000A, 0x8000808B, 0x800000000000008B,
       0x8000000000008089, 0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x800A,
       0x800000008000000A, 0x8000000080008081, 0x8000000000008080, 0x80000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x, k):
    k %= 64
    return ((x << k) | (x >> (64 - k))) & _M


def keccak256(data: bytes) -> bytes:
    rate = 136
    buf = bytearray(data) + b"\x01"
    while len(buf) % rate:
        buf += b"\x00"
    buf[-1] |= 0x80
    A = [[0] * 5 for _ in range(5)]
    for off in range(0, len(buf), rate):
        for i in range(rate // 8):
            A[i % 5][i // 5] ^= int.from_bytes(buf[off + 8 * i: off + 8 * i + 8], "little")
        for rc in _RC:
            C = [A[x][0] ^ A[x][1] ^ A[x][2] ^ A[x][3] ^ A[x][4] for x in range(5)]
            D = [C[(x - 1) % 5] ^ _rol(C[(x + 1) % 5], 1) for x in range(5)]
            A = [[A[x][y] ^ D[x] for y in range(5)] for x in range(5)]
            B = [[0] * 5 for _ in range(5)]
            for x in range(5):
                for y in range(5):
                    B[y][(2 * x + 3 * y) % 5] = _rol(A[x][y], _ROT[x][y])
            A = [[B[x][y] ^ ((~B[(x + 1) % 5][y]) & B[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
            A[0][0] ^= rc
    return b"".join(A[i % 5][i // 5].to_bytes(8, "little") for i in range(4))


DOMAIN_TYPEHASH = keccak256(b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")


def domain_separator(name: str, version: str, chain_id: int, contract: str) -> str:
    return "0x" + keccak256(DOMAIN_TYPEHASH + keccak256(name.encode()) + keccak256(version.encode())
                            + chain_id.to_bytes(32, "big") + bytes(12) + bytes.fromhex(contract[2:])).hex()


# --- base58 and Solana program-derived addresses -------------------------------------------------

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s: str) -> bytes:
    num = 0
    for ch in s:
        num = num * 58 + _B58.index(ch)
    raw = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + raw


def b58encode(b: bytes) -> str:
    num, out = int.from_bytes(b, "big"), ""
    while num:
        num, r = divmod(num, 58)
        out = _B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + out


def solana_key(s) -> bytes | None:
    try:
        if not isinstance(s, str) or not 32 <= len(s) <= 44:
            return None
        b = b58decode(s)
        return b if len(b) == 32 else None
    except ValueError:
        return None


_P = 2 ** 255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def on_ed25519_curve(b: bytes) -> bool:
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    u, v = (y * y - 1) % _P, (_D * y * y + 1) % _P
    x2 = u * pow(v, _P - 2, _P) % _P
    if x2 == 0:
        return not (b[31] >> 7)
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    return (x * x - x2) % _P == 0


def find_pda(seeds: list[bytes], program: bytes) -> bytes:
    for bump in range(255, -1, -1):
        h = hashlib.sha256(b"".join(seeds) + bytes([bump]) + program + b"ProgramDerivedAddress").digest()
        if not on_ed25519_curve(h):
            return h
    raise ValueError("no PDA")


def associated_token_account(owner: bytes, mint: bytes, token_program: str) -> str:
    return b58encode(find_pda([owner, b58decode(token_program), mint], b58decode(ATA_PROGRAM)))


# --- RPC -----------------------------------------------------------------------------------------

def post(url: str, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=30))


class Evm:
    """One chain, one RPC that proved its chain id, every read at one pinned block."""

    def __init__(self, chain_id: int):
        self.chain_id, self.url, self.block, self.cache, self.urls = chain_id, None, None, {}, []
        for url in EVM_RPCS.get(chain_id, []):
            try:
                got = post(url, {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []})
                if int(got["result"], 16) == chain_id:
                    self.urls.append(url)
            except Exception:  # noqa: BLE001 - an unreachable RPC is tried, then skipped
                continue
        if self.urls:
            self.url = self.urls[0]
            blk = post(self.url, {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []})
            # a few blocks behind the head, so a second RPC that lags slightly can serve the same block
            self.block = hex(int(blk["result"], 16) - 5)

    def rpc(self, method, params):
        key = (method, json.dumps(params))
        if key not in self.cache:
            last = None
            for attempt in range(8):
                url = self.urls[attempt % len(self.urls)]
                try:
                    self.cache[key] = post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                    break
                except Exception as ex:  # noqa: BLE001 - rate limits and timeouts: back off, rotate
                    last = ex
                    time.sleep(min(8, 0.5 * (attempt + 1)))
            else:
                raise RuntimeError(f"rpc failed on chain {self.chain_id}: {last}")
        return self.cache[key]

    def code(self, addr: str) -> bool:
        out = self.rpc("eth_getCode", [addr, self.block])
        if "result" not in out:
            raise RuntimeError(f"eth_getCode error on chain {self.chain_id}: {str(out.get('error'))[:160]}")
        return out["result"] not in ("0x", "0x0")

    def call(self, to: str, data: str):
        """The returned hex, or None when the call reverts (the function is absent or refuses).
        Any other RPC error raises, so a rate limit can never read as a missing function."""
        out = self.rpc("eth_call", [{"to": to, "data": data}, self.block])
        if "error" in out:
            err = out["error"] or {}
            if err.get("code") == 3 or "revert" in str(err.get("message", "")).lower():
                return None
            raise RuntimeError(f"eth_call error on chain {self.chain_id}: {str(err)[:160]}")
        r = out.get("result")
        return r if r and r != "0x" else None


def evm_word(addr: str) -> str:
    return addr[2:].lower().rjust(64, "0")


# --- classification ------------------------------------------------------------------------------

def network_of(net: str):
    """('evm', chain_id) | ('solana', None) | ('other', None) | ('unknown', None)."""
    if not isinstance(net, str):
        return ("unknown", None)
    if net in SOL_NAMES:
        return ("solana", None)
    m = re.fullmatch(r"eip155:(\d+)", net)
    if m:
        return ("evm", int(m.group(1)))
    if net in V1_EVM_NAMES:
        return ("evm", V1_EVM_NAMES[net])
    if net in SOL_OTHER or re.fullmatch(r"(xrpl|stellar|algorand|stacks|cosmos|nano|hyperliquid|lnbtc):.+", net):
        return ("other", None)
    return ("unknown", None)


def judge_evm(o: dict, chain: Evm) -> tuple[str, str | None, dict]:
    pay, asset, ex = o["payTo"], o["asset"], o["extra"]
    method = ex.get("assetTransferMethod") or ("permit2" if o["scheme"] == "upto" else "eip3009")
    if method == "permit2-exact":
        method = "permit2"
    if not (isinstance(pay, str) and HEX20.match(pay)):
        return "UNRECEIVABLE", "payto_malformed", {}
    if not (isinstance(asset, str) and HEX20.match(asset)):
        return "UNRECEIVABLE", "asset_malformed", {}
    pay_l, asset_l = pay.lower(), asset.lower()
    if int(pay_l, 16) == 0:
        return "UNRECEIVABLE", "payto_zero_address", {}
    if pay_l == asset_l:
        return "UNRECEIVABLE", "payto_is_the_token", {}
    if not chain.code(asset_l):
        return "UNRECEIVABLE", "asset_not_a_contract", {"block": int(chain.block, 16)}
    if method == "eip3009":
        if ex.get("name") == "GatewayWalletBatched":
            return "UNCHECKED", "circle_gateway", {}
        if not ex.get("name") or not ex.get("version"):
            return "UNRECEIVABLE", "domain_fields_missing", {}
        if chain.call(asset_l, SEL["authorizationState"] + evm_word("0x" + "0" * 39 + "1") + "0" * 64) is None:
            return "UNRECEIVABLE", "token_lacks_eip3009", {"block": int(chain.block, 16)}
        onchain = chain.call(asset_l, SEL["DOMAIN_SEPARATOR"])
        if onchain is None:
            return "UNCHECKED", "no_domain_separator", {}
        want = domain_separator(str(ex["name"]), str(ex["version"]), chain.chain_id, asset_l)
        if onchain.lower() != want:
            nm = chain.call(asset_l, SEL["name"])
            token_name = None
            if nm:
                try:
                    b = bytes.fromhex(nm[2:])
                    token_name = b[64:64 + int.from_bytes(b[32:64], "big")].decode()
                except Exception:  # noqa: BLE001
                    token_name = None
            return "UNRECEIVABLE", "signing_domain_mismatch", {
                "block": int(chain.block, 16), "listed_name": ex.get("name"), "listed_version": ex.get("version"),
                "token_name": token_name, "token_domain_separator": onchain.lower(), "listed_domain_separator": want}
    elif method == "permit2":
        proxy = PERMIT2_PROXY["upto" if o["scheme"] == "upto" else "exact"]
        missing = [a for a in (PERMIT2, proxy) if not chain.code(a)]
        if missing:
            return "UNRECEIVABLE", "permit2_not_deployed", {"block": int(chain.block, 16), "no_code_at": missing}
    else:
        return "UNCHECKED", "transfer_method_not_covered", {"method": method}
    bl = chain.call(asset_l, SEL["isBlacklisted"] + evm_word(pay_l))
    if bl is not None and int(bl, 16) == 1:
        return "UNRECEIVABLE", "payto_blacklisted", {"block": int(chain.block, 16)}
    return "RECEIVABLE", None, {}


def solana_accounts(keys: list[str]) -> tuple[dict, int]:
    """address -> {'owner': program} or None, for every key; and the lowest slot read."""
    out, slots = {}, []
    for i in range(0, len(keys), 100):
        batch = keys[i:i + 100]
        body = {"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                "params": [batch, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}]}
        last = None
        for attempt, url in enumerate(SOL_RPCS * 3):
            if attempt:
                time.sleep(2 * attempt)                     # the public endpoint rate-limits
            try:
                got = post(url, body)
                vals = got["result"]["value"]
                slots.append(got["result"]["context"]["slot"])
                for k, v in zip(batch, vals):
                    out[k] = {"owner": v["owner"]} if v else None
                break
            except Exception as ex:  # noqa: BLE001
                last = ex
        else:
            raise RuntimeError(f"solana rpc failed: {last}")
    return out, min(slots) if slots else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(HERE))
    ap.add_argument("--listing", help=argparse.SUPPRESS)       # a saved listing, for tests
    a = ap.parse_args(argv)
    started = datetime.now(timezone.utc)

    # 1. the listing
    if a.listing:
        items = json.loads(Path(a.listing).read_text(encoding="utf-8"))
    else:
        items, off = [], 0
        while True:
            page = post_get(f"{BAZAAR}?limit=1000&offset={off}").get("items") or []
            if not page:
                break
            items += page
            off += len(page)
    if len(items) < 1000:
        sys.exit(f"  REFUSING: the listing has only {len(items)} resources; something is wrong. Nothing written.")
    listing_sha = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()

    opts = []
    for it in items:
        res = it.get("resource") or ""
        host = (res.split("/")[2] if "://" in res else res).lower()
        for pos, acc in enumerate(it.get("accepts") or []):
            opts.append({"resource": res, "host": host, "x402Version": it.get("x402Version"), "position": pos,
                         "scheme": acc.get("scheme"), "network": acc.get("network"),
                         "asset": acc.get("asset"), "payTo": acc.get("payTo"),
                         "extra": acc.get("extra") if isinstance(acc.get("extra"), dict) else {}})

    # 2. EVM chains, one pinned block each
    chain_ids = sorted({network_of(o["network"])[1] for o in opts if network_of(o["network"])[0] == "evm"})
    with ThreadPoolExecutor(max_workers=8) as ex:
        chains = dict(zip(chain_ids, ex.map(Evm, chain_ids)))

    # 3. verdicts
    verdicts = [None] * len(opts)
    sol_idx = []
    for i, o in enumerate(opts):
        kind, cid = network_of(o["network"])
        if o["scheme"] not in ("exact", "upto"):
            verdicts[i] = ("UNCHECKED", "scheme_not_covered", {"scheme": o["scheme"]})
        elif kind == "unknown":
            verdicts[i] = ("UNCHECKED", "network_not_recognized", {})
        elif kind == "other":
            verdicts[i] = ("UNCHECKED", "network_not_covered", {})
        elif kind == "solana":
            if o["scheme"] != "exact":
                verdicts[i] = ("UNCHECKED", "scheme_not_covered", {"scheme": o["scheme"]})
            else:
                sol_idx.append(i)
        elif chains[cid].url is None:
            verdicts[i] = ("UNCHECKED", "no_public_rpc", {"chain_id": cid})

    sol_set = set(sol_idx)
    evm_idx = [i for i in range(len(opts)) if verdicts[i] is None and i not in sol_set]
    by_chain = defaultdict(list)
    for i in evm_idx:
        by_chain[network_of(opts[i]["network"])[1]].append(i)

    def key_of(o):
        return (o["scheme"], str(o["asset"]).lower(), str(o["payTo"]).lower(),
                json.dumps({k: o["extra"].get(k) for k in ("name", "version", "assetTransferMethod")}, sort_keys=True))

    def run_chain(cid):
        ch = chains[cid]
        first = {}
        for i in by_chain[cid]:
            first.setdefault(key_of(opts[i]), i)

        def judge(i):
            try:
                return judge_evm(opts[i], ch)
            except RuntimeError as e:
                return ("UNCHECKED", "rpc_failed", {"error": str(e)[:200]})
        with ThreadPoolExecutor(max_workers=4) as inner:
            memo = dict(zip(first, inner.map(judge, first.values())))
        for i in by_chain[cid]:
            verdicts[i] = memo[key_of(opts[i])]
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(run_chain, list(by_chain)))

    # Solana: mints first, then associated token accounts
    sol_slot = None
    if sol_idx:
        pre = {}
        for i in sol_idx:
            o = opts[i]
            if solana_key(o["payTo"]) is None:
                pre[i] = ("UNRECEIVABLE", "payto_malformed", {})
            elif solana_key(o["asset"]) is None:
                pre[i] = ("UNRECEIVABLE", "asset_malformed", {})
        mints = sorted({opts[i]["asset"] for i in sol_idx if i not in pre})
        mint_acc, s1 = solana_accounts(mints)
        ata_of = {}
        for i in sol_idx:
            if i in pre:
                continue
            o = opts[i]
            acc = mint_acc.get(o["asset"])
            if not acc or acc["owner"] not in TOKEN_PROGRAMS:
                pre[i] = ("UNRECEIVABLE", "asset_not_a_mint", {})
                continue
            ata_of[i] = associated_token_account(solana_key(o["payTo"]), solana_key(o["asset"]), acc["owner"])
        ata_acc, s2 = solana_accounts(sorted(set(ata_of.values())))
        sol_slot = min(s1, s2)
        for i in sol_idx:
            if i in pre:
                verdicts[i] = pre[i]
            elif ata_acc.get(ata_of[i]) is None and opts[i]["extra"].get("ataCreationRequired") is not True:
                verdicts[i] = ("UNRECEIVABLE", "no_token_account", {"associated_token_account": ata_of[i], "slot": sol_slot})
            elif ata_acc.get(ata_of[i]) is None:
                verdicts[i] = ("UNCHECKED", "token_account_created_on_payment", {"associated_token_account": ata_of[i]})
            else:
                verdicts[i] = ("RECEIVABLE", None, {})

    # 4. figures
    F = figures(opts, verdicts, items, listing_sha, chains, sol_slot, started)
    md = render(F)
    bad = unbacked_numbers(md, F)
    if bad:
        sys.exit(f"  REFUSING: the report text carries numbers the JSON does not: {bad}. Nothing written.")
    if "—" in md or "–" in md:
        sys.exit("  REFUSING: the report text carries a dash character. Nothing written.")
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    day = F["checked_utc"][:10]
    (out / f"settlement_{day}.json").write_bytes((json.dumps(F, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
    (out / f"settlement_{day}.md").write_bytes(md.encode("utf-8"))
    print(f"  {F['listing']['options']:,} options checked; -> {out / f'settlement_{day}.md'}")
    return 0


def post_get(url: str):
    req = urllib.request.Request(url, headers={"user-agent": UA["user-agent"]})
    return json.load(urllib.request.urlopen(req, timeout=60))


def figures(opts, verdicts, items, listing_sha, chains, sol_slot, started) -> dict:
    v = Counter(x[0] for x in verdicts)
    why = Counter(x[1] for x in verdicts if x[0] == "UNRECEIVABLE")
    unchecked = Counter(x[1] for x in verdicts if x[0] == "UNCHECKED")
    checked = [i for i, x in enumerate(verdicts) if x[0] != "UNCHECKED"]

    def hosts(idx):
        return {opts[i]["host"] for i in idx}

    bad_idx = [i for i, x in enumerate(verdicts) if x[0] == "UNRECEIVABLE"]
    ok_idx = [i for i, x in enumerate(verdicts) if x[0] == "RECEIVABLE"]
    res_bad = defaultdict(set)
    for i in bad_idx:
        res_bad[opts[i]["resource"]].add(i)
    res_ok = {opts[i]["resource"] for i in ok_idx}
    res_checked = {opts[i]["resource"] for i in checked}
    first_bad = {opts[i]["resource"] for i in bad_idx if opts[i]["position"] == 0}
    stranded = sorted(r for r in res_bad if r not in res_ok)
    by_reason_hosts = {r: len(hosts([i for i in bad_idx if verdicts[i][1] == r])) for r in why}

    # one row per distinct failing (host, network, asset, payTo, reason): the evidence table
    groups = defaultdict(lambda: {"options": 0, "resources": set()})
    for i in bad_idx:
        o, (_, reason, ev) = opts[i], verdicts[i]
        k = (o["host"], o["network"], o["asset"], o["payTo"], reason)
        g = groups[k]
        g["options"] += 1
        g["resources"].add(o["resource"])
        g["evidence"] = ev
        g["scheme"] = o["scheme"]
        g["listed_extra"] = {kk: o["extra"].get(kk) for kk in ("name", "version", "assetTransferMethod",
                                                                 "ataCreationRequired") if kk in o["extra"]}
    failing = [{"host": k[0], "network": k[1], "asset": k[2], "payTo": k[3], "reason": k[4],
                "scheme": g["scheme"], "options": g["options"], "resources": len(g["resources"]),
                "listed_extra": g["listed_extra"], "evidence": g["evidence"]}
               for k, g in sorted(groups.items(), key=lambda kv: (-kv[1]["options"], kv[0]))]
    nets_bad = Counter(opts[i]["network"] for i in bad_idx)
    top_hosts = Counter(opts[i]["host"] for i in bad_idx).most_common(10)
    return {
        "schema": SCHEMA,
        "checked_utc": started.isoformat(timespec="seconds"),
        "listing": {"source": BAZAAR, "resources": len(items), "options": len(opts),
                    "hosts": len({o["host"] for o in opts}), "sha256_of_sorted_json": listing_sha},
        "pins": {"evm": {str(cid): {"rpcs": c.urls, "block": int(c.block, 16)} for cid, c in sorted(chains.items()) if c.url},
                 "evm_without_reachable_rpc": sorted(cid for cid, c in chains.items() if not c.url),
                 "evm_chain_ids_listed": sorted(chains),
                 "solana_min_slot": sol_slot},
        "options": {"checked": len(checked), "checked_pct_of_all": pct(len(checked), len(opts)),
                    "receivable": v["RECEIVABLE"], "unreceivable": v["UNRECEIVABLE"],
                    "unreceivable_pct_of_checked": pct(v["UNRECEIVABLE"], len(checked)),
                    "unchecked": v["UNCHECKED"]},
        "hosts": {"checked": len(hosts(checked)), "with_an_unreceivable_option": len(hosts(bad_idx)),
                  "with_an_unreceivable_option_pct_of_checked": pct(len(hosts(bad_idx)), len(hosts(checked)))},
        "resources": {"checked": len(res_checked), "with_an_unreceivable_option": len(res_bad),
                      "with_no_receivable_checked_option": len(stranded),
                      "with_both_an_unreceivable_and_a_receivable_option": len(res_bad) - len(stranded),
                      "whose_first_listed_option_is_unreceivable": len(first_bad),
                      "with_no_receivable_checked_option_pct_of_checked": pct(len(stranded), len(res_checked))},
        "unreceivable_by_reason": {r: {"options": why[r], "hosts": by_reason_hosts[r]}
                                   for r in REASONS_UNRECEIVABLE if why[r]},
        "unreceivable_by_network": dict(nets_bad.most_common()),
        "unreceivable_top_hosts": [{"host": h, "options": c} for h, c in top_hosts],
        "unchecked_by_reason": dict(unchecked.most_common()),
        "stranded_resources": stranded,
        "failing": failing,
        "definitions": {
            "RECEIVABLE": "passed every check this script runs; not proof a payment would settle",
            "UNRECEIVABLE": "failed a check that means a payment built from the listing cannot reach the payTo",
            "UNCHECKED": "outside what this script can judge; the reason says why",
            "stranded_resource": "a resource with at least one unreceivable option and no receivable one "
                                 "(it may still have unchecked options)",
        },
    }


REASON_TEXT = {
    "payto_malformed": "the payTo is not a valid address",
    "asset_malformed": "the asset is not a valid address",
    "payto_zero_address": "the payTo is the zero address",
    "payto_is_the_token": "the payTo is the token contract itself",
    "asset_not_a_contract": "there is no contract at the asset address on that chain",
    "domain_fields_missing": "the signing name or version is missing, so the official client refuses to sign",
    "token_lacks_eip3009": "the token has no transferWithAuthorization, the transfer method the option asks for",
    "signing_domain_mismatch": "the signing name or version differs from the token's own, so every signature fails",
    "permit2_not_deployed": "Permit2 or the x402 Permit2 proxy is not deployed on that chain",
    "payto_blacklisted": "the token has blacklisted the payTo",
    "asset_not_a_mint": "the asset is not a token mint on Solana",
    "no_token_account": "the seller's Solana wallet has no account for that token, and the payment will not create one",
}


def render(F: dict) -> str:
    L, O, H, R = F["listing"], F["options"], F["hosts"], F["resources"]
    reasons = F["unreceivable_by_reason"]
    def many(k, word):
        return f"{n(k)} {word}" + ("" if k == 1 else "s")
    lines = [f"- **{many(x['options'], 'option')} on {many(x['hosts'], 'host')}:** {REASON_TEXT[r]}."
             for r, x in sorted(reasons.items(), key=lambda kv: -kv[1]["options"])]
    worst = F["failing"][:8]
    ex_lines = []
    for g in worst:
        ev = g["evidence"]
        detail = ""
        if g["reason"] == "signing_domain_mismatch" and ev.get("token_name"):
            detail = f" The listing says to sign for \"{g['listed_extra'].get('name')}\"; the token signs as \"{ev['token_name']}\"."
        elif g["reason"] == "no_token_account":
            detail = f" The account the payment would go to, {ev['associated_token_account']}, does not exist."
        ex_lines.append(f"- {g['host']} on {g['network']}: {many(g['options'], 'option')}, "
                        f"{REASON_TEXT[g['reason']]}.{detail}")
    day = F["checked_utc"][:10]
    T = [
        "# Can x402 payments land?",
        "",
        f"A settlement census of every payment option the CDP Bazaar listed on {day}.",
        "",
        "Every x402 census asks whether a seller answers with a valid payment challenge. This asks the next "
        "question: could a payment built from that challenge reach the seller? A challenge can be perfectly "
        "formed and still be unpayable, and the buyer's client can't tell. The chain can. Every check here reads "
        "public chain data only. Nothing was signed and nothing was paid.",
        "",
        "## Findings",
        "",
        f"1. **{n(O['unreceivable'])} of the {n(O['checked'])} payment options checked can't receive a payment "
        f"({O['unreceivable_pct_of_checked']}%).** They are listed by {n(H['with_an_unreceivable_option'])} of "
        f"{n(H['checked'])} hosts ({H['with_an_unreceivable_option_pct_of_checked']}%). The Bazaar listed "
        f"{n(L['options'])} options on {n(L['resources'])} resources; {n(O['checked'])} "
        f"({O['checked_pct_of_all']}%) were on a network and scheme this census checks.",
        "",
        f"2. **Most broken options sit next to a working one, so whether a buyer can pay depends on its client.** "
        f"{n(R['with_both_an_unreceivable_and_a_receivable_option'])} resources list a broken option beside one "
        f"that works, and {n(R['whose_first_listed_option_is_unreceivable'])} of the "
        f"{n(R['with_an_unreceivable_option'])} resources with a broken option list it first. A buyer that can "
        f"only pay on that network, or whose client takes the first option it supports, fails; another buyer "
        f"pays the same resource without trouble. {n(R['with_no_receivable_checked_option'])} resources have no "
        f"checked option that works at all.",
        "",
        "3. **Why they can't receive:**",
        "",
        *lines,
        "",
        "4. **The largest cases:**",
        "",
        *ex_lines,
        "",
        "## How to check one yourself",
        "",
        f"- All of them at once: `python recheck_settlement.py settlement/settlement_{day}.json` reads the chain "
        f"again for every failing verdict, independently of the script that made it.",
        "- A signing mismatch: call DOMAIN_SEPARATOR() on the token at the pinned block and compare it with the "
        "signing domain built from the listing's extra.name, extra.version, the chain id and the token address.",
        "- A missing Solana account: derive the associated token account from the payTo and the mint, and call "
        "getAccountInfo on it. Null means the account does not exist.",
        "",
        f"settlement_{day}.json beside this file has every failing option with its evidence, the block or slot "
        f"it was read at, and the RPC that answered.",
        "",
        "## What this does not show",
        "",
        "- It reads the Bazaar's listing, not each seller's live payment challenge. A seller can serve "
        "different terms live.",
        "- A receivable option passed every check here. That is not proof a payment would settle: a facilitator "
        "can still refuse it for reasons the chain does not show.",
        f"- {n(O['unchecked'])} options were not checked: other schemes and transfer methods, networks without a "
        f"public RPC, and XRPL, Stellar, Algorand and other networks. The JSON counts each reason.",
        "",
        "## Reproduce",
        "",
        "```",
        "python settlement.py --out-dir settlement",
        "```",
        "",
        "The listing changes daily, so a rerun reads a newer one; every failing verdict above can be rechecked "
        "against the chain at the block or slot recorded beside it.",
        "",
    ]
    return "\n".join(T)


if __name__ == "__main__":
    sys.exit(main())
