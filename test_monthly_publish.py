"""Decision tests for monthly_publish.py against a fake GitHub. Run: python test_monthly_publish.py"""
import sys
from pathlib import Path

import monthly_publish as mp

END, ISSUE = "2026-12-16", "2026-12"
TITLE = "State of x402 2026-12 publishes on 2026-12-19 unless this issue is closed"


class Fake(mp.Ops):
    def __init__(self, text="report", iss=None, rel=None):
        super().__init__(dry=False)
        self.text, self.iss, self.rel, self.calls, self.committed = text, iss, rel, [], False

    def issues(self):
        return [self.iss] if self.iss else []

    def releases(self):
        return [self.rel] if self.rel else []

    def build(self, end, out: Path):
        (out / f"state_of_x402_{ISSUE}.md").write_bytes(self.text.encode())
        (out / f"state_of_x402_{ISSUE}.json").write_bytes(b"{}")

    def gh(self, *args, body=None):
        self.calls.append((args, body))
        if args[-1].endswith("/releases") and body and body.get("draft"):
            self.rel = {"id": 7, "tag_name": body["tag_name"], "draft": True, "body": body["body"],
                        "html_url": "https://x/draft"}
            return self.rel
        if args[-1].endswith("/issues"):
            self.iss = {"number": 3, "title": body["title"], "state": "open", "html_url": "https://x/i/3"}
            return self.iss
        if "/releases/" in args[-1]:
            return {"html_url": "https://x/release"}
        return {}

    def commit(self, issue, end):
        self.committed = True
        return "a" * 40


def run(fn, ops, published=False):
    try:
        return fn(ops, END, published)
    except SystemExit as e:
        return f"exit:{e.code}"


ok = True
def check(name, cond):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name)

real_copy = mp.shutil.copyfile
mp.shutil.copyfile = lambda a, b: None          # never write report files into the repo in tests

f = Fake(); r = run(mp.propose, f)
check("propose fresh opens a draft and an issue", r == 0 and f.rel and f.rel["draft"] and f.iss["title"] == TITLE)
check("draft carries the build hash", mp.MARK.search(f.rel["body"]))
check("issue body names the stop rule and the date", "Close this issue before 2026-12-19" in f.calls[-1][1]["body"])
n = len(f.calls); r = run(mp.propose, f)
check("propose again does nothing", r == 0 and len(f.calls) == n)

g = Fake(rel=dict(f.rel)); r = run(mp.propose, g)
check("propose with draft but no issue opens only the issue", r == 0 and len(g.calls) == 1 and g.iss)
h = Fake(text="changed", rel=dict(f.rel)); r = run(mp.propose, h)
check("propose refuses a stale draft that does not match", str(r).startswith("exit:") and not h.calls)

p = Fake(iss=dict(f.iss), rel=dict(f.rel)); r = run(mp.publish, p)
check("publish with open issue commits, publishes, comments, closes",
      r == 0 and p.committed and any(c[1] and c[1].get("draft") is False for c in p.calls)
      and any(c[1] and c[1].get("state") == "closed" for c in p.calls))
rel_patch = next(c for c in p.calls if c[1] and c[1].get("draft") is False)[1]
check("release is tagged at the pushed commit", rel_patch["target_commitish"] == "a" * 40)

q = Fake(iss=dict(f.iss, state="closed"), rel=dict(f.rel)); r = run(mp.publish, q)
check("publish after the owner closed the issue holds", r == 0 and not q.committed and not q.calls)

s = Fake(text="drifted", iss=dict(f.iss), rel=dict(f.rel)); r = run(mp.publish, s)
check("publish refuses when the rebuild differs, and says so on the issue",
      str(r).startswith("exit:") and not s.committed and "does not match" in s.calls[0][1]["body"])

t = Fake(); r = run(mp.publish, t)
check("publish with nothing proposed fails loudly", str(r).startswith("exit:") and not t.committed)

u = Fake(iss=dict(f.iss), rel=dict(f.rel, draft=False)); r = run(mp.publish, u)
check("publish refuses when there is no draft to publish", str(r).startswith("exit:") and not u.committed)

v = Fake(iss=dict(f.iss), rel=dict(f.rel)); r = run(mp.publish, v, published=True)
check("publish of a month already published does nothing", r == 0 and not v.committed and not v.calls)
w = Fake(); r = run(mp.propose, w, published=True)
check("propose of a month already published does nothing", r == 0 and not w.calls)

mp.shutil.copyfile = real_copy
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
