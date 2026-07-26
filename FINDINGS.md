# Findings — 2026-07-25

One run of the scripts in this repo. Aggregate only; per-wallet revenue is not published.

Reproduce with:

```bash
python harvest_bazaar.py
python live_402_sweep.py
python demand_sweep.py 7
```

Numbers will drift. The method won't.

---

## Sample

- **14,335** resources listed in the CDP x402 Bazaar
- **1,120** distinct hosts
- **695** distinct EVM payTo wallets advertised by those hosts

---

## Supply — can these endpoints take money?

One live request per host.

| verdict | hosts | share |
|---|---:|---:|
| clean v2 402, signable by a stock client | 934 | 83.4% |
| no longer returns a 402 | 110 | 9.8% |
| still x402 v1 | 42 | 3.8% |
| unreachable | 16 | 1.4% |
| non-EVM (not assessed) | 15 | 1.3% |
| 402 with no `accepts[]` | 3 | 0.3% |

**The challenge layer is mostly healthy.** I expected it to be a mess and it isn't. Going
in I assumed a missing `extra` block would be widespread; only **15 of 1,120** hosts
advertise a challenge lacking `extra.name`. It's a real failure mode, but it's an outlier,
not a pattern — worth stating because I had it backwards before measuring.

---

## Demand — who actually got paid?

Every USDC transfer into all 695 wallets on Base, 7 days, full block coverage
(302,401 of 302,401 blocks), no sampling.

- **1,252,631** payments
- **545** wallets paid at least once
- **150** wallets received nothing

### Concentration is the whole story

- One host accounts for **84.8% of every payment on the network**
- The top wallet is **67%** of all value; the top five are **95%**
- Outside the top two, the entire rest of the network is roughly **$3,900/day across 543 sellers**

### Distribution

| | |
|---|---:|
| median seller, 7 days | **$0.13** |
| earned under $1 | 71.7% |
| earned under $10 | 90.4% |
| earned under $100 | 97.0% |
| median distinct payers, per paid wallet | **2** |
| paid wallets with exactly one payer | **176** |

---

## Caveats

Stated up front rather than waiting to be asked:

1. **One payTo per seller is assumed.** Rotating wallets are undercounted.
2. **The dollar total is the softest number here.** The largest wallet averages ~$119 per
   payment — retail-sized, not agent-sized — so it is near-certainly carrying ordinary
   commerce through the same address. Payment *counts* and the *median* don't have this
   problem, which is why the headline figures above lead with those.
3. **The Bazaar is one registry.** Sellers publishing only their own
   `/.well-known/x402` manifest aren't in this sample, and spot checks suggest the two
   populations overlap far less than expected. This is the state of a named sample, not
   "the state of x402."

---

## What this suggests

The plumbing works. 83% of listed sellers can accept a payment from a standard client
today. What's missing is buyers — and the demand that does exist is concentrated to the
point where a single participant leaving would change the network's totals.

For an individual seller staring at zero settlements, two things are worth separating:
whether anyone tried and couldn't pay (`preflight.py` answers that in seconds, for free),
and whether anyone tried at all. They look identical in a funnel and have completely
different fixes.
