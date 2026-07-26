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

## Discovery — are the two approaches competing, or complementary?

x402 discovery is currently argued as standalone `/.well-known/x402` manifest **vs**
extending an existing OpenAPI document. Mostly on design merits. So: for all 1,120 Bazaar
hosts, does each one *also* serve its own manifest?

| | hosts | share |
|---|---:|---:|
| in the Bazaar **and** self-publishing a manifest | 654 | 58.4% |
| registry-only, no manifest of their own | 414 | 37.0% |
| 200 but not JSON (SPA catch-all, not a manifest) | 27 | 2.4% |
| unreachable | 25 | 2.2% |

**Most sellers do both.** The framing as a choice is largely false in practice — 58% hedge
and publish either way. That's an argument for making the two describe the same thing well,
rather than for picking a winner.

### But the manifests can't be relied on for version negotiation

Of those 654 live manifests:

| `x402Version` | count |
|---|---:|
| **absent entirely** | **407 (62.2%)** |
| `2` (int) | 226 |
| `1` (int) | 20 |
| `"1"` (**string**) | 1 |

Nearly two thirds declare no version at all, and among those that do, the field isn't even
consistently typed — one seller emits a string where twenty emit an integer. A consumer
cannot use this field to decide how to talk to a seller.

That matters more than it looks, because v1 and v2 do not degrade into each other: v1 puts
the challenge in the response body, v2 in the `PAYMENT-REQUIRED` header. A client that
guesses wrong doesn't get a downgrade, it gets nothing. Any discovery schema that ships
should make version **explicit, required, and typed** — and rejections should name the
offending field, which is a separate failure mode entirely.

### The reverse direction

Spot-checking sellers active in the x402 Foundation Domain Discovery working group, several
who publish their own manifest are **not in the Bazaar at all**. So the gap runs both ways,
and no single registry is a census. Any adoption number sourced from one registry should say
which one.

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
