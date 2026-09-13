"""The probe trace must say what the probe actually did. No network: preflight.fetch is a fake.

Guards the 2026-09-13 defect: the census was described as one request per host per day and a
comparison was built on that; it is one to three. From schema /3 every row records the truth.
These tests pin the recording and the k-bounds the comparator derives from it.

Proven by mutation, not observation: dropping the POST-side trace update makes the fallback case
report GET; dropping the retry summation makes the retried case report the second attempt only;
breaking k_bounds makes the historical bracket wrong.
"""
from __future__ import annotations

import sys

import preflight
import snapshot
import landing_model as lm


class _Script:
    """Answers fetch() calls from a queue. Each entry is (status, headers, body) or an Exception."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls: list[str] = []

    def __call__(self, url, method):
        self.calls.append(method)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


CHALLENGE_HDR = {"PAYMENT-REQUIRED": "e30="}   # base64 of "{}" -> parses to a dict with no accepts
OK_402 = (402, CHALLENGE_HDR, b"")


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))

    real_fetch = preflight.fetch
    try:
        # 1. GET answers 402 -> one request, verb GET
        preflight.fetch = _Script([OK_402])
        *_, trace = preflight.classify_both_traced("https://h/x")
        check("GET->402: one request", trace["requests"] == 1, str(trace))
        check("GET->402: verb is GET", trace["verb"] == "GET", str(trace))
        check("GET->402: get_status recorded as 402", trace["get_status"] == 402, str(trace))

        # 2. GET answers 200, POST answers 402 -> two requests, verb POST, get_status 200
        preflight.fetch = _Script([(200, {}, b"free"), OK_402])
        *_, trace = preflight.classify_both_traced("https://h/x")
        check("GET->200->POST->402: two requests", trace["requests"] == 2, str(trace))
        check("GET->200->POST->402: verb is POST", trace["verb"] == "POST", str(trace))
        check("GET->200->POST->402: get_status is 200", trace["get_status"] == 200, str(trace))

        # 3. neither verb yields 402 -> two requests, NO_402, verb POST
        s3 = _Script([(404, {}, b""), (405, {}, b"")])
        preflight.fetch = s3
        v, notes, _ch, v1, v1n, trace = preflight.classify_both_traced("https://h/x")
        check("404/405: verdict NO_402", v == "NO_402", v)
        check("404/405: two requests, both verbs tried", trace["requests"] == 2 and s3.calls == ["GET", "POST"], str(s3.calls))

        # 4. transport failure on GET -> UNREACHABLE with requests=1 and the SAME note text as before
        preflight.fetch = _Script([ConnectionResetError("boom")])
        v, notes, _ch, v1, v1n, trace = preflight.classify_both_traced("https://h/x")
        check("transport fail on GET: UNREACHABLE", v == "UNREACHABLE", v)
        check("transport fail on GET: note is the exception class name, unchanged",
              notes == ["ConnectionResetError"], str(notes))
        check("transport fail on GET: requests=1, verb None", trace["requests"] == 1 and trace["verb"] is None, str(trace))

        # 5. GET ok, POST transport-fails -> requests=2
        preflight.fetch = _Script([(200, {}, b""), TimeoutError("t")])
        v, notes, *_rest, trace = preflight.classify_both_traced("https://h/x")
        check("POST transport fail: requests=2", trace["requests"] == 2 and v == "UNREACHABLE", str(trace))

        # 6. the old 5-tuple API is byte-identical to the traced one minus the trace
        preflight.fetch = _Script([(200, {}, b"free"), OK_402])
        five = preflight.classify_both("https://h/x")
        preflight.fetch = _Script([(200, {}, b"free"), OK_402])
        six = preflight.classify_both_traced("https://h/x")
        check("classify_both == classify_both_traced[:5]", tuple(five) == tuple(six[:5]))

        # 7. observe(): a clean row carries probe with attempts=1 and a UTC timestamp
        preflight.fetch = _Script([OK_402])
        row = snapshot.observe({"host": "h", "url": "https://h/x"})
        pr = row.get("probe") or {}
        check("observe: probe object present", isinstance(row.get("probe"), dict), str(row.keys()))
        check("observe: attempts=1, requests=1, verb GET",
              pr.get("attempts") == 1 and pr.get("requests") == 1 and pr.get("verb") == "GET", str(pr))
        check("observe: at_utc is an ISO timestamp ending in +00:00",
              isinstance(pr.get("at_utc"), str) and pr["at_utc"].endswith("+00:00"), str(pr.get("at_utc")))
        check("observe: verdict semantics unchanged", row["verdict"] in ("OK", "BLOCKED", "UNPARSEABLE", "V1", "NON_EVM"), row["verdict"])

        # 8. observe(): transport fail then success on retry -> requests SUMMED across attempts
        preflight.fetch = _Script([ConnectionResetError("x"), (200, {}, b""), OK_402])
        row = snapshot.observe({"host": "h", "url": "https://h/x"})
        pr = row.get("probe") or {}
        check("retry: row flagged retried", row.get("retried") is True)
        check("retry: attempts=2", pr.get("attempts") == 2, str(pr))
        check("retry: requests summed = 1 (failed GET) + 2 (GET+POST) = 3", pr.get("requests") == 3, str(pr))
        check("retry: verb from the answering attempt = POST", pr.get("verb") == "POST", str(pr))
        check("retry: note text unchanged", row["notes"][0].startswith("first attempt unreachable (ConnectionResetError); answered on immediate retry"), row["notes"][0])

        # 9. observe(): unreachable on both attempts -> requests still summed, verb None
        preflight.fetch = _Script([TimeoutError("a"), TimeoutError("b")])
        row = snapshot.observe({"host": "h", "url": "https://h/x"})
        pr = row.get("probe") or {}
        check("double fail: requests = 1 + 1 = 2, verb None", pr.get("requests") == 2 and pr.get("verb") is None, str(pr))

        # 10. k_bounds: the comparator's reading of history vs schema /3 rows
        check("k_bounds: historical plain row -> (1, 2)", lm.k_bounds({}) == (1, 2))
        check("k_bounds: historical retried row -> (2, 4)", lm.k_bounds({"retried": True}) == (2, 4))
        check("k_bounds: schema/3 row with requests=2 -> (2, 2)", lm.k_bounds({"probe": {"requests": 2}}) == (2, 2))
        check("k_bounds: schema/3 row with requests=None falls back to history", lm.k_bounds({"probe": {"requests": None}}) == (1, 2))
        check("k_bounds: schema/3 row with requests=0 (policy refusal) -> (0, 0), no draw", lm.k_bounds({"probe": {"requests": 0}}) == (0, 0))
        check("p_land: zero draws can never land", lm.p_land(0.9, 0) == 0.0)

        # 11. the landing bracket collapses to the classic sum(p) when k is known to be 1
        demo = [{"share": 0.5, "our_served": True, "row": {"probe": {"requests": 1}}}] * 4
        s = lm.summarise(demo)
        check("summarise: k=1 exactly gives expected 2.0 both bounds", s["expected_k_lo"] == 2.0 == s["expected_k_hi"], str(s))
        # and widens for history
        demo2 = [{"share": 0.5, "our_served": True, "row": {}}] * 4
        s2 = lm.summarise(demo2)
        check("summarise: history brackets k in {1,2}: 2.0 .. 3.0", s2["expected_k_lo"] == 2.0 and s2["expected_k_hi"] == 3.0, str(s2))

        # 12. verdict_line never says "agrees": ANOMALOUS only when out at BOTH bounds, otherwise
        #     it names the uncorrected confound instead of a comfortable adjective
        both_out = lm.verdict_line({"observed": 19, "mixed_days": 19, "expected_k_lo": 12.47,
                                    "expected_k_hi": 13.0, "z_k_lo": 3.33, "z_k_hi": 3.0})
        check("verdict_line: out at both bounds -> ANOMALOUS", "ANOMALOUS" in both_out, both_out)
        one_in = lm.verdict_line({"observed": 19, "mixed_days": 19, "expected_k_lo": 12.47,
                                  "expected_k_hi": 16.30, "z_k_lo": 3.33, "z_k_hi": 1.87})
        check("verdict_line: inside at k-high -> names the confound, never agreement",
              "not anomalous at the k-high bound" in one_in and "not as agreement" in one_in
              and "consistent" not in one_in and "ANOMALOUS" not in one_in, one_in)
    finally:
        preflight.fetch = real_fetch

    ok = sum(1 for _, p, _ in results if p)
    for name, passed, detail in results:
        print(("PASS " if passed else "FAIL ") + name + (f"   [{detail}]" if detail and not passed else ""))
    print(f"\n{ok}/{len(results)} passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
