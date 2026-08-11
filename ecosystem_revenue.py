"""What does the ENTIRE known x402 seller population actually earn? Bottom-up, on chain.

CONTROL: VerityLayer's own wallet must come back at $9.83 across 41 USDC transfers. That figure
was established independently and matches the wallet's live balance exactly. If the control does
not reproduce, every other number here is noise and nothing may be reported.
"""
import json, ssl, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
H={"user-agent":"verity-measure/1.0","accept":"application/json"}
USDC="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
OURS="0x89d38023167bda453bed9f6cbf22ddd1ec5f70a7"

def transfers(addr):
    u=f"https://base.blockscout.com/api/v2/addresses/{addr}/token-transfers?type=ERC-20"
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=45,context=CTX) as r:
            d=json.loads(r.read(30_000_000))
    except Exception as e:
        return {"addr":addr,"error":type(e).__name__}
    inn=[]
    for t in d.get("items",[]):
        tk=t.get("token") or {}
        if (tk.get("address_hash") or "").lower()!=USDC: continue
        to=((t.get("to") or {}).get("hash") or "").lower()
        if to!=addr.lower(): continue
        inn.append({"ts":t["timestamp"][:19],
                    "v":int((t.get("total") or {}).get("value") or 0)/1e6})
    return {"addr":addr,"n":len(inn),"total":sum(x["v"] for x in inn),
            "txs":inn,"more":bool(d.get("next_page_params"))}

W=[w["payTo"] for w in json.loads(Path("payto_wallets.json").read_text(encoding="utf-8"))]
if OURS not in [w.lower() for w in W]: W.append(OURS)
print(f"  querying {len(W)} seller wallets on Base\n")
with ThreadPoolExecutor(max_workers=8) as ex:
    res=list(ex.map(transfers,W))

ctl=[r for r in res if r["addr"].lower()==OURS]
if ctl and not ctl[0].get("error"):
    c=ctl[0]
    ok = c["n"]>=40 and abs(c["total"]-9.83)<0.5
    print(f"  CONTROL VerityLayer wallet: {c['n']} transfers, ${c['total']:.2f}  "
          f"{'PASS' if ok else 'FAIL'}")
    if not ok: raise SystemExit("control failed - not reporting")
else:
    raise SystemExit("control unavailable - not reporting")

good=[r for r in res if not r.get("error")]
errs=[r for r in res if r.get("error")]
earners=[r for r in good if r["n"]>0]
tot=sum(r["total"] for r in good)
capped=sum(1 for r in good if r.get("more"))

print(f"  queried ok: {len(good)}   errors: {len(errs)}")
print(f"  wallets with ANY USDC received : {len(earners)} / {len(good)} ({len(earners)/max(len(good),1)*100:.1f}%)")
print(f"  wallets hitting the page cap   : {capped}  (their totals are FLOORS)")
print(f"\n  TOTAL USDC received across all known x402 seller wallets: ${tot:,.2f}")
print(f"  (floor - page-capped wallets are undercounted)\n")

by=defaultdict(float); cnt=defaultdict(int)
for r in good:
    for t in r["txs"]:
        by[t["ts"][:10]]+=t["v"]; cnt[t["ts"][:10]]+=1
days=sorted(by)
if days:
    print(f"  activity window: {days[0]} -> {days[-1]}  ({len(days)} active days)")
    last14=[d for d in days if d>="2026-07-25"]
    print(f"  last 14 days: ${sum(by[d] for d in last14):,.2f} across {sum(cnt[d] for d in last14)} payments")
    print(f"  mean/day over last 14: ${sum(by[d] for d in last14)/14:,.2f}\n")
    print("  most recent 14 days:")
    for d in days[-14:]:
        print(f"   {d}  ${by[d]:>12,.2f}  ({cnt[d]} payments)")

earners.sort(key=lambda r:-r["total"])
print("\n  top earning seller wallets:")
for r in earners[:15]:
    print(f"   {r['addr'][:18]}..  ${r['total']:>12,.2f}  {r['n']:>4} payments{'  (FLOOR)' if r.get('more') else ''}")

Path("ecosystem_revenue.json").write_text(json.dumps(
    {"wallets":len(good),"earners":len(earners),"total_usdc":tot,
     "by_day":dict(by),"capped":capped},indent=1),encoding="utf-8")
print("\n  wrote ecosystem_revenue.json")
