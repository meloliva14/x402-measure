# Can an agent learn how to pay you by reading your manifest?

Mostly, no. `/.well-known/x402.json` is a convention with no agreed schema, and four fifths of
the hosts that publish one do not publish enough to pay from.

Swept 2026-08-02. **1,521 hosts**, one GET each. Reproduce with `python manifests.py`.

## Headline

| | hosts |
|---|---:|
| Serve a manifest at all | **544** / 1,521 |
| Publish enough to construct a payment | **116** |
| Some payment fields, still unsignable | 165 |
| No payment terms at all | 263 |

**21.3% of manifest-serving hosts publish enough for a buyer to build a payment.**

## What "enough" means

To construct an x402 `exact` payment a buyer needs four things it cannot guess:

| field | why |
|---|---|
| `network` | which chain to sign for, ideally CAIP-2 |
| `asset` | the token **contract**. `"USDC"` is not an address and cannot be signed. |
| `amount` | how much, in atomic units |
| `payTo` | who receives it |

Scoring is all-or-nothing on purpose. A manifest naming three of the four is not 75% payable,
it is unpayable.

What the 165 partial manifests are missing, by field:

| missing | hosts |
|---|---:|
| `asset` | 158 |
| `payTo` | 135 |
| `network` | 65 |
| `amount` | 47 |

`asset` leads, and the common failure inside it is a populated, useless value: a ticker where a
contract belongs. It reads fine to a human reviewing the JSON, which is exactly why it survives
review.

## There is no schema. There are ten.

Every family below is somebody's independent invention of the same document:

| shape | hosts |
|---|---:|
| `x402Version` + `resources` | 281 |
| `version` + `resources` | 74 |
| `version` + `endpoints` | 58 |
| `x402Version` + `endpoints` | 41 |
| `x402Version` + no container | 18 |
| no version + `resources` | 16 |
| `x402Version` + `accepts` | 11 |
| no version + `routes` | 9 |
| no version + `endpoints` | 8 |
| no version + `services` | 8 |

Some spell the version field `x402Version`, some `version`, 41 omit it entirely. The payment
terms live under `resources`, `endpoints`, `services`, `routes`, `accepts`, or directly on the
object. A cataloguer cannot write one parser for this, which is most of the reason nobody has.

## We found this by shipping it

On 2026-08-02 `api.veritylayer.dev` advertised this in its own manifest:

```json
{"scheme": "exact", "network": "eip155:8453", "asset": "USDC", "payTo": "0x89d3…", "price": "0.02"}
```

while its live 402 header demanded:

```json
{"scheme": "exact", "network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
 "amount": "20000", "payTo": "0x89d3…", "maxTimeoutSeconds": 300,
 "extra": {"name": "USD Coin", "version": "2"}}
```

A buyer building from our manifest could not have signed anything: `asset` was a ticker, and
`price` is not a field in the x402 spec at any version (v2 uses `amount`, v1 used
`maxAmountRequired`). Fixed the same day; the manifest is now derived from the same
`NETWORK_CONFIGS` the middleware reads, so it cannot drift again without the middleware drifting
with it.

We publish a conformance census that marks other hosts `BLOCKED` for this class of defect. It
was on our own listing, and `preflight.py` could not see it, because that census reads the 402
and never reads the manifest. `manifests.py` exists to close that hole.

## What this does NOT say

A manifest without payment terms is **not a broken service**. Almost every host here is
perfectly payable by an agent doing the normal thing: call the endpoint, read the 402, pay. That
is what the spec actually requires, and it works.

The finding is narrower, and should always be quoted narrowly: **discovery-by-manifest does not
work on this network.** A cataloguer, an indexer, or a buyer that wants to survey before
spending has nothing machine-readable to read. Anyone citing this as "N hosts are broken" is
misreading it.

Other limits, stated because a silent one would overstate the result:

- One GET per host at one moment. Hosts change.
- Only `/.well-known/x402.json`. A host publishing terms somewhere else is counted as not
  serving one.
- Hosts we could not parse are reported as unparsed, never scored as clean.
- TLS verification is disabled deliberately. A cert error is not the question, and refusing
  those hosts would bias the census toward well-run infrastructure.

## Check your own

`https://veritylayer.dev` has a free checker: paste a paid URL and it reads the 402 the way a
spec-current buyer would, compares it against your manifest, and hands you the curl command that
reproduces whatever it found. No wallet, no signup, no model in the path.
