#!/usr/bin/env python3
"""release.py - cut a dated version, and notice when one is overdue.

The same scheme as the paper engine's tools/release.py. The version is the
release date, `2026.10.1`: it answers the question a user actually asks
(*how old is this?*), and unlike semver a machine can compute it. No leading
zeros: `plugin.json` is schema-validated, semver forbids them, and
`2026.10.1` is valid semver that orders correctly after `2026.9.30`.

gpm carries the version twice, and `bump` writes both:

    .claude-plugin/plugin.json   "version", which `/plugin update` compares
    bin/gpm                      VERSION=, which `gpm version` and the
                                 upgrade commit message print

tests/test_gpm.py fails if the two ever differ.

It reports; it never updates on its own. `check` says when shipped content
has moved since the last bump, and exits 0 either way: a commit is not a
release. It is not a git hook, because .git/hooks/ does not survive a fresh
clone and would stop silently. Maintainer tooling only: nothing at run time
needs it, so house rule 7 (bash and git only) is untouched.

  python tools/release.py check
  python tools/release.py bump [--version 2026.10.1] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import io
import os
import re
import subprocess
import sys

MANIFEST = os.path.join(".claude-plugin", "plugin.json")
CLI = os.path.join("bin", "gpm")

# What a user receives: a change to any of these should move the version.
CONTENT = ("bin", "lib", "adapters", "skills", ".claude-plugin", "install.sh")

# `git log -S` counts occurrences, and a bump changes the value while leaving
# one "version" line before and after, so -S finds only the commit that
# created the line. -G matches the changed line itself. (Measured in the
# paper engine, 2026-09-09.)
VERSION_PICKAXE = ("-G", r'^ *"version":')

MANIFEST_RE = re.compile(r'("version"\s*:\s*")([^"]*)(")')
CLI_RE = re.compile(r"^(VERSION=)(\S*)$", re.M)


def today_version() -> str:
    now = datetime.date.today()
    return f"{now.year}.{now.month}.{now.day}"


def _read(root: str, rel: str) -> str:
    try:
        with io.open(os.path.join(root, rel), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def versions(root: str) -> tuple:
    """(manifest version, bin/gpm version), "" for one that is missing."""
    m = MANIFEST_RE.search(_read(root, MANIFEST))
    c = CLI_RE.search(_read(root, CLI))
    return (m.group(2) if m else "", c.group(2) if c else "")


def _git(root: str, *argv: str) -> tuple:
    try:
        p = subprocess.run(["git", *argv], cwd=root, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return p.returncode, p.stdout


def _last(root: str, paths: list, pickaxe: tuple = ()) -> str:
    rc, out = _git(root, "log", "-1", "--format=%h", *pickaxe, "--", *paths)
    return out.strip() if rc == 0 else ""


def check(root: str) -> dict:
    """Has shipped content moved since the version last changed?"""
    out = {"state": "unknown", "why": "", "since": []}
    if _git(root, "rev-parse", "--git-dir")[0] != 0:
        out["why"] = "not a git checkout, so there is no history to read"
        return out
    bumped = _last(root, [MANIFEST], VERSION_PICKAXE)
    present = [c for c in CONTENT if os.path.exists(os.path.join(root, c))]
    moved = _last(root, present)
    if not moved:
        out.update(state="current", why="no shipped content committed yet")
        return out
    if not bumped:
        out.update(state="stale", why="the version line has never changed")
        return out
    # By the commit graph, not by date: two commits on one day are ordered.
    if _git(root, "merge-base", "--is-ancestor", moved, bumped)[0] == 0:
        out.update(state="current",
                   why=f"the version last changed at {bumped}, at or after "
                       f"the last shipped-content commit")
        return out
    _, listing = _git(root, "log", "--format=%h %s", f"{bumped}..HEAD",
                      "--", *present)
    out["since"] = [r for r in listing.splitlines() if r.strip()]
    out.update(state="stale",
               why=f"{len(out['since'])} commit(s) of shipped content since "
                   f"the last bump ({bumped})")
    return out


def bump(root: str, version: str = "", dry_run: bool = False) -> dict:
    """Write the version into both files, as text: re-serializing would
    reformat a file a person maintains."""
    out = {"was": versions(root), "version": version or today_version(),
           "written": False, "notes": []}
    new = {}
    for rel, rx in ((MANIFEST, MANIFEST_RE), (CLI, CLI_RE)):
        text = _read(root, rel)
        # Keep everything around the value: group 1 before, group 3 (the
        # manifest's closing quote) after.
        text2, n = rx.subn(lambda m: m.group(1) + out["version"]
                           + (m.group(3) if m.re.groups >= 3 else ""),
                           text, count=1)
        if not n:
            out["notes"].append(f"no version line in {rel}; nothing written")
            return out
        new[rel] = text2
    if out["version"] in out["was"]:
        out["notes"].append(
            f"already {out['version']} - a second release on the same day "
            f"carries the same date. Say so in the commit message instead")
    if not dry_run:
        for rel, text in new.items():
            with io.open(os.path.join(root, rel), "w", encoding="utf-8",
                         newline="\n") as fh:
                fh.write(text)
        out["written"] = True
    return out


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(prog="release.py", description=__doc__.split(
        "\n")[0])
    p.add_argument("cmd", choices=["check", "bump"])
    p.add_argument("--path", default="",
                   help="the repository. Default: the one this file is in")
    p.add_argument("--version", default="", help="instead of today's date")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    root = os.path.abspath(a.path or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))

    if a.cmd == "check":
        m, c = versions(root)
        res = check(root)
        print(f"version: {m or '(none)'}"
              + ("" if m == c else f"  (bin/gpm says {c or 'nothing'}: "
                 "run `python tools/release.py bump`)"))
        print(f"  {res['state'].upper() if res['state'] == 'stale' else res['state']}"
              f" - {res['why']}")
        for row in res["since"][:10]:
            print(f"    {row}")
        if res["state"] == "stale":
            print("  remedy: python tools/release.py bump")
            print("  This is a reminder, not a refusal. A commit is not a release.")
        return 0

    res = bump(root, a.version, a.dry_run)
    verb = "would write" if a.dry_run else "wrote"
    if res["written"] or (a.dry_run and not res["notes"]):
        print(f"{verb} version {res['version']} (was {res['was'][0] or 'none'})"
              f" into {MANIFEST} and {CLI}")
    for note in res["notes"]:
        print(f"  note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
