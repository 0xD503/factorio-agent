#!/usr/bin/env python3
"""Make a release: an annotated tag plus archives made with `git archive`.

    python3 tools/release.py --dry-run                     archives of HEAD in dist/, no tag
    python3 tools/release.py 0.1.0 --notes NOTES.md        tag v0.1.0 and build dist/ from it
    python3 tools/release.py 0.1.0 --publish               also push the tag and create a release
                                                           with the archives attached (GitHub `gh`)

Before tagging: the working tree must be clean, fxa.__version__ must equal VERSION, and the
offline tests must pass. Players install from the archives (no git needed): see the user guide.
The archives carry the commit in fxa/_build.py (export-subst), shown by `fx doctor`.
"""

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist"
NAME = "factorio-agent"


def git(*args, capture=True):
    done = subprocess.run(["git", *args], cwd=REPO, capture_output=capture, text=True)
    if done.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{done.stderr}")
    return done.stdout.strip() if capture else ""


def version_in_code():
    text = (REPO / "fxa" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def build(ref, version):
    DIST.mkdir(exist_ok=True)
    prefix = f"{NAME}-{version}/"
    files = []
    for fmt, suffix in (("zip", ".zip"), ("tar.gz", ".tar.gz")):
        out = DIST / f"{NAME}-{version}{suffix}"
        git("archive", f"--format={fmt}", f"--prefix={prefix}", "-o", str(out), ref)
        files.append(out)
    sums = DIST / f"{NAME}-{version}.SHA256SUMS"
    sums.write_text("".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n" for f in files), encoding="utf-8")
    return files + [sums]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", nargs="?")
    parser.add_argument("--notes", help="release notes file (tag message and release body)")
    parser.add_argument("--dry-run", action="store_true", help="build archives of HEAD without tagging")
    parser.add_argument("--publish", action="store_true", help="push the tag and create a GitHub release with gh")
    args = parser.parse_args()

    if args.dry_run:
        version = f"{version_in_code()}+{git('rev-parse', '--short', 'HEAD')}"
        for f in build("HEAD", version):
            print(f"built {f.relative_to(REPO)}")
        return 0

    if not args.version:
        parser.error("give a VERSION, or --dry-run")
    version = args.version
    if version != version_in_code():
        sys.exit(f"fxa/__init__.py says {version_in_code()}; set __version__ = \"{version}\" and commit first")
    if git("status", "--porcelain"):
        sys.exit("the working tree has uncommitted changes")
    tag = f"v{version}"
    if git("tag", "--list", tag):
        sys.exit(f"tag {tag} exists already")
    if subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=REPO).returncode:
        sys.exit("tests failed")
    notes = Path(args.notes).read_text(encoding="utf-8") if args.notes else f"{NAME} {version}"
    git("tag", "-a", tag, "-m", notes)
    files = build(tag, version)
    for f in files:
        print(f"built {f.relative_to(REPO)}")
    print(f"tagged {tag}")
    if args.publish:
        if not shutil.which("gh"):
            sys.exit("gh (GitHub CLI) is not installed: push the tag and upload dist/ by hand")
        git("push", "origin", tag, capture=False)
        cmd = ["gh", "release", "create", tag, *map(str, files), "--title", f"{NAME} {version}"]
        cmd += ["--notes-file", args.notes] if args.notes else ["--notes", notes]
        if subprocess.run(cmd, cwd=REPO).returncode:
            sys.exit("gh release create failed")
    else:
        print(f"to publish: git push origin {tag}, then attach the files in dist/ to a release for {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
