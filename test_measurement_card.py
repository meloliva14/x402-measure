"""measurement_card.json must agree with the census. Run: python test_measurement_card.py

Checks the card against the latest signed snapshot's manifest and the published key, and checks
the two 'where the payment terms are read' claims against the classifier's actual behaviour.
"""
import base64, json, sys
from pathlib import Path

import preflight

HERE = Path(__file__).resolve().parent
card = json.loads((HERE / "measurement_card.json").read_text(encoding="utf-8"))
snaps = HERE / "snapshots"
day = sorted(p.name for p in snaps.iterdir() if p.name[:2] == "20")[-1]
m = json.loads((snaps / day / "observation.json").read_text(encoding="utf-8"))["manifest"]
key = json.loads((HERE / "index-pubkey.json").read_text(encoding="utf-8"))

ok = True
def check(name, cond):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name)

pop = card["population"]
check(f"population matches the {day} manifest",
      (pop["source"], pop["collected_at_utc"], pop["hosts"], pop["target_list_sha256"]) ==
      (m["target_list_source"], m["target_list_collected_at_utc"], m["target_list_count"], m["target_list_sha256"]))
check("probe method and retry rule match the manifest word for word",
      card["probe"]["method"] == m["method"] and card["probe"]["retry_rule"] == m["retry_rule"])
check("verdict vocabulary matches the manifest", card["broken"]["verdicts"] == m["verdict_vocabulary"])
check("named verdicts exist in the vocabulary",
      set(card["broken"]["no_payment_challenge"] + card["broken"]["no_response_at_all"]) <= set(m["verdict_vocabulary"]))
check("signing key matches index-pubkey.json", card["probe"]["signed"]["key_id"] == key["key_id"])

challenge = {"x402Version": 2, "resource": {"url": "https://example.test/r"}, "accepts": [{
    "scheme": "exact", "network": "eip155:8453", "amount": "20000",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "payTo": "0x0000000000000000000000000000000000000001", "maxTimeoutSeconds": 300,
    "extra": {"name": "USD Coin", "version": "2"}}]}
b64 = base64.b64encode(json.dumps(challenge).encode()).decode()
v_hdr = preflight.decide(402, {"PAYMENT-REQUIRED": b64}, "{}")[0]
v_bod = preflight.decide(402, {}, json.dumps(challenge))[0]
v_none = preflight.decide(402, {}, "{}")[0]
check(f"v2 verdict reads the header (header only, empty body -> {v_hdr})", v_hdr in ("OK", "WARN"))
check(f"v2 verdict falls back to the body (body only -> {v_bod})", v_bod != "UNPARSEABLE")
check(f"no challenge in either place is unreadable (-> {v_none})", v_none == "UNPARSEABLE")
check("v1 verdict reads the body only (header present, body {} -> V1_NO_ACCEPTS)",
      preflight.v1_verdict("{}")[0] == "V1_NO_ACCEPTS")
check("card names the code that does this", set(card["payment_terms_read_from"]["code"]) ==
      {"preflight.decide", "preflight.v1_verdict"} and hasattr(preflight, "decide") and hasattr(preflight, "v1_verdict"))

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
