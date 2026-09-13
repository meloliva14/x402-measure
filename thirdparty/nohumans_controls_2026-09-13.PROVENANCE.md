# nohumans.directory control files, two hosts

Source:    https://nohumans.directory/state/controls/onesource.csv
           https://nohumans.directory/state/controls/osf.csv
Retrieved: 2026-09-13
Publisher: jalcodev (nohumans.directory), published after the 2026-09-13 exchange in the x402
           Slack #wg-domain-discovery thread "v1 challenges are still live".
Shape:     day, host, state (all_402 | all_fail | mixed), share_402.
           PROBE COUNTS ARE DELIBERATELY OMITTED. His words: the state and the share are what the
           comparator needs, and the counts describe his scheduler rather than the endpoint.
Selection: both hosts chosen on OUR stated criterion, then picked from hosts he has PAID, which
           is the one dimension our census cannot see.
His own caveats, carried here so nobody cites past them:
  api.onesource.io        - the generalisation control. Sole host on its domain. He says the
                            window is 30 days (08-09 to 09-07) because it was first listed on
                            the morning of the 9th. Its "mixed" days sit at 96 to 99.9 percent.
  api.osf-master-server.com - the power control. He says the shape is a DECLINE, not a flap:
                            high, falling, then twelve consecutive all-fail days. Not a genuine
                            flapper, and he had not found one he also pays from.
RETRACTION BY THE PUBLISHER, same day, after we had run the files. He reports that osf's 19
  "mixed" days are an artefact of his own scanner: 3,008 of the probes in that window returned
  HTTP 429 and 1,500 returned no status at all, which he attributes to his request rate rather
  than to the endpoint, and he places the genuine outage at 2026-08-27. He also reports the
  mechanism is not confined to osf (a 429 counted toward a fail streak, and his scheduler gave
  failing listings priority) and says he is publishing a correction and a per-host request cap.
  ALL OF THAT IS HIS ACCOUNT OF HIS OWN INSTRUMENT. We cannot verify it and do not assert it.
  What our own rows say, independently: a readable 402 on all 19 of those days with no retry,
  and UNREACHABLE on both attempts every day from 08-27 through 09-13.
  The CSVs are left exactly as published. The osf file should not now be cited as evidence
  about that endpoint's intraday behaviour before 08-27.

NOT OURS. Never edit. Any number derived from these is theirs and is labelled theirs.
