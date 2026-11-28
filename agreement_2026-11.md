# Where x402 measurements agree, and where they don't

November 2026

At least ten groups now publish numbers about x402 sellers, mine included. Read side by side, the headlines seem to contradict each other. The market is 1,225 sellers, or 405,664 endpoints. A sixth of it is dead, or nearly two thirds is. A call costs half a cent, or two cents.

I lined up every figure I could trace to a public page and checked what each one actually counts. Most of the gap comes from definitions, not from anyone getting it wrong. Every figure below is as its publisher printed it, on the date shown. I didn't recompute anyone else's numbers.

I run one of these measurements myself, a daily signed census in meloliva14/x402-measure, so I'm not neutral. My own figures are recomputed from one signed snapshot (2026-11-16) by a script anyone can run, and where it helps I show them under the other publishers' definitions instead of mine. x402 List's guide "Why x402 Numbers Differ" covers this problem for payment volume. This covers the seller side: size, health and price.

## 1. How big is x402?

| Figure | What is counted | Source, date |
|---|---|---|
| 1,225 | sellers in the x402 Bazaar | ForgeMesh, Aug 19 |
| 1,343 | services listed in a directory (1,230 answering) | x402 List, Nov 17 |
| 1,521 | hosts in a Bazaar list I pinned on Jul 26 | my census, Nov 16 |
| 2,280 hosts, 31,620 URLs | resource URLs in the CDP Bazaar | Low Key Builds, Oct 13 |
| 3,218 hosts, 33,324 listings | listings in the CDP Bazaar | Tanod price index, Nov 16 |
| 17,533 | registered endpoints in the CDP catalog | Stelar Digital, Sep 27 |
| 48,541 | x402 endpoints in its index | 402 Index, Nov 17 |
| 175,450 | endpoints tracked | Settled, as reported by minia2a, Nov 14 |
| 405,664 listed, 241,233 active | endpoints merged from x402scan, the Bazaar, thirdweb, PayAI and others | x402 Trust, Nov 17 |

**Where they agree:** counted by host or seller, every source lands between 1,225 and 3,218. The jump to hundreds of thousands comes from counting URLs instead of hosts, and from merging several catalogs into one.

**Why a date matters:** the Bazaar itself moves fast. Tanod's daily file shows 46,352 listings on Oct 18, 25,790 the next day, and 79,456 on Oct 27. A size figure without its unit and its date can't be compared with anything.

## 2. How much of it is broken?

| Figure | What counts as broken | Out of | Source, date |
|---|---|---|---|
| 17% | the listed URL returns 404 | 1,225 sellers, one URL each | ForgeMesh, Aug 19 |
| a quarter | no reachable, correct 402 with a payment envelope | same | ForgeMesh, Aug 19 |
| 43.4% on Oct 12, 32.1% on Oct 26, 2.7% on Nov 2 | marked down by 402 Index, read weekly. The 2.7% came after the index was pruned from 196,373 to 43,907 endpoints | endpoints | Feldspar, Oct 12 to Nov 2 |
| 0 | a 404 or unreachable, on one unpaid GET with a 15 s timeout. 94 answered 402, counted by status code only, not checked against the x402 schema. 3 needed input and 3 template rows got no reply | 100 rows of the PayAI facilitator discovery list | CSOAI, Oct 24 |
| 1,157 down, 12,460 unknown | marked down or not yet known | 52,572 endpoints across L402, x402 and MPP | 402 Index, Nov 17 |
| 61% | do not answer at all | 175,331 probed endpoints | Settled, as reported by minia2a, Nov 14 |
| 36% reachable | not reachable | 241,233 active endpoints | x402 Trust, Nov 17 |

Mine, for the same 1,521 hosts on Nov 16, four ways:

| Definition of broken | Hosts | Share |
|---|---|---|
| answered 404 | 96 | 6.3% |
| no response at all | 171 | 11.2% |
| answered 404 or 410 | 179 | 11.8% |
| served no payment challenge of any kind | 470 | 30.9% |

**Where they agree:** on one signed day my own figure runs from 6.3% to 30.9% just by changing what "broken" means. That spread is about as wide as the disagreement between publishers. The denominator matters as much. Counting endpoints gives a host that lists thousands of URLs thousands of votes, and "listed" against "active" differs by 164,431 endpoints at x402 Trust alone.

**None of these figures involve paying.** The one large paid test I found is Lumière PayCheck, which paid endpoints 45,152 times from Sep 27 to Nov 7. On each endpoint's latest graded paid test, 95.1% of 31,546 endpoints delivered. Across all attempts, though, 49.1% of 126,291 ended before any data came back because the payment didn't complete. 86.1% of those were the endpoint asking for payment again after being paid. That's a different question from every figure above, and it's the one a buyer cares about most.

## 3. Header or body?

ForgeMesh's first pass read only response bodies and "flagged nearly half the catalog as broken". The terms were in the PAYMENT-REQUIRED header, and their published figures accept either place. My Nov 16 snapshot shows how big that trap is. Of the 950 hosts a stock v2 client could pay, 462 (48.6%) carried no payment terms in the body at all. A measurement that reads only the body would call about half of those working sellers broken.

## 4. What does a call cost?

| Figure | What is measured | Over | Source, date |
|---|---|---|---|
| $0.02 | median price quoted in a live 402, Base USDC, one figure per host | 934 hosts | my census, Nov 16 |
| $0.01 | median listed price, one figure per listing | CDP Bazaar listings | Tanod price index, Oct 27 |
| $0.005 | same measure, three weeks later | 33,324 listings | Tanod price index, Nov 16 |
| $0.01 | median price, unit not stated | directory services | x402 List, Nov 17 |
| 0.87¢ | average amount actually paid per call | 45,152 payments | Lumière PayCheck, Sep 27 to Nov 7 |
| $0.024 | mean USDC transfer matched to a listed price | 660,013 transfers | Settled, as reported by minia2a, Nov 7 to 13 |

**Where they agree:** most of the gap is per listing against per host. A host that lists thousands of cheap URLs counts thousands of times in a per-listing median and once in mine. Of my 934 hosts, 439 (47%) charge $0.01 or less, so a per-host median lands just above that line, at $0.02. Listed, quoted and paid prices are also three different things. Tanod says plainly that its figures are listed prices, not prices actually paid.

## What would make these comparable

If each publication stated five things, most of these gaps would explain themselves:

1. The unit: host, seller, listing or URL.
2. The population and the date it was taken: which catalog, or which merge of catalogs.
3. The probe: listing data only, an unpaid request, or a paid call.
4. What counts as broken: no response, a 404, no challenge, or a failed payment.
5. Where the payment terms were read: the header, the body or both.

These line up closely with the named check profiles proposed for a Measurement & Trust workstream in x402-foundation/x402#4127.

## Notes

- Every figure was checked against its page on Nov 16 and 17 (UTC). Pages change, so each date is the one the page showed.
- CSOAI's row was added on Nov 28 (UTC), after CSOAI confirmed it on x402-foundation/x402#4127, and checked against its snapshot that day. It uses CSOAI's stated definition. The snapshot's own headline says "correct 402 challenge", which CSOAI notes claims more than its method checked.
- ForgeMesh's census was also cross-posted to dev.to. It's counted once here.
- The Feldspar post says its author works on Lumière PayCheck, so those two aren't independent of each other.
- Every publisher here, me included, runs x402 services or a directory.
- To reproduce my figures: `python agreement_ourside.py 2026-11-16`. It refuses to run unless that day's signature verifies.
- If I've misread your definition, tell me and I'll correct it.

## Sources

- ForgeMesh, x402 Bazaar Health Census: https://forgemesh.io/blog/x402-bazaar-health-census-august-2026
- x402 List, State of x402: https://x402-list.com/state-of-x402 and https://x402-list.com/api/v1/stats
- x402 List, Why x402 Numbers Differ: https://x402-list.com/methodology/why-x402-numbers-differ
- Low Key Builds: https://dev.to/lowkeybuilds/i-crawled-all-31620-x402-bazaar-listings-most-have-one-payer-and-boring-chain-reads-win-5c73
- Tanod price index: https://github.com/tanod-labs/x402-price-index and https://tanod.dev/data/x402-bazaar-stats-history.csv
- Stelar Digital: https://stelardigital.com/state-of-x402
- 402 Index: https://402index.io/
- Settled, as reported by minia2a: https://dev.to/minia2a/175450-endpoints-630-paid-sellers-the-x402-demand-side-measured-25fn
- x402 Trust: https://x402-trust.com/trust/report
- Feldspar: https://dev.to/feldsparaiagent/what-ai-agents-actually-paid-for-on-x402-october-2026-44cf
- Lumière PayCheck: https://dev.to/book0feli/we-paid-x402-endpoints-45152-times-heres-what-we-found-mic
- CSOAI (Council of AI), x402 catalog trust snapshot: https://councilof.ai/interop/x402-trust/20261024T045329Z.json, row confirmed by CSOAI at https://github.com/x402-foundation/x402/issues/4127#issuecomment-7210093608
- My census: https://github.com/meloliva14/x402-measure
