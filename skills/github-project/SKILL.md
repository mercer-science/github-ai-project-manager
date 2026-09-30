---
name: github-project
description: Put a project folder on GitHub as a private repository and keep it in step at the start and end of every AI session, in Claude Code, Codex or any other CLI. Use when the user wants to connect, back up, sync or put a project on GitHub; when a session opens with a "Project sync:" line; when they ask to keep a file or folder off GitHub, or to put one back ("sync the analysis folder too", "stop ignoring X"); when two computers' copies conflict; or when they want to see what is synced, pending or kept local.
---

# github-project

A thin caller over `gpm`, the command that does the work. You never run git
yourself to do what a `gpm` subcommand does, and you never edit `.gitignore`
lines between gpm's markers by hand: **those lines are the record of the
user's answers.**

## Find `gpm`

Resolve `<gpm>` in this order, and stop at the first hit:

1. `gpm`, if it is on `PATH` (`command -v gpm`)
2. `${CLAUDE_PLUGIN_ROOT}/bin/gpm`, if the harness expands that variable
3. `../../bin/gpm` relative to this skill's own directory

Run it as `bash <gpm> …`, which works on Windows too. If none resolves, say
so and stop.

## Which Command Answers Which Sentence

| The user says | Run |
|---|---|
| "put this on GitHub", "back this project up", "connect this folder" | `connect` (below) |
| "keep `X` off GitHub", "don't sync the raw data" | `keep X` |
| "put `X` on GitHub", "sync the analysis folder too", "stop ignoring `X`" | `include X` |
| "what's waiting?", after a `Project sync:` list | `pending` |
| "is this synced?", "what's kept local?" | `status` |
| "I use Codex here too" | `hooks --cli codex` |
| "stop syncing this" | `disconnect` (the repository stays; say so) |

Paths are relative to the working directory for `keep` and `include`, and
relative to the project for `connect`'s answers.

## Connect

`connect` asks before it creates or commits anything. Run it with what you
know, and read the output:

```bash
bash <gpm> connect "<folder>" [--suggest-data data] [--context "<one sentence>"]
```

**Exit 3 means it needs answers**, and nothing has been committed or created
yet. Each `name:`, `data:` and `old:` line is one question for the user. Ask
them all in one message, then re-run with **every** answer given so far.

**The name.** A repository's name is visible even when the repository is
private, and renaming it later breaks every clone:

> I'll put this on GitHub as a **private** repository named
> **`<proposed>`**. OK, or would you like a different name?

Re-run with `--repo <the name they confirmed>`. Never pass a name the user has
not seen. It goes on the user's own account unless they name an organisation
(`--owner ORG`). **Never pass `--public`** unless the user asked for a public
repository in those words.

**Each `data:` line.** Ask exactly this, filling in the folder and size:

> **`data/`** holds 12.4 GB. Do you want it synced to GitHub, or kept just on
> this computer?
>
> **Recommended: keep it on this computer.** GitHub refuses any file over
> 100 MB, and a repository gets slow long before that. Raw instrument data is
> usually backed up somewhere else already. Kept here, it exists only on this
> computer, so anything that reads it (an analysis, a figure) runs here. I'll
> add it to `.gitignore`. You can put any file or folder back on GitHub later
> by asking.
>
> 1. Keep it on this computer (recommended)
> 2. Sync it to GitHub
> 3. Let me choose folder by folder

If a `context:` line came back, add its sentence after the question as it
stands. It is the caller's context for the user, and it does not change your
recommendation.

Answer 1 is `--keep data`, answer 2 is `--sync data`. Answer 3: list the
folders inside it with their sizes (`du -sh data/*`), ask the same question
for each, and pass one `--keep` or `--sync` per subfolder. That is how
`data/raw/` stays here while `data/analysis/` syncs.

**Each `old:` line** is something the paper engine's old sync kept off GitHub
without asking anyone. Put them to the user together: *"The old sync kept
these off GitHub on its own. Keep them that way?"* Then pass each back
exactly as printed, quoted: `--keep '*.eer'` or `--sync '/data/big map.mrc'`.

**On success** say, in two sentences: it is on GitHub, and from now on it
syncs itself when a session opens and closes. The first time, also say both of
these plainly:

- Data kept on this computer exists only on this computer. Anything that
  reads it runs here.
- If the project is open on two computers at once, the sync can hit a
  conflict. It then stops and says so, and never merges on its own.

**In Codex**, tell the user to approve the project's hooks once when Codex
asks. Until they do, nothing syncs.

### When `connect` Reports a Problem

| Problem | What to do |
|---|---|
| `gh` not installed | Offer to install it (`winget install GitHub.cli` on Windows, `brew install gh` on macOS, `sudo apt install gh` on Linux), then `gh auth login`, then re-run. Or: the user creates an **empty private** repository at github.com/new (no README, no .gitignore, no licence) and you re-run with `--url <its address>` |
| `gh` not logged in | `gh auth login`, then re-run |
| git has no name/email | Offer the two `git config --global` lines with their name and email filled in, then re-run |
| `REFUSED: … OneDrive, Dropbox …` | Explain that two sync tools on one repository corrupt it, and suggest moving the project to an ordinary folder. Pass `--allow-cloud-folder` only if the user insists after hearing that |
| a hook file is not valid JSON | Show the user the error. Do not rewrite their file |
| no Python to merge into an existing hook file | Add the `"hooks"` entries from the named adapter file to it yourself, keeping every other key, then run `status` |

`connect` is safe to re-run. It only adds what is missing.

### In a Cloud Session

A cloud session has no `gh` and cannot create a repository. Ask the user to
create an **empty private** repository at github.com/new, suggesting the name
you would have proposed. Attach it to the session and clone it, then run
`connect` on the clone. The clone already has its remote, so no name is
needed. Push to `main`, not a session branch. Then tell the user the one step
left on their own computer: `git clone` it and open a session there.

## A Session Opens With `Project sync:`

Relay each line to the user. The two that need more than relaying:

**"held back from GitHub"** lists new, large files that nobody has answered
for. They are in no commit and in no `.gitignore`, so nothing has been
decided about them. Put the data question above to the user, for each one,
and run `keep <path>` or `include <path>` with the answer.

**"both changed the same file"** means this computer and GitHub each have
changes to the same file. Nothing was merged or uploaded, and both versions
are safe. Walk the user through it before any other work:

1. `git fetch origin` and `git diff HEAD origin/main --stat` show which files.
2. For each file, show both versions (`git show origin/main:<file>`) and ask
   which to keep: this computer's, GitHub's, or both, combined by you and
   shown to the user before it is saved.
3. `git rebase origin/main`, resolve each file as the user decided,
   `git add` it, and `git rebase --continue`. Then `bash <gpm> sync start`.

Never pick a version for the user, and never force-push.

## Keep and Include

`keep <path>` adds one line to gpm's block in `.gitignore`. If the path was
already on GitHub, gpm says the copy there stays in the repository's history.
Taking it out of history is a separate, destructive step. gpm does not take
it, and you do not offer it unless the user asks.

`include <path>`:

- **Exit 1, `REFUSED`, a file over 100 MB.** Relay why: GitHub rejects the
  push, and every sync after it would fail. The file stays on this computer.
  There is no override, and gpm does not use Git LFS.
- **Exit 2, `NEEDS CONFIRMATION`.** A rule the user wrote (not gpm) ignores
  it. Show them the rule and ask whether to add an exception. Re-run with
  `--yes` only after they agree.
- **Exit 1, "inside an ignored folder".** git cannot un-ignore anything
  inside a folder that `.gitignore` ignores. The user's line has to change;
  show it to them and offer the edit (for example `results/` becomes
  `results/*`).

## Any Other CLI

A CLI without session hooks is wrapped instead:
`gpm run <cli> [args…]` syncs, runs the CLI, and syncs again when it exits,
with no time limit. `connect --cli agents` also writes a block into the
project's `AGENTS.md` telling an agent to run the sync first and last.
