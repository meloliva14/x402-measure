"""Our side of the agreement report: every Verity census figure it quotes, recomputed from one
signed snapshot, under each of the other measurers' definitions.

Usage, from a clone of this repo:  python agreement_ourside.py 2026-11-16
Refuses unless verify_snapshot.py passes for that day.
"""
import collections, json, re, statistics, subprocess, sys
from pathlib import Path

DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-11-16"
REPO = Path(__file__).resolve().parent
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"

v = subprocess.run([sys.executable, "verify_snapshot.py", DAY], cwd=REPO, capture_output=True, text=True)
if v.returncode != 0:
    sys.exit(f"REFUSING: {DAY} does not verify:\n{v.stdout}{v.stderr}")

doc = json.loads((REPO / "snapshots" / DAY / "observation.json").read_text(encoding="utf-8"))
obs = doc["observations"]
N = len(obs)
verd = collections.Counter(r["verdict"] for r in obs)


def http(r):
    for n in r["notes"]:
        m = re.match(r"HTTP (\d{3})", n)
        if m:
            return int(m.group(1))
    return None


no402 = collections.Counter(http(r) for r in obs if r["verdict"] == "NO_402")
gated = sum(verd[k] for k in ("OK", "WARN", "V1", "NON_EVM", "BLOCKED"))
ok = [r for r in obs if r["verdict"] == "OK"]
body_has_no_terms = sum(1 for r in ok if r["v1"] in ("V1_NO_ACCEPTS", "V1_NO_BODY"))
prices = []
for r in ok:
    m = re.search(r"amount=(\d+) asset=(0x[0-9a-fA-F]{40})", " ".join(r["notes"]))
    if m and m.group(2).lower() == USDC:
        prices.append(int(m.group(1)))
pct = lambda a, b: round(100 * a / b, 1)

F = {
    "day": DAY,
    "verified": v.stdout.strip().splitlines()[-1],
    "hosts_probed": N,
    "population": doc["manifest"]["target_list_source"],
    "list_pinned_utc": doc["manifest"]["target_list_collected_at_utc"],
    "no_response_at_all": [verd["UNREACHABLE"], pct(verd["UNREACHABLE"], N)],
    "http_404": [no402[404], pct(no402[404], N)],
    "http_404_or_410": [no402[404] + no402[410], pct(no402[404] + no402[410], N)],
    "http_5xx": sum(c for k, c in no402.items() if k and k >= 500),
    "http_200_no_challenge": no402[200],
    "no_payment_challenge_any_reason": [verd["UNREACHABLE"] + verd["NO_402"],
                                        pct(verd["UNREACHABLE"] + verd["NO_402"], N)],
    "payment_gated": [gated, pct(gated, N)],
    "signable_v2": [verd["OK"], pct(verd["OK"], N)],
    "signable_with_no_terms_in_body": [body_has_no_terms, pct(body_has_no_terms, verd["OK"])],
    "median_price_base_usdc_per_host": [statistics.median(prices) / 1e6, len(prices)],
    "price_0_01_or_less_hosts": [sum(p <= 10_000 for p in prices), len(prices)],
}
print(json.dumps(F, indent=1))
