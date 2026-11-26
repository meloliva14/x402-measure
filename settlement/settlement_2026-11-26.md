# Can x402 payments land?

A settlement census of every payment option the CDP Bazaar listed on 2026-11-26.

Every x402 census asks whether a seller answers with a valid payment challenge. This asks the next question: could a payment built from that challenge reach the seller? A challenge can be perfectly formed and still be unpayable, and the buyer's client can't tell. The chain can. Every check here reads public chain data only. Nothing was signed and nothing was paid.

## Findings

1. **1,309 of the 218,969 payment options checked can't receive a payment (0.6%).** They are listed by 174 of 3,322 hosts (5.2%). The Bazaar listed 228,595 options on 89,065 resources; 218,969 (95.8%) were on a network and scheme this census checks.

2. **Most broken options sit next to a working one, so whether a buyer can pay depends on its client.** 1,237 resources list a broken option beside one that works, and 12 of the 1,239 resources with a broken option list it first. A buyer that can only pay on that network, or whose client takes the first option it supports, fails; another buyer pays the same resource without trouble. 2 resources have no checked option that works at all.

3. **Why they can't receive:**

- **1,067 options on 163 hosts:** the seller's Solana wallet has no account for that token, and the payment will not create one.
- **129 options on 3 hosts:** the token has no transferWithAuthorization, the transfer method the option asks for.
- **98 options on 5 hosts:** the signing name or version differs from the token's own, so every signature fails.
- **10 options on 1 host:** the signing name or version is missing, so the official client refuses to sign.
- **3 options on 1 host:** the asset is not a token mint on Solana.
- **1 option on 1 host:** the payTo is the zero address.
- **1 option on 1 host:** Permit2 or the x402 Permit2 proxy is not deployed on that chain.

4. **The largest cases:**

- emc2ai.io on solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp: 199 options, the seller's Solana wallet has no account for that token, and the payment will not create one. The account the payment would go to, AGPbCGUgcyo161EmHcS5LQscadvdkYSQP6P9Y8K5njWA, does not exist.
- rengi.dev on solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp: 77 options, the seller's Solana wallet has no account for that token, and the payment will not create one. The account the payment would go to, 9CtEpXNo9FCUYYaLMns6bb2w3opVcTozZ4or1ic4tTNz, does not exist.
- saylorinnovations.com on solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp: 67 options, the seller's Solana wallet has no account for that token, and the payment will not create one. The account the payment would go to, 7d7Y7HwG8TuFRXdKfX6NS7pCeTeGx5hvSx31bfk8iGNC, does not exist.
- archtools.dev on eip155:137: 52 options, the token has no transferWithAuthorization, the transfer method the option asks for.
- archtools.dev on eip155:8453: 52 options, the token has no transferWithAuthorization, the transfer method the option asks for.
- agents.204-168-199-108.sslip.io on solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp: 43 options, the seller's Solana wallet has no account for that token, and the payment will not create one. The account the payment would go to, 6md8UhEyDfAbaKqNTVEuPH2qrFuXtxjHPnJN3kDBqZq, does not exist.
- api.carbon-cashmere.de on eip155:480: 43 options, the signing name or version differs from the token's own, so every signature fails. The listing says to sign for "USD Coin"; the token signs as "USDC".
- api.nuasense.com on solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp: 37 options, the seller's Solana wallet has no account for that token, and the payment will not create one. The account the payment would go to, AzLaeKEMnE4MdSmCNNHNDKzifGTHbeasYhUvuC8gK9rt, does not exist.

## How to check one yourself

- All of them at once: `python recheck_settlement.py settlement/settlement_2026-11-26.json` reads the chain again for every failing verdict, independently of the script that made it.
- A signing mismatch: call DOMAIN_SEPARATOR() on the token at the pinned block and compare it with the signing domain built from the listing's extra.name, extra.version, the chain id and the token address.
- A missing Solana account: derive the associated token account from the payTo and the mint, and call getAccountInfo on it. Null means the account does not exist.

settlement_2026-11-26.json beside this file has every failing option with its evidence, the block or slot it was read at, and the RPC that answered.

## What this does not show

- It reads the Bazaar's listing, not each seller's live payment challenge. A seller can serve different terms live.
- A receivable option passed every check here. That is not proof a payment would settle: a facilitator can still refuse it for reasons the chain does not show.
- 9,626 options were not checked: other schemes and transfer methods, networks without a public RPC, and XRPL, Stellar, Algorand and other networks. The JSON counts each reason.

## Reproduce

```
python settlement.py --out-dir settlement
```

The listing changes daily, so a rerun reads a newer one; every failing verdict above can be rechecked against the chain at the block or slot recorded beside it.
