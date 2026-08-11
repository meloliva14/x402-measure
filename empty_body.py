"""How many live sellers return a 402 whose BODY tells a buyer nothing?

Our classify() reads the PAYMENT-REQUIRED header first, so a host with a perfect header and a
completely empty body scores OK. That is correct for a v2 buyer and blind to the population
gadaffihub measured from the other side. Before putting a number in front of a vendor it has to
be our own measurement, not his repeated back at him.

Also separates the signature the x402 Python FastAPI middleware leaves behind -- a literal `{}`
or empty body alongside a valid header -- from bodies that are merely v2-shaped.
"""
import json, ssl, urllib.error, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
UA={"user-agent":"verity-measure/1.0 (+https://veritylayer.dev)","content-type":"application/json"}

def probe(t):
    try:
        urllib.request.urlopen(urllib.request.Request(
            t["url"],method="POST",data=b"{}",headers=UA),timeout=12,context=CTX)
        return None
    except urllib.error.HTTPError as e:
        if e.code!=402: return None
        hdr=bool(e.headers.get("PAYMENT-REQUIRED") or e.headers.get("payment-required"))
        raw=e.read(200_000)
        srv=(e.headers.get("server") or "")[:40]
        try: b=json.loads(raw)
        except Exception: b=None
        if raw.strip() in (b"", b"{}"): kind="EMPTY_BODY"
        elif not isinstance(b,dict): kind="unparseable"
        elif not b.get("accepts"): kind="no_accepts"
        else:
            a=(b["accepts"] or [{}])[0]
            kind="v1_usable" if a.get("maxAmountRequired") is not None else "v2_vocab_in_body"
        return {"host":t["host"],"kind":kind,"header":hdr,"bytes":len(raw),"server":srv}
    except Exception:
        return None

doc=json.loads(Path("targets.json").read_text(encoding="utf-8"))
tg=doc["targets"]
print(f"  probing {len(tg)} hosts for what the BODY carries\n")
with ThreadPoolExecutor(max_workers=14) as ex:
    res=[r for r in ex.map(probe,tg) if r]

c=Counter(r["kind"] for r in res)
print(f"  hosts issuing a 402: {len(res)}\n")
for k,v in c.most_common(): print(f"    {k:<20} {v:>5}  ({v/len(res)*100:.1f}%)")
eb=[r for r in res if r["kind"]=="EMPTY_BODY"]
print(f"\n  EMPTY BODY + valid header (the middleware default signature): "
      f"{sum(1 for r in eb if r['header'])}")
print(f"  empty body and NO header (unpayable by anyone): {sum(1 for r in eb if not r['header'])}")
print("\n  server header among empty-body hosts:")
for s,n in Counter(r["server"] or "(none)" for r in eb).most_common(8): print(f"    {n:>4}  {s}")
Path("empty_body.json").write_text(json.dumps(
    {"probed":len(tg),"gated":len(res),"counts":dict(c),"results":res},indent=1),encoding="utf-8")
print("\n  wrote empty_body.json")
