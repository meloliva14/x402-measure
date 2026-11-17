"""Check for agreement_2026-11.md.

Usage: python agreement_check.py PAGES_DIR
PAGES_DIR holds saved copies of the source pages, named as in SRC below (not committed, since
they are other people's pages; save your own copies to re-check).

Every number in the report must be on the allowed list, each allowed source number must still
be on its saved page, our side must recompute from the signed snapshot, and the text must carry
no long dashes. Exit 0 only if all pass."""
import html, json, re, subprocess, sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
D = Path(__file__).with_name("agreement_2026-11.md").read_text(encoding="utf-8")
PAGES = Path(sys.argv[1])
fails = []

def page(f):
    s = (PAGES / f).read_text(encoding="utf-8", errors="replace")
    if f.endswith(".html"):
        s = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", " ", s); s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).replace("\u2019", "'")

# number in draft -> (page file, exact text proving it)
SRC = {
 "1,225": ("forgemesh.html", "all 1,225 of them"), "17%": ("forgemesh.html", "206 sellers (17%) are dead"),
 "1,343": ("x402list_state.html", "1343 services are listed"), "1,230": ("x402list_state.html", "1230 answering"),
 "2,280": ("lowkey.html", "31,620 unique resource URLs on 2,280 hosts"), "31,620": ("lowkey.html", "31,620 unique resource URLs"),
 "3,218": ("tanod_stats.csv", "2026-11-16,33324,3218,0.005"), "33,324": ("tanod_stats.csv", "2026-11-16,33324"),
 "$0.005": ("tanod_stats.csv", "2026-11-16,33324,3218,0.005"),
 "46,352": ("tanod_repo_stats.csv", "2026-10-18,46352"), "25,790": ("tanod_repo_stats.csv", "2026-10-19,25790"),
 "79,456": ("tanod_repo_stats.csv", "2026-10-27,79456"),
 "17,533": ("stelar.html", "17,533"), "48,541": ("index402.html", "48,541"),
 "175,450": ("minia.html", "175,450 / 175,331"), "175,331": ("minia.html", "175,450 / 175,331"),
 "61%": ("minia.html", "61% of probed endpoints do not answer at all"),
 "660,013": ("minia.html", "660,013 / $15,866.16"), "$0.024": ("minia.html", "Mean transfer $0.024"),
 "405,664": ("trust_report.html", "405,664 endpoints listed 241,233 currently active 164,431 delisted"),
 "241,233": ("trust_report.html", "36% actually reachable of 241,233 active endpoints"),
 "164,431": ("trust_report.html", "164,431 delisted"), "36%": ("trust_report.html", "36% actually reachable"),
 "43.4%": ("feldspar.html", "43.4% of 140,794"), "32.1%": ("feldspar.html", "32.1% of 196,373"),
 "2.7%": ("feldspar.html", "new series: 2.7% of 43,907"), "196,373": ("feldspar.html", "from 196,373 to 43,907"),
 "43,907": ("feldspar.html", "from 196,373 to 43,907"),
 "1,157": ("index402.html", "down 1,157 unknown 12,460"), "12,460": ("index402.html", "unknown 12,460"),
 "52,572": ("index402.html", "52,572"),
 "45,152": ("paycheck.html", "45,152"), "95.1%": ("paycheck.html", "29,990 95.1%"),
 "31,546": ("paycheck.html", "(31,546 endpoints)"), "49.1%": ("paycheck.html", "61,982 (49.1%)"),
 "126,291": ("paycheck.html", "Of 126,291 test attempts"), "86.1%": ("paycheck.html", "53,340 86.1%"),
 "0.87": ("paycheck.html", "0.87"),
}
# x402 List median: JSON field
SRC_JSON = {"$0.01": [("x402list_stats.json", '"median_price_usd":0.01'), ("tanod_repo_stats.csv", "2026-10-27,79456,2760,0.01")]}
for num, (f, proof) in SRC.items():
    if proof not in page(f): fails.append(f"source no longer shows {num}: {f} lacks {proof!r}")
for num, lst in SRC_JSON.items():
    for f, proof in lst:
        if proof not in page(f): fails.append(f"source no longer shows {num}: {f} lacks {proof!r}")

# our side, recomputed from the signed snapshot
o = subprocess.run([sys.executable, str(Path(__file__).with_name("agreement_ourside.py")), "2026-11-16"],
                   cwd=str(Path(__file__).resolve().parent), capture_output=True, text=True, encoding="utf-8")
if o.returncode: fails.append("our side refused: " + o.stdout + o.stderr); O = {}
else: O = json.loads(o.stdout)
OURS = {}
if O:
    def put(n, pct=None): OURS[f"{n:,}"] = True; pct is not None and OURS.__setitem__(f"{pct}%", True)
    put(O["hosts_probed"]); put(*O["http_404"]); put(*O["no_response_at_all"]); put(*O["http_404_or_410"])
    put(*O["no_payment_challenge_any_reason"]); put(*O["signable_with_no_terms_in_body"])
    put(O["signable_v2"][0]); put(O["median_price_base_usdc_per_host"][1]); put(O["price_0_01_or_less_hosts"][0])
    OURS[f"{round(100*O['price_0_01_or_less_hosts'][0]/O['price_0_01_or_less_hosts'][1])}%"] = True
    if O["median_price_base_usdc_per_host"][0] != 0.02: fails.append("our median is not 0.02")
    OURS["$0.02"] = True
# check the specific pairings in the draft
for pair in ["| answered 404 | 96 | 6.3% |", "| no response at all | 171 | 11.2% |", "| answered 404 or 410 | 179 | 11.8% |",
             "| served no payment challenge of any kind | 470 | 30.9% |", "462 (48.6%)", "Of the 950 hosts", "| 934 hosts |",
             "Of my 934 hosts, 439 (47%)", "the same 1,521 hosts"]:
    if pair not in D: fails.append(f"draft lacks pairing {pair!r}")

# context-only numbers (dates, list numbers, issue number, wording)
OK_CTX = {"2026", "2026-11-16", "4127", "402", "404", "410", "v2", "x402", "L402"}
body = re.sub(r"https?://\S+", " ", D)
tokens = [t.rstrip(",") for t in re.findall(r"\$?\d[\d,]*(?:\.\d+)?%?¢?", body)]
allowed = set(SRC) | set(SRC_JSON) | set(OURS)
for t in tokens:
    if t in allowed or t in OK_CTX: continue
    if re.fullmatch(r"\d{1,2}", t): continue          # day numbers, list items, "five"
    if t in {"0.87¢"}: continue
    fails.append(f"number not traced: {t}")

for ch in "\u2014\u2013":
    if ch in D: fails.append(f"draft carries a long dash {ch!r}")

print("\n".join(fails) or "ALL PASS")
print(f"{len(tokens)} numbers checked, {len(SRC)+len(SRC_JSON)} source figures re-read, {len(OURS)} ours recomputed")
sys.exit(1 if fails else 0)
