#!/usr/bin/env bash
# github-ai-project-manager sync
#
# Keeps this project in step with its GitHub repository, so the work done on
# one computer is waiting on the other. The hooks `gpm connect` installed run
# it at the start and end of every AI session; `gpm run <cli>` runs it around
# a CLI that has no hooks. It never needs running by hand, and it needs
# nothing but git and bash: a clone works on a computer that has never
# installed gpm.
#
#   sync.sh start   a session opened: commit whatever the last session left
#                   unsaved, say what is waiting for an answer, bring in
#                   GitHub's copy, then send this one up
#   sync.sh end     a session closed: commit, then start `push` detached and
#                   return at once. Codex allows a closing hook 3 seconds and
#                   Claude Code 1.5 by default, and neither is enough to push
#   sync.sh push    send the commits up. `end` runs it detached; if it is
#                   killed, nothing is lost - the next `start` pushes
#   sync.sh report  say what is waiting for an answer, and nothing else (the
#                   session /clear opens, while `push` may still be running)
#
# Closing the terminal window can kill the CLI before `end` runs at all,
# which is why `start` commits first: nothing typed is lost, it only goes up
# a session late.
#
# Nothing is ever ignored here. A new file of HOLD_MB or more, a new folder
# whose new files add up to HOLD_DIR_MB or more, and a new data file of any
# size (DATA_EXT) are HELD BACK: left out of the commit and listed in
# .git/gpm-pending, and the next session opens by asking the user about them.
# Data is assumed to stay on this computer until the user says otherwise, and
# one file over 100 MB makes GitHub refuse the whole push, so committing it
# would stop everything else reaching GitHub; holding it back decides nothing
# about it. The user's answers live in the marked block in .gitignore (kept
# here) and in SYNCED (folders whose new data syncs without asking), which
# `gpm keep` and `gpm include` write.
#
# Silent when there is nothing to say. What `start` and `report` print is read
# by the agent at the top of the session, so a problem is reported rather than
# lost. Every path exits 0: a sync that cannot run must never stop a session
# opening.

HOLD_MB=50
HOLD_DIR_MB=500
PENDING=.git/gpm-pending
SYNCED=.gpm/synced-data
# What counts as data, by extension, case-insensitive. It decides when to
# ask, never what the answer is, and says nothing about what the project is.
DATA_EXT="csv tsv xls xlsx xlsm ods parquet feather arrow avro orc jsonl ndjson
  h5 hdf5 hdf he5 nc nc4 cdf npy npz mat pkl pickle joblib rds rda rdata sav dta
  sas7bdat sqlite sqlite3 db duckdb tif tiff mrc mrcs eer dm3 dm4 ser emd nd2
  czi lif lsm ims dcm nii fcs fastq fq fasta fa fna bam sam cram vcf bcf bed
  bigwig bw gff gtf zip tar gz tgz bz2 xz zst 7z rar mp4 mov avi mkv wav flac
  bin dat raw pt pth ckpt safetensors onnx"
LAST=.git/gpm-last-sync

say() { echo "Project sync: $*"; }
stamp() { printf '%s\t%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" "$2" >"$LAST" 2>/dev/null; }

# "<bytes>\t<path>" for every file outside .git. GNU find prints both in one
# process; BSD find (macOS) has no -printf, so it batches stat with `+`.
sizes() {
  if find . -maxdepth 0 -printf '' >/dev/null 2>&1; then
    find . -path ./.git -prune -o -type f -printf '%s\t%P\n' 2>/dev/null
  else
    find . -path ./.git -prune -o -type f -exec stat -f '%z%t%N' {} + 2>/dev/null |
      awk 'BEGIN { FS = OFS = "\t" } { sub(/^\.\//, "", $2); print }'
  fi
}

# "<bytes>\t<path>\t<kind>" for every new, not-yet-ignored file. kind is
# "data" for a data file that no answer in SYNCED covers, and "-" otherwise.
# One `find` and one `awk` whatever the file count: a per-file `stat` costs a
# process each, and Git Bash on Windows spawns slowly enough that a folder of
# movies would outlast the hook's time limit.
new_files() {
  local others synced=/dev/null
  others=$(mktemp) || return 0
  [ -f "$SYNCED" ] && synced=$SYNCED
  git -c core.quotePath=false ls-files --others --exclude-standard \
    >"$others" 2>/dev/null
  if [ -s "$others" ]; then
    sizes |
      awk -F'\t' -v exts="$DATA_EXT" '
        BEGIN {
          n = split(exts, e, /[ \n]+/)
          for (i = 1; i <= n; i++) if (e[i] != "") ext[e[i]] = 1
        }
        FILENAME == ARGV[1] { new[$0] = 1; next }
        FILENAME == ARGV[2] {
          sub(/\r$/, ""); sub(/\/$/, ""); if ($0 != "") ok[$0] = 1; next
        }
        !($2 in new) { next }
        {
          kind = "-"
          b = tolower($2); sub(/.*\//, "", b)
          if (index(b, ".") > 1) {
            x = b; sub(/.*\./, "", x)
            if (x in ext) {
              kind = "data"
              for (s in ok) if ($2 == s || index($2, s "/") == 1) { kind = "-"; break }
            }
          }
          print $1 "\t" $2 "\t" kind
        }' "$others" "$synced" -
  fi
  rm -f "$others"
}

# Every new path to hold back, as "<bytes>\t<path>", a folder ending in "/":
# too large, or data nobody has said to sync.
held_back() {
  new_files |
    awk -F'\t' -v F=$((HOLD_MB * 1048576)) -v D=$((HOLD_DIR_MB * 1048576)) '
      {
        n = split($2, part, "/"); d = ""
        for (i = 1; i < n; i++) { d = d part[i] "/"; tot[d] += $1 }
        if ($1 >= F || $3 == "data") hold[$2] = $1
      }
      END {
        # The deepest folders over the limit, so a movie folder is asked
        # about without taking the whole data/ tree with it.
        for (d in tot) if (tot[d] >= D) over[d] = 1
        for (d in over) {
          deepest = 1
          for (e in over) if (e != d && index(e, d) == 1) { deepest = 0; break }
          if (deepest) pick[d] = tot[d]
        }
        for (p in hold) {
          inside = 0
          for (d in pick) if (index(p, d) == 1) { inside = 1; break }
          if (inside) continue
          par = p; sub(/[^\/]*$/, "", par)
          count[par]++; loose[p] = par
        }
        # Five held files side by side is a data folder, not five
        # questions: one question about the folder.
        for (p in loose) {
          par = loose[p]
          if (par != "" && count[par] >= 5) pick[par] = tot[par]
          else print hold[p] "\t" p
        }
        for (d in pick) print pick[d] "\t" d
      }' | sort -t "$(printf '\t')" -k2
}

# Commit everything except what is held back. Returns 1 when there was
# nothing to commit.
save() {
  local list size path
  local -a skip=()
  list=$(held_back)
  : >"$PENDING"
  if [ -n "$list" ]; then
    printf '%s\n' "$list" >"$PENDING"
    while IFS=$'\t' read -r size path; do
      [ -n "$path" ] && skip+=(":(top,exclude,literal)${path%/}")
    done <<<"$list"
  else
    rm -f "$PENDING"
  fi
  git add -A -- . "${skip[@]}" >/dev/null 2>&1 || return 1
  git diff --cached --quiet && return 1
  git commit -q -m "$1 $(date '+%Y-%m-%d %H:%M')" >/dev/null 2>&1
}

report_pending() {
  [ -s "$PENDING" ] || return 0
  say "these are new data or large files, so they were held back from GitHub and nothing has been decided about them:"
  awk -F'\t' '{
    s = $1 / 1024; u = "KB"
    if (s >= 1024) { s /= 1024; u = "MB" }
    if (s >= 1024) { s /= 1024; u = "GB" }
    printf "  - %s (%.1f %s)\n", $2, s, u
  }' "$PENDING"
  echo "  Ask the user, for each one, whether to sync it to GitHub or keep it on this computer only (recommend keeping it here). Then run \`gpm keep <path>\` or \`gpm include <path>\`. Until they answer, it stays out of every commit; new data is never uploaded unasked."
}

has_remote() { git remote get-url origin >/dev/null 2>&1; }

push() {
  has_remote || return 1
  git push -q -u origin HEAD >/dev/null 2>&1
}

# Start `push` in a session of its own. The CLI kills the hook's process
# group when the hook returns (Codex does, measured from its source), so a
# plain `&` or `nohup` would die with it. macOS has no `setsid` command, and
# perl ships with it. The hook does not return until the child says it is out
# of the group: returning first is a race the kill can win.
detach_push() {
  local ready i how=${GPM_DETACH_WITH:-}
  ready=$(mktemp) || return 0
  rm -f "$ready"
  if [ -z "$how" ]; then
    if command -v setsid >/dev/null 2>&1; then how=setsid
    elif command -v perl >/dev/null 2>&1; then how=perl
    else how=nohup
    fi
  fi
  case $how in
    setsid) GPM_READY=$ready setsid bash "$here/sync.sh" push </dev/null >/dev/null 2>&1 & ;;
    perl) GPM_READY=$ready perl -MPOSIX=setsid -e 'fork and exit; setsid; exec @ARGV' \
            bash "$here/sync.sh" push </dev/null >/dev/null 2>&1 & ;;
    *) GPM_READY=$ready nohup bash "$here/sync.sh" push </dev/null >/dev/null 2>&1 & ;;
  esac
  for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    [ -e "$ready" ] && break
    sleep 0.1
  done
  rm -f "$ready"
}

main() {
  # The project is the folder this script's folder sits in (<project>/.gpm/),
  # whatever the CLI's working directory is and whatever it calls its
  # project-directory variable, if it has one.
  here=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd) || return 0
  cd "$here/.." || return 0

  # Only a project that is its own repository. A project folder sitting
  # inside some other repository must not commit into that one.
  [ -e .git ] || return 0

  case "$1" in
  start)
    if [ -z "$(git config user.email)" ]; then
      say "git does not know your name and email on this computer, so nothing can be saved. Ask the agent to set them up."
      stamp start "no git identity"
      return 0
    fi
    if ! git rev-parse -q --verify HEAD >/dev/null; then
      save "Project created"
    elif save "Auto-save (left unsaved by the last session)"; then
      say "the last session closed before it could save. Its changes are committed now."
    fi
    report_pending
    if ! has_remote; then
      say "this project is not connected to a GitHub repository yet, so it is saved on this computer only."
      stamp start "no remote"
      return 0
    fi
    branch=$(git symbolic-ref --short HEAD 2>/dev/null) || return 0
    if ! git fetch -q origin >/dev/null 2>&1; then
      say "could not reach GitHub (offline?). Working from this computer's copy; it will sync next time."
      stamp start "offline"
      return 0
    fi
    if git rev-parse -q --verify "origin/$branch" >/dev/null; then
      if ! git rebase -q "origin/$branch" >/dev/null 2>&1; then
        git rebase --abort >/dev/null 2>&1
        say "this computer and GitHub both changed the same file since the last sync, so nothing was merged or uploaded. Both versions are safe. Ask the agent to walk you through keeping one, the other, or both, before starting work."
        stamp start "conflict"
        return 0
      fi
    fi
    if push; then
      stamp start "synced"
    else
      say "could not upload to GitHub. Everything is saved on this computer and will go up next time."
      stamp start "push failed"
    fi
    ;;
  end)
    [ -n "$(git config user.email)" ] || return 0
    save "Auto-save"
    stamp end "committed"
    if has_remote; then
      if [ -n "$GPM_NO_DETACH" ]; then push; else detach_push; fi
    fi
    ;;
  push)
    # `end` waits for this before it returns (see detach_push).
    [ -n "${GPM_READY:-}" ] && : >"$GPM_READY"
    if push; then stamp push "pushed"; else stamp push "push failed"; fi
    ;;
  report)
    report_pending
    ;;
esac
}

# gpm loads this file for held_back and new_files, so the rules for what is
# held back live in one place; run as a script, it syncs.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
  exit 0
fi
