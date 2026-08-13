# Where each sweep was run from

A verdict from a single vantage is partly a fact about the vantage. A host behind a WAF that
holds per-IP state can answer one prober and refuse another on the same morning, so `UNREACHABLE`
can describe the observer rather than the observed. That is why this is recorded at all.

From **2026-08-13** the class is a field inside every `observation.json`, under
`manifest.vantage`. The five files before that predate the field, and they are signed and
append-only, so they are not edited retroactively. Their vantage is recorded here instead.

| snapshot | vantage class | how it ran |
|---|---|---|
| 2026-08-08 | `residential` | run by hand from a home connection |
| 2026-08-09 | `ci-runner` | GitHub-hosted runner (`workflow_dispatch`) |
| 2026-08-10 | `ci-runner` | GitHub-hosted runner (scheduled) |
| 2026-08-11 | `ci-runner` | GitHub-hosted runner (scheduled) |
| 2026-08-12 | `ci-runner` | GitHub-hosted runner (scheduled) |

**The series therefore contains one vantage change, between day one and day two.** Any comparison
that spans 2026-08-08 to 2026-08-09 crosses it. The flip rate originally published for that pair
was withdrawn for a different reason (the two sweeps ran 2h17m apart, not 24h); the vantage change
is a second, independent reason that pair should not have been used.

## Category only, never an address

`vantage.class` is a closed vocabulary: `residential`, `datacenter`, `ci-runner`, `vpn`, `mobile`,
`unspecified`.

No IP, hostname, ISP, or city is recorded here or in any snapshot. The whole analytic value is in
the residential-versus-datacenter axis, which is what a two-observer diff measures. An actual
address would add nothing to that and would permanently tie an individual's home connection to
sweeping activity. A closed vocabulary is deliberate: a free-text field eventually becomes an
identifier by accident.
