# GitHub AI Project Manager

Keep a project folder on GitHub as a private repository, synced at the start
and end of every AI coding session, in Claude Code, Codex or any other CLI.

- **One command to connect.** `gpm connect <folder>` makes the folder a
  private repository and syncs it. It asks for the repository's name and
  about each large data folder first.
- **It syncs itself.** When a session opens, it commits whatever the last
  session left unsaved, brings in the other computer's work, and pushes. When
  a session closes, it commits and pushes. Closing the terminal window loses
  nothing: the next session commits it.
- **Your data is your decision.** Nothing is kept off GitHub, or put on it,
  without your answer. A large file that appears later is held back until you
  have answered for it. You can put anything back on GitHub later by asking.
- **Nothing but git.** `gpm` is a bash script. Git for Windows ships bash, so
  there is nothing else to install. A clone keeps syncing on a computer that
  has never installed `gpm`.

## Install

**Claude Code**

```
/plugin marketplace add mercer-science/github-ai-project-manager
/plugin install github-ai-project-manager
```

Then ask: *"put this project on GitHub"*.

**Codex** reads the same plugin manifest. Its marketplace command will be
listed here once it has been tested on a released Codex. Until then, use the
route below. Codex will ask you to approve the project's hooks once; nothing
syncs until you do.

**Any other CLI**, or without a plugin:

```bash
git clone https://github.com/mercer-science/github-ai-project-manager
bash github-ai-project-manager/install.sh      # puts gpm on PATH
gpm connect ~/projects/my-project
gpm run <your-cli>                              # sync, run it, sync again
```

You need **git**, and a GitHub login for it. Creating the repository for you
also needs the [GitHub CLI](https://cli.github.com) (`gh auth login`).
Without it, create an empty private repository at github.com/new and pass
`--url <its address>`.

## What to Say

| Say | It runs |
|---|---|
| "Put this project on GitHub" | `gpm connect` |
| "Keep the raw data off GitHub" | `gpm keep data/raw` |
| "Sync the analysis folder too" / "stop ignoring X" | `gpm include data/analysis` |
| "What's waiting for an answer?" | `gpm pending` |
| "Is this synced?" | `gpm status` |
| "Stop syncing this project" | `gpm disconnect` (the repository stays) |

## What It Will Not Do

- Create a **public** repository unless you ask for one by name.
- Force-push or rewrite history that is already on GitHub.
- Merge two computers' changes on its own. If both changed the same file, it
  stops, says so, and keeps both versions safe until you choose.
- Put a file over 100 MB on GitHub. GitHub refuses such files, and one in a
  push would stop everything else reaching GitHub. It does not use Git LFS.
- Connect a folder inside OneDrive, Dropbox, iCloud or Google Drive. Two sync
  tools on one repository corrupt it.

## Two Things to Know

- **Data kept on this computer exists only on this computer.** Anything that
  reads it, such as an analysis or a figure, runs here.
- **The same project open on two computers at once** can produce a conflict.
  The sync stops and tells you. Your agent walks you through keeping one
  version, the other, or both.

## How the Sync Fits in a Hook's Time Limit

Codex gives a closing hook at most 3 seconds, and Claude Code 1.5 seconds by
default. That is not enough to push to GitHub. So the closing hook only
commits, which is local and fast. It then starts the push in a process of its
own and returns. If that push is killed, nothing is lost: the next session
pushes it.

## Status

Built 2026-09-30. The offline suite (`python tests/test_gpm.py`) runs on
Linux, macOS and Windows in CI. **Not yet measured on real machines:**
whether the detached push survives each CLI exiting, on Windows and on
Linux/macOS, and whether Codex runs a project's hooks before the project is
marked trusted. Until those are checked, the next session start is the
guaranteed push.

## License

MIT
