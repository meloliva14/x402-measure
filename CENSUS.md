# x402 conformance census

What fraction of the live x402 network a spec-current buyer can actually pay.

Every number here comes from `preflight.py` run against the host list in `sweep_results.json`,
and every one is reproducible with the scripts in this repo. No estimates, no modelling.

Swept 2026-08-01. **1,521 hosts.**

## Headline

| | hosts | share |
|---|---:|---:|
| Fully conformant (`OK`) | 1,262 | 83.0% |
| Not payment-gated right now (`NO_402`) | 124 | 8.2% |
| Still speaking x402 **v1** | 96 | 6.3% |
| Unreachable | 18 | 1.2% |
| Non-EVM (different signer, not assessed) | 15 | 1.0% |
| Malformed challenge (`BLOCKED`) | 4 | 0.3% |
| Unknown network | 2 | 0.1% |

Of the **1,379** endpoints that were actually payment-gated at sweep time, **1,262 (91.5%)**
are fully conformant.

That is the honest headline, and it is a good one for the ecosystem. The interesting part is
the tail.

## The finding: 92 sellers a v2-only buyer cannot pay

**92 live, payment-gated endpoints return their challenge in the response body with no
`PAYMENT-REQUIRED` header at all.**

A v2 client reads the header. There is nothing in it. It does not fall back to sniffing the
body, because a body challenge is not where v2 says the challenge lives. So the buyer sees an
endpoint that will not tell it the price, and moves on.

These sellers are not broken and not idle. They are earning right now, from v1 buyers. The
exposure is that they go dark the moment a buyer upgrades, and they have no way to find out
except by watching revenue fall.

Same 92 hosts, the two other v1 markers:

- 93 use `maxAmountRequired` rather than v2's `amount`
- 92 send `network="base"`, which is v1 naming; v2 uses CAIP-2 (`eip155:8453`)

### What it is worth

Cross-referencing those hosts against the payTo wallets in `paytos.json` and the on-chain
receipts in `demand_results.json`:

- 92 invisible-to-v2 hosts
- 35 have a payTo wallet we can identify
- 18 of those wallets have measured on-chain receipts
- those 18 have taken **$321.95 across 1,594 payments**

State that last number carefully. It is a **floor on a subset**: only 35 of 92 hosts resolve to
a wallet we hold, and only 18 of those wallets show receipts in the measured window. It is not
the revenue of all 92, and it is not annualised.

It is also worth saying plainly what the size of it means. $321.95 across 18 sellers is not a
rounding error in someone's quarter — it is the whole thing. The x402 seller economy is small
today. Anyone quoting this census as evidence of a large stranded market is misreading it.

## Method, and what this does not catch

`preflight.py` fetches each endpoint, reads the 402 challenge from the header and the body,
and classifies. It calls something conformant only when it can read a v2-shaped challenge; it
never infers one.

Known limits, all of which move the non-conformant count **down**, so treat the 91.5% as
generous rather than harsh:

- A host that was down at sweep time lands in `UNREACHABLE`, not in a defect bucket.
- `NO_402` means the endpoint was not payment-gated *at that moment*. Some are gated on other
  routes, or gate conditionally.
- Non-EVM chains are excluded rather than judged. A Solana endpoint is not assessed here.
- One sweep is one point in time. Hosts change.

## Reproducing it

```
python preflight.py            # classify every host in sweep_results.json
python demand_sweep.py         # on-chain receipts per payTo wallet
python circularity.py          # per-seller funding edges (see the caveats in that file)
```

Public RPC only, read-only, no keys.
