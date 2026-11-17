"""Checks for survival.py. Run: python test_survival.py

The operator rule, the silence counter and the end-state reader are checked on fixed inputs, and
the headline figures in the published survival file are recomputed here by a separate, plain loop
over the signed snapshots, so a bug in survival.py's bookkeeping cannot agree with itself.
"""
import json
import sys
from pathlib import Path

import survival as S
from monthly_report import GATED

HERE = Path(__file__).resolve().parent
ok = True


def check(name, cond):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name)


psl = S.load_psl(S.PSL)
cases = {
    "foo.klymax402.com": "klymax402.com",
    "a.b.example.co.uk": "example.co.uk",
    "my-app.vercel.app": "my-app.vercel.app",
    "svc.up.railway.app": "svc.up.railway.app",
    "api.foo.workers.dev": "foo.workers.dev",
    "x402.example.com": "example.com",
    "203.0.113.7": "203.0.113.7",
    "www.ck": "www.ck",            # exception rule !www.ck
    "a.b.ck": "a.b.ck",            # wildcard rule *.ck
}
for host, want in cases.items():
    check(f"operator of {host} is {want}", S.registrable(host, psl) == want)

prev = S.preview_scopes([
    "stable-enrich-git-fix-a-merit-systems.vercel.app",
    "stable-jobs-git-ben-b-merit-systems.vercel.app",
    "x402scan-e11utvi3p-merit-systems.vercel.app",
    "2s-3cpr6qm6j-alleyford.vercel.app",
    "lonely-git-main-solo.vercel.app",
    "plain-app.vercel.app",
])
check("previews of one team are grouped, hyphenated team slug kept",
      {prev.get(h) for h in list(prev)[:3]} == {"merit-systems.vercel.app previews"})
check("a lone preview and a plain app are not grouped",
      "lonely-git-main-solo.vercel.app" not in prev and "plain-app.vercel.app" not in prev
      and "2s-3cpr6qm6j-alleyford.vercel.app" not in prev)

check("silences counted with comebacks",
      S.silences([True, False, False, True, False]) == [(2, True), (1, False)])
check("no silence in an always-selling host", S.silences([True, True]) == [])

row = lambda v, note=None: {"verdict": v, "notes": [note] if note else []}
check("end state: unreachable", S.end_state(row("UNREACHABLE")) == "no_answer")
check("end state: 404", S.end_state(row("NO_402", "HTTP 404 - endpoint is not payment-gated right now")) == "not_found_404_410")
check("end state: 200", S.end_state(row("NO_402", "HTTP 200 - endpoint is not payment-gated right now"))
      == "answers_2xx_without_charging")
check("end state: 503", S.end_state(row("NO_402", "HTTP 503 - origin error")) == "server_error_5xx")
check("end state: gated", S.end_state(row("OK")) == "payment_gated")

# the published file, recomputed by a plain loop
pub = sorted(HERE.glob("survival_20*.json"))
if pub:
    F = json.loads(pub[-1].read_text(encoding="utf-8"))
    end, d0, q = F["window"]["end"], F["window"]["cohort_day"], F["window"]["quiet_days"]
    days = [d["date"] for d in F["inputs"]]
    g = {}
    for d in days:
        o = json.loads((HERE / "snapshots" / d / "observation.json").read_text(encoding="utf-8"))
        g[d] = {r["host"] for r in o["observations"] if r["verdict"] in GATED}
    cohort = g[d0]
    tail = days[-q:]
    stopped = [h for h in cohort if not any(h in g[d] for d in tail)]
    check(f"{pub[-1].name}: cohort size recomputes", len(cohort) == F["cohort"]["hosts"])
    check(f"{pub[-1].name}: stopped hosts recompute", len(stopped) == F["end"]["hosts_stopped"])
    check(f"{pub[-1].name}: gated on the last day recomputes",
          len(cohort & g[end]) == F["end"]["hosts_payment_gated"])
    check(f"{pub[-1].name}: every listed stopped host is in the recomputed set",
          sorted(stopped) == [s["host"] for s in F["stopped_hosts"]])
    check(f"{pub[-1].name}: days are consecutive and complete", len(days) == F["window"]["days"])

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
