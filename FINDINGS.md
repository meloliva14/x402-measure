# Findings

A run of the scripts in this repo. **Snapshot of 2026-07-26**, complete sweep
(14,365 of 14,365 listings). Aggregate only; per-wallet revenue is not published.

Reproduce with:

```bash
python harvest_bazaar.py     # writes harvest_meta.json with provenance
python live_402_sweep.py
python manifest_probe.py
python demand_sweep.py 7
```

**Numbers here are a timestamped snapshot, not a constant.** See
[Method and its limits](#method-and-its-limits) — the registry is live, and any two sweeps
return slightly different slices of it. Every figure below should be read with its date
attached. `harvest_meta.json` records the provenance of whatever run produced your copy.

---

## Sample

- **14,365** resources listed in the CDP x402 Bazaar (registry-reported total: 14,365 — complete)
- **1,521** distinct hosts
- **1,020** distinct EVM payTo wallets advertised by those hosts

---

## Supply — can these endpoints take money?

One live request per host.

| verdict | hosts | share |
|---|---:|---:|
| clean v2 402, signable by a stock client | 1,262 | 83.0% |
| no longer returns a 402 | 124 | 8.2% |
| still x402 v1 | 96 | 6.3% |
| unreachable | 18 | 1.2% |
| non-EVM (not assessed) | 15 | 1.0% |
| v2 challenge a stock client can't sign | 4 | 0.3% |
| unrecognised network id | 2 | 0.1% |

**The challenge layer is mostly healthy.** 83% of listed sellers can accept a payment from a
standard client today. Only 4 hosts serve a v2 challenge a reference buyer cannot construct a
payment from — that failure mode is real but rare.

---

## Discovery — are the two approaches competing, or complementary?

x402 discovery is argued as standalone `/.well-known/x402` manifest **vs** extending an
existing OpenAPI document. So: for all 1,521 hosts, does each also serve its own manifest?

| | hosts | share |
|---|---:|---:|
| in the Bazaar **and** self-publishing a manifest | 885 | 58.2% |
| registry-only, no manifest of their own | 636 | 41.8% |
| 200 but not JSON (SPA catch-all, not a manifest) | 41 | 2.7% |
| unreachable | 25 | 1.6% |

**Most sellers do both.** The framing as a choice is largely false in practice — 58% publish
either way. That argues for making the two describe the same thing well rather than for
picking a winner.

### But the manifests can't be relied on for version negotiation

Of those 885 live manifests:

| `x402Version` | count |
|---|---:|
| **absent entirely** | **557 (62.9%)** |
| `2` | 301 |
| `1` | 27 |

Nearly two thirds declare no version at all. Type inconsistency also occurs in the wild —
`scrape402.xyz` serves `"1"` as a JSON **string** where others emit an integer — so a consumer
cannot compare this field without coercing it first.

That matters because v1 and v2 do not degrade into each other: v1 puts the challenge in the
response body, v2 in the `PAYMENT-REQUIRED` header. A client that guesses wrong doesn't get a
downgrade, it gets nothing. Any discovery schema that ships should make version **explicit,
required, and typed** — and rejections should name the offending field.

### Receipt extensions are near-nonexistent

| extension | hosts | listings |
|---|---:|---:|
| `bazaar` | 1,521 | 14,365 |
| `builder-code` | 187 | 2,612 |
| `payment-identifier` | 17 | 230 |
| `offer-receipt` | **12** | 278 |
| `otto-content-receipt` | 2 | 46 |

`offer-receipt` — the approved v0.6 extension — is advertised by 12 hosts, and those 12
collapse to **six root domains** (forgemesh.io ×6, coinopai.com ×2, carbon-cashmere.de,
nodeflare.app, ottoai.services, x402swag.com). Under 1% of the registry, and effectively six
operators.

---

## Demand — who actually got paid?

Every USDC transfer into all 1,020 wallets on Base, 7 days, full block coverage
(302,401 of 302,401 blocks), no sampling.

- **1,277,221** payments
- **658** wallets paid at least once (64.5%)
- **362** wallets received nothing (35.5%)

### Concentration is the whole story

- One host accounts for **85% of every payment on the network** (1,088,620 of 1,277,221)
- The top wallet is **62%** of all value; the top five are **94%**

### Distribution

| | |
|---|---:|
| median seller, 7 days | **$0.05** |
| median *paid* seller, 7 days | $0.27 |
| earned under $1 | 79.9% |
| earned under $10 | 93.4% |
| earned under $100 | 97.6% |
| median distinct payers, per paid wallet | **2** |
| paid wallets with exactly one payer | **190** |

---

## Method and its limits

Stated up front rather than waiting to be asked.

**Two sampling hazards, both measured directly:**

1. **A short page is not the end of the data.** The Bazaar API emits pages shorter than
   `limit` mid-run. Treating one as end-of-data truncates a sweep silently while it still
   reports success. `harvest_bazaar.py` now ends only on an empty batch or on reaching the
   registry-reported `total`, warns loudly if it falls short, and records completeness in
   `harvest_meta.json`.

2. **Even a complete sweep is a snapshot, not an enumeration.** Offset pagination over a
   registry that changes while you page it cannot guarantee coverage — rows shift across page
   boundaries between requests. Measured: 13 hosts present in one sweep were absent from a
   complete sweep the following day while still serving live manifests. Consequence: two
   correct runs return different slices. Quote the timestamp with any figure, keep prior runs,
   and prefer a union across runs for "does X exist anywhere" questions rather than "what
   share of the registry is X".

**Other limits:**

- **One payTo per seller is assumed.** Anyone rotating wallets is undercounted.
- **These wallets can receive non-x402 USDC too.** The largest averages ~$127 per payment —
  retail-sized, not agent-sized — so it is near-certainly carrying ordinary commerce through
  the same address. Payment *counts* and the *median* don't have this problem, which is why
  the headline figures lead with those. `demand_sweep.py` prints the largest wallet's average
  payment size so you can judge it yourself.
- **The Bazaar is one registry, not the whole network.** Sellers publishing only their own
  `/.well-known/x402` aren't in this sample, and spot checks suggest that population isn't
  small. This is the state of a named, reproducible sample — not "the state of x402".
- **One to three requests per host, once a day.** A GET, then a POST if the GET produced no
  challenge, then one retry after a transport failure. These scripts are not a crawler. This
  bullet said one request until 2026-09-13; that was wrong, and it mattered the day the census
  was laid beside an intraday instrument. The sweep is also one window of about three minutes
  per day, at whatever time the scheduler delivers the 04:17 UTC job (so far from 02:52 to
  15:16 UTC; most days either 04:24 to 05:47 or 08:22 to 10:53), so a daily verdict is a
  fixed-time sample, not a uniform draw over the day. Each day's manifest records
  sweep_started_utc and sweep_ended_utc, and from schema /3 every row records which verb
  answered, how many requests it took, and when.
- **An HTTP 429 is recorded `RATE_LIMITED`, never "not payment-gated."** A rate-limit response
  is a fact about the conversation, not about whether the endpoint sells anything, and from
  2026-09-13 a 429 on the GET also stops the POST fallback rather than asking a complaining
  host twice. Before that date it was filed `NO_402`: 39 host-days on two hosts, and both
  served a readable 402 on the days their 429 lifted, so the label was contradicted by this
  census itself. Signed snapshots are never rewritten, so those rows still read `NO_402` and
  carry the status in the note; `rate_limited_history.py` lists every one of them and derived
  scripts read the status rather than the label.
- **A route template in a pinned URL is not a closed shop.** 68 of the 1,521 pinned URLs carry
  an Express-style path segment (`/:id`), and 31 of those hosts served a 402 on that literal
  path on some day, because plenty of servers gate payment before they route. So a template
  alone is not an artifact. The uninformative class is templated *and* never answered with a
  challenge on any day, and 32 such hosts sit inside the count of hosts with a
  14-consecutive-day `NO_402` run (`notgated_runs.py`). Over 2026-08-08..09-14 that count reads
  171 as published and 139 with those 32 set aside; over 2026-08-08..09-19, 182 and 150. If
  origin failures are excluded as well, the same two windows read 156 and 124, then 162 and
  130. 21 of the 37 templated hosts that never served a challenge returned 404 on every one of
  their no-402 days. "No challenge was served" stays true for all 32 of them; "this host
  stopped charging" does not follow. `templated_routes.py` (commit `8b5513d`) prints the split
  and the per-host detail on the same 429-neutral basis the published census uses. Recorded
  2026-09-20.
- **Nothing is signed and no payment is ever sent.**

---

## What this suggests

The plumbing works. 83% of listed sellers can accept a payment from a standard client today.
What's missing is buyers — and the demand that does exist is concentrated to the point where a
single participant leaving would change the network's totals.

For an individual seller staring at zero settlements, two things are worth separating: whether
anyone tried and couldn't pay (`preflight.py` answers that in seconds, for free), and whether
anyone tried at all. They look identical in a funnel and have completely different fixes.
