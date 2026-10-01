# AGENTS.md — github-ai-project-manager

The contract for any agent working in or with this repository. Claude Code
reads the skill; Codex and other agents read this file.

## What It Is

`gpm` makes a project folder its own **private** GitHub repository and keeps
it in step at the start and end of every AI session. It knows nothing about
what the project is. A caller may suggest where data lives
(`--suggest-data`) and add one sentence of context (`--context`); gpm passes
both to the user and decides nothing from them.

## Layout

```
bin/gpm                   the CLI (bash; needs git and nothing else)
lib/sync.sh               the sync, copied into each project as .gpm/sync.sh
lib/hooks_json.py         merges hooks into an existing JSON settings file;
                          used only when that file already exists
adapters/claude-code.json the hooks block for .claude/settings.json
adapters/codex.json       the hooks block for .codex/hooks.json
skills/github-project/    the one skill: which command answers which sentence
.claude-plugin/           plugin.json + marketplace.json, read by Claude Code and Codex
install.sh                puts gpm on PATH, for any other CLI
tests/test_gpm.py         the suite
```

## Using It From an Agent

Everything is in `skills/github-project/SKILL.md`, and it applies to any
agent, not only Claude Code. It covers finding `gpm`, which sentence maps to
which command, the exact wording of the data question, what exit code 3
means, and how to walk a user through a conflict. In short:

- `gpm connect <folder>` **stops with exit 3** until the user has confirmed
  the repository name and answered for every place data sits, small or
  large. Put every `name:`, `data:` and `old:` line to the user, then re-run
  with every answer (`--keep-all-data` when they want none of it uploaded).
- A session that opens with `Project sync:` lines: relay them. A "held back"
  path gets the data question; the answer is `gpm keep` or `gpm include`.
- Never edit the lines between gpm's markers in `.gitignore` by hand. They
  are the record of the user's answers.

**In a project with no hooks for your CLI**, run `bash .gpm/sync.sh start`
before any other work and relay what it prints, and run
`bash .gpm/sync.sh end` as the last thing you do. Or have the user start you
with `gpm run <cli>`.

## House Rules

These hold for every change to this repository:

1. **Nothing is ignored or un-ignored without the user's answer, and no data
   goes up unasked.** `connect` asks about every place data sits, whatever
   its size. After that, a new data file (by extension, `DATA_EXT` in
   `lib/sync.sh`) or a large new file is *held back* (excluded from the
   commit and listed in `.git/gpm-pending`), never written into `.gitignore`.
   Only a folder the user said to sync (recorded in `.gpm/synced-data`)
   takes new data without asking. The extensions and thresholds (50 MB a
   file, 500 MB a folder) decide when to ask, never what the answer is.
2. **One refusal overrides the user:** a file over 100 MB never goes on
   GitHub, because it would make every later push fail. There is no Git LFS.
3. **No public repository** unless the user asked for one by name. **No
   force-push, no rewriting pushed history**, and no rebase except of the
   sync's own local commits onto `origin`, aborted on conflict.
4. **Every hook path exits 0.** A sync that cannot run reports and never
   stops a session opening.
5. **The hook commands never change.** Codex trusts a hook by the hash of its
   configuration, and a changed command sits untrusted, which is a sync that
   silently stopped. Change `lib/sync.sh` instead; `gpm upgrade` replaces
   the project's copy and leaves the commands alone.
6. **Contracts are pinned.** The hook commands, the `.gitignore` markers, the
   `.gpm/synced-data` path and
   the paper engine's detection strings each have one constant that
   `tests/test_gpm.py` compares with every file that carries a copy. Change
   one, change all, re-run the suite.
7. **bash, git and nothing else at run time.** Python is used only to merge
   into a JSON file that already exists, and its absence is reported, never
   worked around. Use no GNU-only flag without a BSD fallback: macOS ships
   BSD `find`, `sed` and `stat`, and has no `setsid`.

## Before You Finish

```bash
python tests/test_gpm.py
```

It is offline, needs git and bash, and builds everything in a temporary
folder with its own git identity. CI runs it on Linux, macOS and Windows.
