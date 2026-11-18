# Can x402 payments land?

A settlement census of every payment option the CDP Bazaar listed on 2026-11-18.

Every x402 census asks whether a seller answers with a valid payment challenge. This asks the next question: could a payment built from that challenge reach the seller? A challenge can be perfectly formed and still be unpayable, and the buyer's client can't tell. The chain can. Every check here reads public chain data only. Nothing was signed and nothing was paid.

## Findings

1. **1,040 of the 77,909 payment options checked can't receive a payment (1.3%).** They are listed by 151 of 3,257 hosts (4.6%). The Bazaar listed 89,030 options on 35,894 resources; 77,909 (87.5%) were on a network and scheme this census checks.

2. **Most broken options sit next to a working one, so whether a buyer can pay depends on its client.** 971 resources list a broken option beside one that works, and 11 of the 973 resources with a broken option list it first. A buyer that can only pay on that network, or whose client takes the first option it supports, fails; another buyer pays the same resource without trouble. 2 resources have no checked option that works at all.

3. **Why they can't receive:**

- **806 options on 139 hosts:** the seller's Solana wallet has no account for that token, and the payment will not create one.
- **132 options on 4 hosts:** the token has no transferWithAuthorization, the transfer method the option asks for.
- **90 options on 6 hosts:** the signing name or version differs from the token's own, so every signature fails.
- **10 options on 1 host:** the signing name or version is missing, so the official client refuses to sign.
- **1 option on 1 host:** the payTo is the zero address.
- **1 option on 1 host:** Permit2 or the x402 Permit2 proxy is not deployed on that chain.

4. **The largest cases:**

- emc2ai.io on solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp: 199 options, the seller's Solana wallet has no account for that token, and the payment will not create one. The account the payment would go to, AGPbCGUgcyo161EmHcS5LQscadvdkYSQP6P9Y8K5njWA, does not exist.
- saylorinnovations.com on solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp: 85 options, the seller's Solana wallet has no account for that token, and the payment will not create one. The account the payment would go to, 7d7Y7HwG8TuFRXdKfX6NS7pCeTeGx5hvSx31bfk8iGNC, does not exist.
- archtools.dev on eip155:137: 52 options, the token has no transferWithAuthorization, the transfer method the option asks for.
- archtools.dev on eip155:8453: 52 options, the token has no transferWithAuthorization, the transfer method the option asks for.
- api.carbon-cashmere.de on eip155:480: 43 options, the signing name or version differs from the token's own, so every signature fails. The listing says to sign for "USD Coin"; the token signs as "USDC".
- rengi.dev on solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp: 36 options, the seller's Solana wallet has no account for that token, and the payment will not create one. The account the payment would go to, 9CtEpXNo9FCUYYaLMns6bb2w3opVcTozZ4or1ic4tTNz, does not exist.
- toolrail.dev on solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp: 30 options, the seller's Solana wallet has no account for that token, and the payment will not create one. The account the payment would go to, 5unEv3aJkiw672Q2cy1Q2PyNWyhdtQVdLkzbMxovRSqP, does not exist.
- x402.swaphunt.dev on solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp: 24 options, the seller's Solana wallet has no account for that token, and the payment will not create one. The account the payment would go to, FWocuLXPgBn4V3M5XnPb2rZ1vTXsY3xjU5qJXFEHxDzu, does not exist.

## How to check one yourself

- All of them at once: `python recheck_settlement.py settlement/settlement_2026-11-18.json` reads the chain again for every failing verdict, independently of the script that made it.
- A signing mismatch: call DOMAIN_SEPARATOR() on the token at the pinned block and compare it with the signing domain built from the listing's extra.name, extra.version, the chain id and the token address.
- A missing Solana account: derive the associated token account from the payTo and the mint, and call getAccountInfo on it. Null means the account does not exist.

settlement_2026-11-18.json beside this file has every failing option with its evidence, the block or slot it was read at, and the RPC that answered.

## What this does not show

- It reads the Bazaar's listing, not each seller's live payment challenge. A seller can serve different terms live.
- A receivable option passed every check here. That is not proof a payment would settle: a facilitator can still refuse it for reasons the chain does not show.
- 11,121 options were not checked: other schemes and transfer methods, networks without a public RPC, and XRPL, Stellar, Algorand and other networks. The JSON counts each reason.

## Reproduce

```
python settlement.py --out-dir settlement
```

The listing changes daily, so a rerun reads a newer one; every failing verdict above can be rechecked against the chain at the block or slot recorded beside it.
