"""Publish a per-file digest line and a per-day digest, so the archive can be externally anchored.

WHY. verify_snapshot.py proves a file is the one that was signed. It cannot prove WHEN, because
the signing key is ours and nothing outside stamps it. Walter's point on #wg-domain-discovery, and
he is right: append-only is currently our discipline rather than a property anyone can check.

The fix he proposed, implemented here as the publishing half:

  1. one line per published file, over the EXACT published bytes:
         sha256:<hex>  <filename>  <snapshot-date>
     Same bytes verify_snapshot.py already hashes, so the two never disagree by construction.

  2. one day-digest: sha256 over that day's lines, sorted, LF-joined.
     That single value is the only thing that needs anchoring. Any individual file's inclusion
     stays checkable from the published lines, so one anchor covers every file of that day.

A third party then fetches the files, recomputes the line digests, recomputes the day-digest,
and reads the anchor's block timestamp. The chain supplies the "when". It does not depend on our
key discipline and it does not require trusting us, which is exactly the gap it exists to close.

DELIBERATELY NOT DOING THE ANCHORING HERE. Writing a transaction is the counterparty's half, and
splitting it that way means our side stays keyless, free and offline.

    python digests.py            # rebuild digests.txt for every snapshot on disk
"""
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).parent
SNAPSHOTS = HERE / "snapshots"
OUT = HERE / "digests.txt"

# Hash the published bytes, never a re-serialisation of them. A digest over anything we
# recomputed would be a digest of our intent rather than of what a stranger can download.
FILES = ("observation.json", "signature.json")


def line_for(path: Path, day: str) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}  {day}"


def day_digest(lines: list[str]) -> str:
    """sha256 over the day's lines, sorted, LF-joined. Sorted so it does not depend on the
    order the filesystem happened to hand them back."""
    return hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()


def main() -> int:
    if not SNAPSHOTS.exists():
        sys.exit("  no snapshots/ directory")
    days = sorted(d for d in SNAPSHOTS.iterdir() if d.is_dir())
    if not days:
        sys.exit("  no snapshots recorded yet")

    out, summary = [], []
    for d in days:
        lines = [line_for(d / f, d.name) for f in FILES if (d / f).exists()]
        if not lines:
            continue
        dd = day_digest(lines)
        out.extend(sorted(lines))
        out.append(f"day-digest:{dd}  {d.name}")
        out.append("")
        summary.append((d.name, len(lines), dd))

    OUT.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")

    print(f"  {len(summary)} day(s), {sum(s[1] for s in summary)} files\n")
    print(f"  {'date':<12} {'files':>5}  day-digest")
    print("  " + "-" * 78)
    for name, n, dd in summary:
        print(f"  {name:<12} {n:>5}  sha256:{dd}")
    print(f"\n  wrote {OUT.name}")
    print("  anchor the day-digest; every file's inclusion stays checkable from the lines above it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
