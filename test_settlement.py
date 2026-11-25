"""Checks for settlement.py. Run: python test_settlement.py

Offline. The hashing and address derivation are checked against values read from the chain, not
against the script's own output, and every verdict path is checked against a fake chain.
"""
import sys

import settlement as S

ok = True


def check(name, cond):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name)


# keccak-256 test vectors (Ethereum's keccak, not NIST SHA3)
check("keccak256('')", S.keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")
check("keccak256('abc')", S.keccak256(b"abc").hex() == "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45")

# Base USDC's DOMAIN_SEPARATOR(), read from the chain at block 58,703,550 on 2026-11-17
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
check("EIP-712 domain of Base USDC matches the chain",
      S.domain_separator("USD Coin", "2", 8453, BASE_USDC)
      == "0x02fa7265e7c5d81118673727957699e4d68f74cd74b7db77da710fe8a2c7834f")
check("a different signing name gives a different domain",
      S.domain_separator("USDC", "2", 8453, BASE_USDC) != S.domain_separator("USD Coin", "2", 8453, BASE_USDC))

# A seller's USDC account on Solana, confirmed to exist and be owned by that wallet at slot 470,592,356
OWNER, USDC = "4syngecZXG1XeiVffWC1vLxpwxHyZnZj8gtBZyJt5DRX", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
ATA = S.associated_token_account(S.solana_key(OWNER), S.solana_key(USDC), "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
check("associated token account derivation matches the chain", ATA == "9epgxNUwS4k3dZYVmwWh4wtjVkFKr825PNHA4bR9qpFJ")
check("the ed25519 base point is on the curve", S.on_ed25519_curve(bytes.fromhex("58" + "66" * 31)))
check("y = 0 is on the curve (x squared is -1, a square because p is 1 mod 4)", S.on_ed25519_curve(bytes(32)))
check("a derived account address is off the curve", not S.on_ed25519_curve(S.solana_key(ATA)))
check("base58 round trip", S.b58encode(S.b58decode(USDC)) == USDC)
check("a key that decodes to more than 32 bytes is refused", S.solana_key("z" * 44) is None)
check("a short string is refused", S.solana_key("abc") is None)

nets = {"eip155:8453": ("evm", 8453), "base": ("evm", 8453), S.SOL_MAINNET: ("solana", None),
        "solana": ("solana", None), "solana:5eykt4UsFv8P8NJdTREpY1vzqKqWZvdp": ("unknown", None),
        "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1": ("other", None), "xrpl:0": ("other", None),
        "nonsense": ("unknown", None)}
for net, want in nets.items():
    check(f"network {net} reads as {want[0]}", S.network_of(net) == want)


class FakeChain:
    """A chain where every listed contract exists, with switches for each failure."""
    chain_id, block = 8453, hex(100)

    def __init__(self, domain=None, eip3009=True, permit2=True, blacklisted=False, codeless=()):
        self.domain = domain or S.domain_separator("USD Coin", "2", 8453, BASE_USDC)
        self.eip3009, self.permit2, self.blacklisted, self.codeless = eip3009, permit2, blacklisted, codeless

    def code(self, addr):
        if addr in self.codeless:
            return False
        if addr in (S.PERMIT2, S.PERMIT2_PROXY["exact"], S.PERMIT2_PROXY["upto"]):
            return self.permit2
        return True

    def call(self, to, data):
        if data.startswith(S.SEL["authorizationState"]):
            return "0x" + "0" * 64 if self.eip3009 else None
        if data.startswith(S.SEL["DOMAIN_SEPARATOR"]):
            return self.domain
        if data.startswith(S.SEL["isBlacklisted"]):
            return "0x" + "0" * 63 + ("1" if self.blacklisted else "0")
        if data.startswith(S.SEL["name"]):
            return None
        return None


PAY = "0x1111111111111111111111111111111111111111"


def opt(**kw):
    o = {"scheme": "exact", "asset": BASE_USDC, "payTo": PAY, "extra": {"name": "USD Coin", "version": "2"}}
    o.update(kw)
    return o


def verdict(o, chain=None):
    v, reason, _ = S.judge_evm(o, chain or FakeChain())
    return reason or v


check("a correct option is receivable", verdict(opt()) == "RECEIVABLE")
check("wrong signing name", verdict(opt(extra={"name": "USDC", "version": "2"})) == "signing_domain_mismatch")
check("missing version", verdict(opt(extra={"name": "USD Coin"})) == "domain_fields_missing")
check("zero payTo", verdict(opt(payTo="0x" + "0" * 40)) == "payto_zero_address")
check("payTo is the token", verdict(opt(payTo=BASE_USDC)) == "payto_is_the_token")
check("malformed payTo", verdict(opt(payTo="0x123")) == "payto_malformed")
check("asset with no code", verdict(opt(), FakeChain(codeless=(BASE_USDC,))) == "asset_not_a_contract")
check("token without EIP-3009", verdict(opt(), FakeChain(eip3009=False)) == "token_lacks_eip3009")
check("blacklisted payTo", verdict(opt(), FakeChain(blacklisted=True)) == "payto_blacklisted")
check("permit2 option, Permit2 deployed", verdict(opt(extra={"assetTransferMethod": "permit2"})) == "RECEIVABLE")
check("permit2 option, Permit2 missing",
      verdict(opt(extra={"assetTransferMethod": "permit2"}), FakeChain(permit2=False)) == "permit2_not_deployed")
check("upto uses Permit2 even with no method named", verdict(opt(scheme="upto", extra={}), FakeChain(permit2=False))
      == "permit2_not_deployed")
check("Circle Gateway is not judged", verdict(opt(extra={"name": "GatewayWalletBatched", "version": "1"}))
      == "circle_gateway")
check("an unknown transfer method is not judged", verdict(opt(extra={"assetTransferMethod": "erc7710"}))
      == "transfer_method_not_covered")


class ErrChain(S.Evm):
    """A real Evm whose RPC answers with a rate-limit error object: must raise, never read as absent."""

    def __init__(self):
        self.chain_id, self.block, self.cache, self.urls, self.url = 8453, hex(1), {}, ["x"], "x"

    def rpc(self, method, params):
        return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "rate limited"}}


try:
    ErrChain().call(BASE_USDC, S.SEL["authorizationState"])
    check("an RPC error is never read as a missing function", False)
except RuntimeError:
    check("an RPC error is never read as a missing function", True)


class RevertChain(ErrChain):
    def rpc(self, method, params):
        return {"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted"}}


check("a revert is read as absent", RevertChain().call(BASE_USDC, S.SEL["authorizationState"]) is None)

# The head-block read must survive one RPC answering with an error object, and fail loudly if none answers.
_post, _sleep, _rpcs = S.post, S.time.sleep, S.EVM_RPCS
S.time.sleep = lambda s: None
S.EVM_RPCS = {8453: ["a", "b"]}
_heads = []


def _fake_post(url, body):
    if body["method"] == "eth_chainId":
        return {"jsonrpc": "2.0", "id": 1, "result": hex(8453)}
    _heads.append(url)
    if len(_heads) == 1:
        return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "rate limited"}}
    return {"jsonrpc": "2.0", "id": 1, "result": hex(1000)}


S.post = _fake_post
check("a rate-limited head-block read is retried on the next RPC", S.Evm(8453).block == hex(995) and _heads == ["a", "b"])
S.post = lambda url, body: ({"jsonrpc": "2.0", "id": 1, "result": hex(8453)} if body["method"] == "eth_chainId"
                            else {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "rate limited"}})
try:
    S.Evm(8453)
    check("no RPC answering the head block ends the run loudly", False)
except RuntimeError:
    check("no RPC answering the head block ends the run loudly", True)
S.post, S.time.sleep, S.EVM_RPCS = _post, _sleep, _rpcs

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
