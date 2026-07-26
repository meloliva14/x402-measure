# x402-measure

Measure the x402 network from public data. No wallet, no API key, no payment ever sent.

Everything about x402 adoption is currently asserted. These scripts measure it — the
registry, what endpoints actually serve, and what the seller wallets actually received
on-chain. Python standard library only, nothing to install.

---

## Why this exists

A seller instrumenting their own funnel sees discovery hits, then price quotes, then
settlements. When the last number is zero, the natural conclusion is "nobody wanted it."

That conclusion can be wrong in a way nothing in the funnel reveals. If the 402 challenge
you serve can't be read or signed by a standard client, the buyer never gets far enough to
decline — and a buyer who couldn't pay looks exactly like a buyer who didn't want to. No
error is raised on either side.

`preflight.py` checks that specific failure. The sweep scripts put it in context.

---

## Quickstart

```bash
git clone https://github.com/meloliva14/x402-measure
cd x402-measure

# Is my endpoint payable by a standard v2 client?
python preflight.py https://api.example.com/paid-route

# Check an entire service from its OpenAPI doc
python preflight.py --openapi https://api.example.com/openapi.json

# Measure the whole network
python harvest_bazaar.py     # pull the CDP Bazaar          -> bazaar_all.json, paytos.json
python live_402_sweep.py     # one live request per host    -> sweep_results.json
python manifest_probe.py     # who also self-publishes?     -> manifest_probe.json
python demand_sweep.py 7     # on-chain revenue, 7 days     -> demand_results.json

# One wallet, on its own
python rpc.py 0xYourPayToAddress 30
```

`preflight.py` exits non-zero if any endpoint is unpayable, so it drops into CI.

---

## What each script does

| script | what it answers |
|---|---|
| `preflight.py` | Given the 402 you serve, could a stock `@x402/evm` 2.x buyer construct a payment? |
| `harvest_bazaar.py` | What does the CDP Bazaar claim exists? |
| `live_402_sweep.py` | What do those hosts actually serve right now? |
| `manifest_probe.py` | Do registry-listed sellers also publish their own `/.well-known/x402`? |
| `demand_sweep.py` | Which advertised payTo wallets actually received USDC, from how many payers? |
| `rpc.py` | Shared JSON-RPC + USDC log helpers. Also runnable for a single address. |

---

## The check `preflight.py` performs

It is grounded in the reference client rather than in spec prose. From `@x402/evm` 2.x:

```js
if (!requirements.extra?.name || !requirements.extra?.version) {
  throw new Error(
    `EIP-712 domain parameters (name, version) are required in payment
     requirements for asset ${requirements.asset}`)
}
```

`signERC3009` builds the EIP-712 domain from `extra.name` / `extra.version`. Absent those,
the buyer throws **before signing**, however well-formed the rest of the challenge is.

It also separates two things that are easy to confuse:

- **v1 vs v2.** v1 puts the challenge in the response body; v2 moved it to the base64
  `PAYMENT-REQUIRED` header. These do not degrade into each other — a v2 client reads the
  header, finds nothing, and never sees your price at all.
- **v1 network naming.** v1 used names (`"base"`); v2 uses CAIP-2 (`"eip155:8453"`). A
  seller on `"base"` is on an EVM chain, not a non-EVM one. An early build of this script
  classified `"base"` as Solana purely because it didn't start with `eip155` — it failed
  open into a confidently wrong label. `V1_EVM_NAMES` is explicit for that reason.

`rpc.token_name()` is included for a related trap: `extra.name` must match what the token
contract's `name()` actually returns, and that legitimately differs per chain — Base
mainnet USDC is `"USD Coin"`, Base Sepolia USDC is `"USDC"`. Copying a mainnet domain to
testnet produces signatures that fail verification with no useful error.

---

## Method, and what it does not cover

- **One request per host.** These scripts are not a crawler.
- **Nothing is signed, and no payment is ever sent.** Every check runs against the free
  402 an endpoint already returns.
- **A timeout is recorded `UNREACHABLE`, never "broken."**
- **`demand_sweep.py` splits any block range the RPC refuses rather than skipping it.** A
  silently dropped range would understate payments and overstate "never paid" — the exact
  direction this must not err in.

Limitations worth stating plainly:

- **One payTo per seller is assumed.** Anyone rotating wallets is undercounted.
- **These wallets can receive non-x402 USDC too.** A wallet whose average payment is
  retail-sized is almost certainly carrying ordinary business alongside agent traffic, so
  treat dollar totals as softer than payment counts. `demand_sweep.py` prints the largest
  wallet's average payment size so you can judge this yourself.
- **The Bazaar is one registry, not the whole network.** Sellers who publish only their
  own `/.well-known/x402` manifest are not in it. In practice the two populations overlap
  far less than you'd expect, so a measurement of one says little about the other. Point
  `preflight.py` and `rpc.py` at any endpoint or wallet directly to cover the rest.

No result here should be read as "the state of x402." It is the state of a named,
reproducible sample, which is a different and more defensible claim.

---

## Findings

A run from 2026-07-25 is written up in [FINDINGS.md](FINDINGS.md) — aggregate only.

Per-wallet revenue is deliberately **not** published. Every figure is derivable from public
chain data in a few minutes with these scripts, which is the point of open-sourcing them;
shipping a ready-made map of which seller earns what is a different act, and not one worth
doing to people who are building in the open.

---

## License

MIT. Built while doing interop work in the
[x402 Foundation](https://github.com/x402-foundation/x402) Domain Discovery working group.

Bug reports and results that contradict mine are both welcome — the second kind more so.
