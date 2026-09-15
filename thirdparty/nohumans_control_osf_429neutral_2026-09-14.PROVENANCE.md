# nohumans.directory osf control, re-cut with HTTP 429 treated as neutral

Source:    https://nohumans.directory/state/controls/osf-429neutral.csv
Retrieved: 2026-09-14
Publisher: jalcodev (nohumans.directory), published after tracing a class of his own
           "endpoint failed" rows to his scanner's request rate. Sits BESIDE
           nohumans_control_osf_2026-09-13.csv rather than replacing it: he published the
           re-cut as its own file rather than as a corrected number, so both rules are
           readable side by side.
Shape:     day, host, passes, probes, probes_429, share_old, share_429_neutral.
           share_429_neutral = passes / (probes - probes_429).

WHAT WE VERIFIED BEFORE USING IT (all from the file itself, nothing taken on trust):
  - 31 rows, 2026-08-08..2026-09-07, matching the original file's window exactly.
  - share_old reproduces passes/probes on every row, and equals the share published in
    nohumans_control_osf_2026-09-13.csv on every row. The re-cut did not quietly move the
    original numbers.
  - share_429_neutral reproduces passes/(probes - probes_429) on every row.
  - 08-26: 181 passes, 556 probes, 57 of them 429 -> 499 non-neutral, 36.3%, as he stated.
  - The other 18 mixed days read 0.9621 to 1.0000 under the new rule, 9 of them exactly 1.00.
  - His timeout decomposition reproduces from probes - passes - probes_429: 358 inside the
    19 mixed days, of which 318 on 08-26 and 40 scattered across nine days between 08-11 and
    08-23 at 1 to 13 a day. The five days we had asked about (08-08, 08-09, 08-10, 08-24,
    08-25) carry zero, so his 18/1 split stands and our arithmetic objection is withdrawn.
  - One residual we could not reproduce: the all-fail tail's probes - passes - probes_429 is
    1,168 against the 1,144 implied by his stated 1,502 total. That residual counts every
    non-pass, non-429 outcome, so it is an upper bound on timeouts; 24 of the tail's failures
    were evidently something other than a timeout. It does not touch the mixed window, where
    the decomposition is exact.

HIS OWN CAVEAT, carried here so nobody cites past it: 32 of the 181 passes on 08-26 are the
  sample route answering HTTP 200 (`warn:paid_but_open`), which counted as a pass under his
  rule that day. They are not payment challenges, and this census would record a 200 as
  not-gated, so a challenge-only reading of 08-26 is 149/499 = 29.9 percent. We apply that
  only to 08-26, because the pass composition of the other days was not published.
  He also reports that the 429s were served on the SAMPLE URL rather than the paid route.
  The URL this census probes for this host is the sample route,
  https://api.osf-master-server.com/x402/sample/:record_id, unchanged on all 37 days.

NOT OURS. Never edit. Any number derived from these columns is theirs and is labelled theirs.
