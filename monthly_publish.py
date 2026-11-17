"""Publish the monthly State of x402 report with a 48-hour hold the owner can cancel.

  propose  (run on the 17th): build the report for the window ending on the 16th, keep the full
           text in a DRAFT release (visible only to people who can write to this repo), and open
           an issue saying when it will publish. Closing that issue cancels the publish.
  publish  (run on the 19th): if the issue is still open, rebuild the report, require it to be
           byte-identical to the draft the owner was shown, commit it, publish the release, and
           close the issue with the links. If the issue was closed, publish nothing.

Every run is safe to repeat: a month already published, proposed or held is left alone.
monthly_report.py refuses (and so fails this run) on a missing day, a bad signature, a changed host
list, a number the text carries that the data does not, or a dash in the text.

  python monthly_publish.py propose [--end YYYY-MM-DD] [--dry-run]
  python monthly_publish.py publish [--end YYYY-MM-DD] [--dry-run]

--end defaults to the 16th of the current UTC month. --dry-run does every read and the build, and
prints each write instead of making it. Needs the gh CLI with a token that can write contents and
issues (GH_TOKEN in Actions).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = os.getenv("GITHUB_REPOSITORY", "meloliva14/x402-measure")
HOLD_DAYS = 3                       # the 16th's window, proposed on the 17th, published on the 19th
MARK = re.compile(r"<!-- monthly_publish md_sha256=([0-9a-f]{64}) json_sha256=([0-9a-f]{64}) -->")


class Ops:
    """Everything that touches the outside world, so the decisions can be tested without it."""

    def __init__(self, dry: bool):
        self.dry = dry

    def gh(self, *args, body=None):
        cmd = ["gh", "api", *args]
        if body is not None:
            cmd += ["--input", "-"]
        out = subprocess.run(cmd, input=None if body is None else json.dumps(body), text=True,
                             capture_output=True, encoding="utf-8")
        if out.returncode:
            sys.exit(f"  gh api {' '.join(args)} failed: {out.stderr.strip()}")
        return json.loads(out.stdout) if out.stdout.strip() else None

    def write(self, what, *args, body=None):
        if self.dry:
            print(f"  DRY RUN, would {what}")
            return {"html_url": "(dry run)", "number": 0, "id": 0}
        return self.gh(*args, body=body)

    def issues(self):
        return [i for page in self.gh("--paginate", "--slurp", f"repos/{REPO}/issues?state=all&per_page=100")
                for i in page if "pull_request" not in i]

    def releases(self):
        return [r for page in self.gh("--paginate", "--slurp", f"repos/{REPO}/releases?per_page=100")
                for r in page]

    def build(self, end: str, out: Path):
        r = subprocess.run([sys.executable, str(HERE / "monthly_report.py"), "--end", end,
                            "--out-dir", str(out)], text=True, capture_output=True, encoding="utf-8")
        print(r.stdout, end="")
        if r.returncode:
            sys.exit(f"  monthly_report.py refused, nothing proposed or published:\n{r.stdout}{r.stderr}")

    def commit(self, issue: str, end: str) -> str:
        if self.dry:
            print("  DRY RUN, would commit and push the report")
            return "0" * 40
        names = [f"state_of_x402_{issue}.md", f"state_of_x402_{issue}.json"]
        run = lambda *c: subprocess.run(c, cwd=HERE, check=True)
        run("git", "config", "user.name", "verity-index[bot]")
        run("git", "config", "user.email", "veritylayer@gmail.com")
        run("git", "add", *names)
        run("git", "commit", "-q", "-m", f"State of x402 {issue}", "-m",
            f"Built from the signed snapshots and held 48 hours for review. "
            f"Reproduce: python monthly_report.py --end {end}")
        for _ in range(3):
            if (subprocess.run(["git", "pull", "--rebase", "-q"], cwd=HERE).returncode == 0 and
                    subprocess.run(["git", "push", "-q"], cwd=HERE).returncode == 0):
                return subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True,
                                      text=True, check=True).stdout.strip()
        sys.exit("  push failed three times; the report is not published")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def names(end: str):
    issue = end[:7]
    publish_on = (date.fromisoformat(end) + timedelta(days=HOLD_DAYS)).isoformat()
    return (issue, publish_on, f"state-of-x402-{issue}",
            f"State of x402 {issue} publishes on {publish_on} unless this issue is closed")


def built(ops: Ops, end: str, tmp: Path):
    issue = end[:7]
    ops.build(end, tmp)
    md, js = tmp / f"state_of_x402_{issue}.md", tmp / f"state_of_x402_{issue}.json"
    return md, js, sha(md), sha(js)


def propose(ops: Ops, end: str, published: bool) -> int:
    issue, publish_on, tag, title = names(end)
    if published:
        print(f"  {issue} is already published; nothing to propose.")
        if not ops.dry:
            return 0
    iss = next((i for i in ops.issues() if i["title"] == title), None)
    rel = next((r for r in ops.releases() if r["tag_name"] == tag), None)
    if iss and iss["state"] == "closed":
        print(f"  {issue} was held (its issue is closed); nothing to do.")
        return 0
    if iss and rel:
        print(f"  {issue} is already proposed: {iss['html_url']}")
        return 0
    with tempfile.TemporaryDirectory() as t:
        md, js, h_md, h_js = built(ops, end, Path(t))
        text = md.read_text(encoding="utf-8")
    marker = f"<!-- monthly_publish md_sha256={h_md} json_sha256={h_js} -->"
    if rel:
        m = MARK.search(rel.get("body") or "")
        if not m or (m.group(1), m.group(2)) != (h_md, h_js):
            sys.exit(f"  a draft for {issue} exists but does not match this build; refusing")
    else:
        rel = ops.write(f"create draft release {tag}", "-X", "POST", f"repos/{REPO}/releases", body={
            "tag_name": tag, "target_commitish": "main", "name": f"State of x402 {issue}",
            "body": text + "\n\n" + marker, "draft": True})
    if not iss:
        iss = ops.write(f"open issue '{title}'", "-X", "POST", f"repos/{REPO}/issues", body={
            "title": title,
            "body": (f"The {issue} State of x402 report is built and has passed every check.\n\n"
                     f"The owner can read it here before it goes public: {rel['html_url']}\n"
                     f"(it is a draft, so only people who can write to this repo can open it).\n\n"
                     f"**Close this issue before {publish_on} to stop it.** If it stays open, on "
                     f"{publish_on} the report is rebuilt, required to match that draft byte for "
                     f"byte, and published.")})
    print(f"  proposed {issue}: {iss['html_url']}")
    return 0


def publish(ops: Ops, end: str, published: bool) -> int:
    issue, publish_on, tag, title = names(end)
    if published:
        print(f"  {issue} is already published; nothing to do.")
        if not ops.dry:
            return 0
    iss = next((i for i in ops.issues() if i["title"] == title), None)
    if not iss:
        sys.exit(f"  nothing was proposed for {issue}: the propose run on the 17th did not finish")
    if iss["state"] == "closed" and not published:
        print(f"  {issue} was held by closing {iss['html_url']}; not publishing.")
        return 0
    rel = next((r for r in ops.releases() if r["tag_name"] == tag), None)
    if not rel or not rel.get("draft"):
        sys.exit(f"  no draft release {tag} to publish")
    m = MARK.search(rel.get("body") or "")
    if not m:
        sys.exit(f"  draft {tag} carries no build hash; refusing")
    with tempfile.TemporaryDirectory() as t:
        md, js, h_md, h_js = built(ops, end, Path(t))
        if (h_md, h_js) != (m.group(1), m.group(2)):
            ops.write("comment that the rebuild differs", "-X", "POST",
                      f"repos/{REPO}/issues/{iss['number']}/comments", body={"body": (
                          "Not published: the rebuild on the publish date does not match the draft "
                          "shown for review, byte for byte. Nothing was changed.")})
            sys.exit("  rebuild differs from the reviewed draft; refusing to publish")
        text = md.read_text(encoding="utf-8")
        if not ops.dry:
            shutil.copyfile(md, HERE / md.name)
            shutil.copyfile(js, HERE / js.name)
    head = ops.commit(issue, end)
    file_url = f"https://github.com/{REPO}/blob/main/state_of_x402_{issue}.md"
    rel = ops.write(f"publish release {tag} at {head[:7]}", "-X", "PATCH",
                    f"repos/{REPO}/releases/{rel['id']}", body={
                        "draft": False, "tag_name": tag, "target_commitish": head,
                        "body": text + f"\n\nFiles: {file_url} and its .json. "
                                       f"Reproduce: `python monthly_report.py --end {end}`"})
    ops.write("comment the links", "-X", "POST", f"repos/{REPO}/issues/{iss['number']}/comments",
              body={"body": f"Published: {file_url}\nRelease: {rel['html_url']}"})
    ops.write("close the issue", "-X", "PATCH", f"repos/{REPO}/issues/{iss['number']}",
              body={"state": "closed", "state_reason": "completed"})
    print(f"  published {issue}: {file_url}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["propose", "publish"])
    ap.add_argument("--end", help="last day of the window (default: the 16th of this UTC month)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    end = a.end or datetime.now(timezone.utc).strftime("%Y-%m-16")
    date.fromisoformat(end)
    published = (HERE / f"state_of_x402_{end[:7]}.md").exists()
    ops = Ops(a.dry_run)
    return (propose if a.stage == "propose" else publish)(ops, end, published)


if __name__ == "__main__":
    sys.exit(main())
