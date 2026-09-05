"""Collect the payTo wallet of every live x402 seller we know about.

Nobody has a real number for x402 economic activity. x402scan undercounts by ~35x, which we
proved. The honest way to size it is bottom-up: take every seller in our census, read the payTo
address out of its own 402 challenge, then measure what those wallets actually received on chain.

That is the denominator for any business case. If total ecosystem revenue is tiny, we should know
before building, not after.

2026-09-04: the roster now comes from the latest daily snapshot (verdicts OK and V1) instead of
the frozen July sweep_results.json, so a re-run reflects the census as of its date. The probe
itself and the output shape are unchanged from a3bc36c.
"""
import base64, json, ssl, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
UA={"user-agent":"verity-measure/1.0 (+https://veritylayer.dev)","content-type":"application/json"}

def payto_of(row):
    url=row.get("url")
    if not url: return None
    req=urllib.request.Request(url,method="POST",data=b"{}",headers=UA)
    try:
        urllib.request.urlopen(req,timeout=12,context=CTX); return None
    except urllib.error.HTTPError as e:
        if e.code!=402: return None
        out={"host":row["host"]}
        h=e.headers.get("PAYMENT-REQUIRED") or e.headers.get("payment-required")
        if h:
            try:
                d=json.loads(base64.b64decode(h)); a=(d.get("accepts") or [{}])[0]
                out["payTo"]=a.get("payTo"); out["amount"]=a.get("amount")
                out["network"]=a.get("network"); out["asset"]=a.get("asset")
            except Exception: pass
        if not out.get("payTo"):
            try:
                b=json.loads(e.read(200_000)); a=(b.get("accepts") or [b])[0]
                out["payTo"]=a.get("payTo")
                out["amount"]=a.get("amount") or a.get("maxAmountRequired")
                out["network"]=a.get("network"); out["asset"]=a.get("asset")
            except Exception: pass
        return out if out.get("payTo") else None
    except Exception:
        return None

SNAPSHOTS=Path(__file__).parent/"snapshots"
latest=sorted(q.name for q in SNAPSHOTS.iterdir())[-1]
rows=json.loads((SNAPSHOTS/latest/"observation.json").read_text(encoding="utf-8"))["observations"]
live=[r for r in rows if r.get("verdict") in ("OK","V1") and r.get("url")]
print(f"  roster: the {latest} snapshot")
print(f"  probing {len(live)} live gated hosts for payTo\n")
with ThreadPoolExecutor(max_workers=16) as ex:
    res=[r for r in ex.map(payto_of, live) if r]

seen={}
for r in res:
    p=(r.get("payTo") or "").lower()
    if not p.startswith("0x") or len(p)!=42: continue
    seen.setdefault(p,{"payTo":p,"hosts":[],"amounts":set(),"networks":set()})
    seen[p]["hosts"].append(r["host"])
    if r.get("amount"): seen[p]["amounts"].add(str(r["amount"]))
    if r.get("network"): seen[p]["networks"].add(str(r["network"]))

out=[{"payTo":v["payTo"],"hosts":v["hosts"],"n_hosts":len(v["hosts"]),
      "amounts":sorted(v["amounts"])[:6],"networks":sorted(v["networks"])} for v in seen.values()]
out.sort(key=lambda x:-x["n_hosts"])
Path("payto_wallets.json").write_text(json.dumps(out,indent=1),encoding="utf-8")

print(f"  hosts that answered with a payTo : {len(res)}")
print(f"  DISTINCT seller wallets          : {len(out)}")
print(f"  wallets serving >1 host          : {sum(1 for x in out if x['n_hosts']>1)}\n")
print("  biggest operators by host count:")
for x in out[:12]:
    print(f"   {x['payTo'][:16]}..  {x['n_hosts']:>4} hosts  nets={','.join(x['networks'])[:26]}")
print("\n  wrote payto_wallets.json")
