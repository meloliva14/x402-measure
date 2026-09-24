"""Re-check every figure in the discovery spec that a reader would attribute to this census.

WHY THIS EXISTS, stated plainly because the reason is a mistake of mine.

x402#2979 credits this repo in a footnote: "Deployment figures here, and the 1,971-name DNS census
in the TXT section, are from independent measurements by @meloliva14". I audited that section three
times in one day and each time checked the figures I could check quickest:

  1. I verified the operator count, the walk size and the suffix counts, and never rebuilt the
     five-row table between them. minia2auk rebuilt it and found the doc's rows had never matched
     this file (2/1/1/1/2 against 1/3/0/1/2) while the total, 7, was right the whole time.
  2. After the fix landed I read the same section again and still did not rebuild the rows.
  3. I then called the sentence under the table a stale digit without asking what unit it counted.
     Three names, two publishing zones and two distinct record bodies are all true of those rows.

Each miss was the same shape: a spot check over the claims that were easy to reach, in a document
whose every number carries someone's name. A promise to look harder does not fix that. A list does.

WHAT THIS ENFORCES. Every numeric token in the document must be claimed by an entry below. A token
nobody has classified is reported as UNCLASSIFIED and the run fails, so "I did not look at that
one" stops being available. Each entry says which instrument owns the figure:

  OURS            reproducible from an artifact in this repo; the value is recomputed and compared.
  OURS-POSTED     our measurement, published in a dated comment of ours rather than in an artifact.
                  The comment is fetched and must be ours and carry every figure; it passes on that,
                  and the summary still counts it apart, because nothing here re-runs it.
  OURS-UNPUBLISHED  our measurement, published nowhere. Reported, never green.
  THEIRS          another instrument's figure, named, so it is never silently treated as ours.
  PROSE           a structural number (a cap, a section number, a port, an RFC), not a measurement.

BEFORE ANYTHING IS CLASSED OURS-UNPUBLISHED, SEARCH OUR OWN POSTED COMMENTS, not only this repo.
The 260/139 figure was classed unpublished here and said so in the thread, and it had been posted
by us on 2026-08-06 (x402#2979, issuecomment-5199553316), where it is the reason `x402Version`
stayed normative. Taking our word for it, the spec relabelled it "unpublished operator telemetry"
without the credit. Since 3b6d778 the footnote cites that comment, and it is classed OURS-POSTED below.

Read-only. Network: the spec itself from the PR head, and any comment an OURS-POSTED entry cites.

Usage: python spec_audit.py [--pr 2979]
"""
import collections
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
PR = sys.argv[sys.argv.index("--pr") + 1] if "--pr" in sys.argv else "2979"
SNAP = HERE / "snapshots"

# The ten platform boundaries the spec names in its own prose, in its order.
SPEC_TEN = ["vercel.app", "workers.dev", "up.railway.app", "onrender.com", "fly.dev",
            "replit.app", "netlify.app", "run.app", "sslip.io", "nip.io"]
# Platform suffixes this census counts. A name under one of these is its own operator.
OURS_PLATFORM = SPEC_TEN + ["hf.space", "trycloudflare.com", "deno.dev", "herokuapp.com",
                            "pages.dev", "ngrok-free.app", "ngrok.io", "repl.co", "glitch.me",
                            "koyeb.app", "streamlit.app", "modal.run", "azurewebsites.net",
                            "cloudfunctions.net"]


def spec_text():
    pr = json.loads(subprocess.run(["gh", "api", f"repos/x402-foundation/x402/pulls/{PR}"],
                                   capture_output=True, text=True, encoding="utf-8").stdout)
    sha = pr["head"]["sha"]
    repo = pr["head"]["repo"]["full_name"]
    files = json.loads(subprocess.run(["gh", "api", f"repos/x402-foundation/x402/pulls/{PR}/files?per_page=100"],
                                      capture_output=True, text=True, encoding="utf-8").stdout)
    path = [f["filename"] for f in files if f["filename"].endswith("discovery.md")][0]
    url = f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "x402-measure"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8"), sha, path


def pinned_hosts():
    days = sorted(p.name for p in SNAP.iterdir() if p.name[:2] == "20")
    sets = {d: {r["host"] for r in json.loads((SNAP / d / "observation.json").read_text(encoding="utf-8"))["observations"]}
            for d in (days[0], days[-1])}
    assert sets[days[0]] == sets[days[-1]], "the pinned population moved; every count below is date-dependent"
    return sorted(sets[days[-1]]), days[-1]


def platform_class(host, classes):
    for s in classes:
        if host.endswith("." + s):
            return s
    return None


def posted(cid, figures):
    """A figure of ours that lives in a comment: fetch it, and confirm it is ours and carries them."""
    c = json.loads(subprocess.run(["gh", "api", f"repos/x402-foundation/x402/issues/comments/{cid}"],
                                  capture_output=True, text=True, encoding="utf-8").stdout or "{}")
    who, body = (c.get("user") or {}).get("login"), c.get("body") or ""
    found = [n for n in figures if re.search(rf"(?<![\d,.]){n}(?![\d,])", body)]
    return {"ok": who == "meloliva14" and len(found) == len(figures),
            "detail": f"issuecomment-{cid} by {who} on {(c.get('created_at') or '')[:10]} carries "
                      f"{found}; no artifact here re-runs it"}


def facts():
    """Everything this repo can say, recomputed now rather than remembered."""
    hosts, day = pinned_hosts()
    census = json.loads((HERE / "dns_census.json").read_text(encoding="utf-8"))
    spellings = json.loads((HERE / "spellings_2026-08-23.json").read_text(encoding="utf-8"))
    ten = collections.Counter(c for h in hosts if (c := platform_class(h, SPEC_TEN)))
    ours = collections.Counter(c for h in hosts if (c := platform_class(h, OURS_PLATFORM)))
    fleets = collections.Counter(".".join(h.split(".")[-2:]) for h in hosts
                                 if platform_class(h, OURS_PLATFORM) is None)
    record_names = [h["name"] for h in census["hits"]]
    manifests = json.loads((HERE / "manifests.json").read_text(encoding="utf-8"))["results"]
    published = (HERE / "MANIFESTS.md").read_text(encoding="utf-8")
    partial = [r for r in manifests if r.get("payable") == "partial"]
    pmiss = collections.Counter(f for r in partial for f in (r.get("missing") or []))
    # The v=x4021 rows in their own units: names, distinct bodies, and the zones that publish them,
    # read from the live delegation check rather than guessed from the names.
    x4021 = [r for r in spellings["rows"] if r["spelling"] == "v=x4021;descriptor=...;url="][0]
    zone_of = {n: v["enclosing_registrable_domain"] for n, v in spellings["delegation_check"]["names"].items()}
    run_app = [h for h in hosts if platform_class(h, SPEC_TEN) == "run.app"]
    platform_hosts = [h for h in hosts if platform_class(h, OURS_PLATFORM)]
    return {
        "day": day,
        "pinned": len(hosts),
        "census_names": census["queried"],
        "census_counts": census["counts"],
        "records": len(record_names),
        "operators": spellings["units_over_all_records"]["registrable_domains"],
        "rows": {r["spelling"]: r["records"] for r in spellings["rows"]},
        "row_names": {r["spelling"]: r["names"] for r in spellings["rows"]},
        "distinct_bodies": spellings["units_over_all_records"]["distinct_record_bodies"],
        "zones": len(spellings["delegation_check"]["zones_holding_the_records"]),
        "x4021_names": x4021["names"],
        "x4021_bodies": x4021["distinct_record_bodies"],
        "x4021_zones": sorted({zone_of[n] for n in x4021["names"]}),
        "identical_pairs": spellings["names_sharing_a_byte_identical_record"],
        "run_app_all_under_a": bool(run_app) and all(h.endswith(".a.run.app") for h in run_app),
        # what a last-two-labels rule would make of the platform hosts, computed rather than inferred
        "last_two_buckets": len({".".join(h.split(".")[-2:]) for h in platform_hosts}),
        "posted_0806": posted(5199553316, ("260", "139")),
        "ten_class_counts": dict(ten),
        "ten_class_total": sum(ten.values()),
        "our_platform_total": sum(ours.values()),
        "classes_outside_the_ten": {k: v for k, v in ours.items() if k not in SPEC_TEN},
        "fleets_32_plus": {d: n for d, n in fleets.most_common() if n >= 32},
        "records_not_pinned": [n for n in record_names if n not in set(hosts)],
        "manifests_served": sum(1 for r in manifests if r.get("served")),
        "partial_now": len(partial),
        "partial_missing_now": dict(pmiss),
        # what the published, dated page says, which is what the spec actually cites
        "published_partial": int(re.search(r"still unsignable \| (\d+)", published).group(1)),
        "published_missing": {k: int(v) for k, v in re.findall(r"\| `(asset|payTo|network|amount)` \| (\d+) \|", published)},
    }


def claims(f):
    """(quote, kind, verdict, detail). The quote must appear in the spec or the entry is stale."""
    ten = f["ten_class_counts"]
    tail_ours = f["ten_class_total"] - sum(ten[k] for k in ("vercel.app", "workers.dev", "up.railway.app", "onrender.com"))
    # The spec names the Cloud Run class `a.run.app`; this census files it under run.app and
    # checks separately that every one of those hosts really sits under a.run.app.
    tail = {"fly.dev": 12, "replit.app": 4, "netlify.app": 3, "run.app": 3, "sslip.io": 3, "nip.io": 1}
    n_classes = len(ten) + len(f["classes_outside_the_ten"])
    return [
        ("1,971 names", "OURS", f["census_names"] == 1971, f"census queried {f['census_names']}"),
        ("7 records across 5 operators", "OURS", f["records"] == 7 and f["operators"] == 5,
         f"{f['records']} records over {f['operators']} registrable domains"),
        ("(`auor.io`)", "OURS", f["rows"]["bare URL"] == 1, f"bare URL rows: {f['rows']['bare URL']}"),
        ("`api.posttosource.com`, `posttosource.com`, `api.telemost.io`", "OURS",
         f["rows"]["v=x4021;descriptor=...;url="] == 3,
         f"descriptor rows: {f['rows']['v=x4021;descriptor=...;url=']}, names {f['row_names']['v=x4021;descriptor=...;url=']}"),
        ("(`vibesprings.net`)", "OURS", f["rows"]["x402-manifest="] == 1, f"manifest-pointer rows: {f['rows']['x402-manifest=']}"),
        ("(`sirenic.eu`, `api.sirenic.eu`)", "OURS", f["rows"]["v=x402-1 (conforming)"] == 2,
         f"conforming rows: {f['rows']['v=x402-1 (conforming)']}"),
        # Since 3b6d778 the sentence names its units: names, zones and bodies are each checked here.
        ("The three `v=x4021` records across two publishing zones", "OURS",
         len(f["x4021_names"]) == 3 and len(f["x4021_zones"]) == 2,
         f"{len(f['x4021_names'])} names in {len(f['x4021_zones'])} zones {f['x4021_zones']}"),
        ("(Two publishing zones publish three such names", "OURS",
         len(f["x4021_zones"]) == 2 and len(f["x4021_names"]) == 3,
         f"names {f['x4021_names']}"),
        ("with the first two carrying byte-identical record bodies", "OURS",
         ["api.posttosource.com", "posttosource.com"] in f["identical_pairs"] and f["x4021_bodies"] == 2,
         f"{f['x4021_bodies']} distinct bodies over the three; identical pairs {f['identical_pairs']} "
         "(the spec lists api.posttosource.com and posttosource.com first)"),
        ("four single-operator domains each hold 32 or more hosts", "OURS", len(f["fleets_32_plus"]) == 4,
         f"{len(f['fleets_32_plus'])} domains hold 32+: {f['fleets_32_plus']}"),
        ("401 of the 1,521 hosts sit directly under shared-platform", "OURS",
         f["our_platform_total"] == 401 and f["pinned"] == 1521,
         f"this census counts {f['our_platform_total']} platform hosts of {f['pinned']}, over {n_classes} classes"),
        ("393 across the ten primary platforms", "OURS", f["ten_class_total"] == 393,
         f"the spec's ten classes hold {f['ten_class_total']} here"),
        ("`vercel.app` 202, `workers.dev` 72, `up.railway.app` 66", "OURS",
         (ten["vercel.app"], ten["workers.dev"], ten["up.railway.app"]) == (202, 72, 66),
         f"vercel {ten['vercel.app']}, workers.dev {ten['workers.dev']}, up.railway.app {ten['up.railway.app']}"),
        ("`onrender.com` 27", "OURS", ten["onrender.com"] == 27, f"onrender.com {ten['onrender.com']}"),
        ("the remaining 26 across `fly.dev` 12, `replit.app` 4, `netlify.app` 3, `a.run.app` 3, `sslip.io` 3, `nip.io` 1",
         "OURS", tail_ours == 26 and all(ten.get(k, 0) == v for k, v in tail.items()) and f["run_app_all_under_a"],
         f"tail {tail_ours}: " + ", ".join(f"{k} {ten.get(k, 0)}" for k in tail)
         + f"; every run.app host under a.run.app: {f['run_app_all_under_a']}"),
        ("`hf.space` 5 and `trycloudflare.com` 3", "OURS",
         f["classes_outside_the_ten"] == {"hf.space": 5, "trycloudflare.com": 3},
         f"platform hosts outside the ten: {f['classes_outside_the_ten']}"),
        ("collapses those 401 operators into twelve buckets", "OURS",
         f["our_platform_total"] == 401 and f["last_two_buckets"] == 12,
         f"a last-two-labels rule makes {f['last_two_buckets']} buckets of {f['our_platform_total']} hosts"),
        ("Twelve boundaries cover every platform host in the census today (the ten primary platforms "
         "covering 393 hosts, plus `hf.space` 5 and `trycloudflare.com` 3 closing the 401 total)", "OURS",
         n_classes == 12 and f["ten_class_total"] == 393 and f["our_platform_total"] == 401,
         f"{n_classes} non-empty classes of the {len(OURS_PLATFORM)} this census knows; "
         f"{f['ten_class_total']} + {sum(f['classes_outside_the_ten'].values())} = {f['our_platform_total']}"),
        # These cite MANIFESTS.md, which is dated 2026-08-02 on its face. The committed artifact is
        # the 08-11 re-run, so the published page is the right comparand and the later draw is a note.
        ("Of 205 manifests observed", "OURS", f["published_partial"] == 205,
         f"MANIFESTS.md (2026-08-02) publishes {f['published_partial']}; the 08-11 re-run in "
         f"manifests.json reads {f['partial_now']} ({f['manifests_served']} served)"),
        ("188 were missing `asset` and 144 were missing `payTo`", "OURS",
         (f["published_missing"].get("asset"), f["published_missing"].get("payTo")) == (188, 144),
         f"published page: asset {f['published_missing'].get('asset')}, payTo {f['published_missing'].get('payTo')}; "
         f"08-11 re-run: asset {f['partial_missing_now'].get('asset')}, payTo {f['partial_missing_now'].get('payTo')}"),
        ("A census of 260 live payment-gated hosts found 139 readable 402", "OURS-POSTED",
         f["posted_0806"]["ok"], f["posted_0806"]["detail"]),
        ("The 260-host / 139-challenge figure in §2.1 is from probe measurements by [@meloliva14]"
         "(https://github.com/meloliva14) reported in [#2979 (comment)](https://github.com/x402-foundation/"
         "x402/pull/2979#issuecomment-5199553316)", "OURS-POSTED", f["posted_0806"]["ok"],
         "the footnote cites that comment; its §2.1 names no section, the headings are unnumbered "
         "(raised by minia2auk on 2026-09-24)"),
        ("three of the seven\n> live", "OURS", len(f["records_not_pinned"]) == 3,
         f"record names that are not themselves pinned hosts: {f['records_not_pinned']}"),
        ("1,619 catalogued hosts, 380 of", "THEIRS", True, "not this census: the manifest survey here is 1,521 hosts"),
        ("the 442 that publish a version-like key", "THEIRS", True, "same 1,619-host survey, not this repo"),
        ("171-host census reports 52 of 76", "THEIRS", True, "Circadian-agent's census, credited in the doc"),
        ("1,609 catalogued hosts", "THEIRS", True, "the spec author's own survey"),
        ("1,617-host walk", "THEIRS", True, "the spec author's own walk"),
        ("leaves only 7 (0.4%) unable to reach their own apex", "THEIRS", True, "measured against the same 1,617 hosts"),
        ("1,611 catalogued hosts on 2026-08-23, 381 (23.6%)", "THEIRS", True,
         "conformance/ancestor-walk.json, credited there"),
        ("2,234-name ancestor-walk", "THEIRS", True, "conformance/ancestor-walk.json, credited there"),
        ("None of the 28 suffixes", "THEIRS", True, "ancestor-walk dataset, credited there"),
    ]


# Numbers that are structure rather than measurement: caps, versions, RFCs, ports, examples.
PROSE = {"402", "8615", "3009", "2026", "29", "23", "22", "2979", "8601", "32", "169.254", "1918",
         "256", "25", "427961920698", "1.2", "0.06", "24", "20", "100", "50", "1", "2", "3", "4",
         "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "21",
         "26", "27", "28", "30", "31", "33", "34", "35", "36", "37", "38", "39", "40", "41", "42",
         "43", "44", "45", "46", "47", "48", "49", "60", "64", "72", "80", "90", "96", "99", "120",
         "300", "301", "302", "307", "308", "400", "404", "405", "410", "429", "500", "502", "503",
         "504", "520", "526", "600", "900", "1000", "3600", "86400"}


def main() -> int:
    spec, sha, path = spec_text()
    flat = " ".join(spec.split())
    f = facts()
    rows = claims(f)
    print(f"  spec {path} @ {sha[:10]} | census day {f['day']} | pinned {f['pinned']}\n")

    stale = [q for q, *_ in rows if q.replace("\n> ", " ") not in flat and q not in spec]
    bad = []
    for quote, kind, good, detail in rows:
        mark = {"THEIRS": "THEIRS ", "OURS-UNPUBLISHED": "UNPUBL "}.get(kind, "PASS   " if good else "FAIL   ")
        if kind == "OURS-POSTED":
            mark = "POSTED " if good else "FAIL   "
        if kind in ("OURS", "OURS-POSTED") and not good:
            bad.append(quote)
        if kind == "OURS-UNPUBLISHED":
            bad.append(quote)
        print(f"  {mark} {quote[:58]:<58} {detail}")
    n_posted = sum(1 for _, kind, good, _ in rows if kind == "OURS-POSTED" and good)

    # Nothing may be skipped: every numeric token has to be claimed by a line above.
    claimed = " ".join(q for q, *_ in rows)
    unclaimed = collections.Counter()
    # Dates, draft revisions, RFC section numbers and ISO timestamps are structure, not measurement.
    scrubbed = re.sub(r"\d{4}-\d{2}-\d{2}(T[\d:.]+Z?)?|-\d{2}\b|rfc\d+#section-[\d.]+|DNS-\d+", " ", spec)
    for m in re.finditer(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w])", scrubbed):
        n = m.group(1).rstrip(",")
        if n in PROSE or n in claimed or n.replace(",", "") in claimed:
            continue
        unclaimed[n] += 1
    if unclaimed:
        print("\n  UNCLASSIFIED numbers, nobody has said whose these are:")
        for n, c in unclaimed.most_common():
            ctx = [l.strip()[:90] for l in spec.split("\n") if re.search(rf"(?<![\w.]){re.escape(n)}(?![\w])", l)]
            print(f"   {n:>10} x{c}  {ctx[0] if ctx else ''}")

    if stale:
        print("\n  STALE ENTRIES, the quote is no longer in the document:", stale)
    print(f"\n  {len(rows) - len(bad)} of {len(rows)} attributed claims reproduce "
          f"({n_posted} of them only from a posted comment of ours); "
          f"{len(bad)} do not; {len(unclaimed)} numbers unclassified; {len(stale)} stale entries")
    return 1 if (bad or unclaimed or stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
