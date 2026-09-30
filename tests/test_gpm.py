"""The gpm suite: every command, offline, against a bare local remote.

    python tests/test_gpm.py

Needs git and bash, and nothing else: no network, no gh, no GitHub. Each
test builds its projects in a temporary folder with its own git identity, so
the user's global git configuration is never read or written.

The checks follow the spec's §9 list, plus the one measurement the hooks'
design rests on: that `end`'s detached push survives the CLI killing the
hook's process group, which Codex does (codex-rs/hooks command_runner.rs,
ProcessTreeGuard).
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
GPM = os.path.join(REPO, "bin", "gpm")
BASH = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
MB = 1048576

PASSED = FAILED = SKIPPED = 0

# The contract, as the spec and the engine state it. bin/gpm and the adapters
# each carry a copy; test_contracts compares them all to these.
BLOCK_BEGIN = ("# --- github-ai-project-manager: kept on this computer "
               "(the user's answers) ---")
BLOCK_END = "# --- end ---"
CLAUDE_CMD = 'bash "$CLAUDE_PROJECT_DIR/.gpm/sync.sh" {}'
CODEX_CMD = ("bash -c 'd=$(git rev-parse --show-toplevel 2>/dev/null) && "
             "[ -f \"$d/.gpm/sync.sh\" ] && exec bash \"$d/.gpm/sync.sh\" {}; "
             "exit 0'")
CODEX_WIN = ('if exist "%ProgramFiles%\\Git\\bin\\bash.exe" '
             '("%ProgramFiles%\\Git\\bin\\bash.exe" .gpm/sync.sh {0}) else '
             '("%LOCALAPPDATA%\\Programs\\Git\\bin\\bash.exe" .gpm/sync.sh {0})')
LEGACY_CMD = 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/sync.sh" {}'
LEGACY_MARK = "KEPT_NOTE=.git/paper-engine-kept-off"
LEGACY_KEPT_HEADER = ("# Kept off GitHub by the project sync: too large for a "
                      "repository.")


def section(name):
    print(f"\n== {name}")


def check(label, ok, detail=None):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  ok    {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label}")
        if detail is not None:
            print(f"        {str(detail)[:1500]}")


def skip(label, why):
    global SKIPPED
    SKIPPED += 1
    print(f"  skip  {label}: {why}")


class Sandbox:
    """A temporary folder with its own git identity and a bare remote."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="gpm-test-")
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        cfg = os.path.join(self.root, "gitconfig")
        with open(cfg, "w") as fh:
            fh.write("[user]\n\tname = Ada Bell\n\temail = ada@example.org\n"
                     "[init]\n\tdefaultBranch = main\n")
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=cfg,
                        GIT_CONFIG_NOSYSTEM="1", HOME=self.home,
                        GIT_TERMINAL_PROMPT="0")
        for k in ("CLAUDE_PROJECT_DIR", "OneDrive", "OneDriveCommercial",
                  "OneDriveConsumer"):
            self.env.pop(k, None)
        # A test that reached the real gh would create a real repository,
        # so a stub that is never logged in comes first on PATH.
        shim = os.path.join(self.root, "shim")
        os.makedirs(shim)
        with open(os.path.join(shim, "gh"), "w", newline="\n") as fh:
            fh.write("#!/bin/sh\nexit 1\n")
        os.chmod(os.path.join(shim, "gh"), 0o755)
        self.env["PATH"] = shim + os.pathsep + self.env["PATH"]
        self.bare = self.path("remote.git")
        self.git("init", "-q", "--bare", "-b", "main", self.bare, cwd=self.root)

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def project(self, name="EXAMPLE_STUDY"):
        p = self.path(name)
        os.makedirs(p)
        write(p, "plan/README.md", "# Plan\n")
        write(p, "drafts/intro.md", "Draft.\n")
        return p

    def gpm(self, *args, cwd=None, env=None):
        return subprocess.run([BASH, GPM, *args], capture_output=True,
                              text=True, cwd=cwd or self.root,
                              env=env or self.env, stdin=subprocess.DEVNULL)

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              cwd=cwd or self.root, env=self.env)

    def sync(self, proj, verb, env=None):
        return subprocess.run([BASH, os.path.join(proj, ".gpm", "sync.sh"),
                               verb], capture_output=True, text=True,
                              cwd=proj, env=env or self.env)

    def remote_files(self, branch="main"):
        return self.git("-C", self.bare, "ls-tree", "-r", "--name-only",
                        branch).stdout.splitlines()

    def connect(self, proj, *extra):
        return self.gpm("connect", proj, "--url", self.bare, *extra)

    def clean(self):
        shutil.rmtree(self.root, ignore_errors=True)


def write(root, rel, text):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return p


def sized(root, rel, mb):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as fh:
        fh.truncate(int(mb * MB))
    return p


def read(root, rel):
    with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


def block(proj):
    if not os.path.exists(os.path.join(proj, ".gitignore")):
        return []
    text = read(proj, ".gitignore").splitlines()
    if BLOCK_BEGIN not in text:
        return []
    i = text.index(BLOCK_BEGIN)
    j = text.index(BLOCK_END, i)
    return text[i + 1:j]


def out(r):
    return (r.stdout + r.stderr).strip()


def wait_for(pred, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.2)
    return pred()


# ---------------------------------------------------------------------------

def test_contracts():
    section("Pinned contracts")
    gpm = open(GPM, encoding="utf-8").read()
    sync = open(os.path.join(REPO, "lib", "sync.sh"), encoding="utf-8").read()
    check("bin/gpm carries the managed-block markers",
          f'BLOCK_BEGIN="{BLOCK_BEGIN}"' in gpm
          and f'BLOCK_END="{BLOCK_END}"' in gpm)
    check("bin/gpm carries the paper engine's detection strings",
          f'LEGACY_SCRIPT_MARK="{LEGACY_MARK}"' in gpm
          and f'LEGACY_KEPT_HEADER="{LEGACY_KEPT_HEADER}"' in gpm
          and 'LEGACY_SCRIPT=".claude/hooks/sync.sh"' in gpm)

    for name, cmd, win, end_timeout in (
            ("claude-code.json", CLAUDE_CMD, None, 10),
            ("codex.json", CODEX_CMD, CODEX_WIN, 3)):
        with open(os.path.join(REPO, "adapters", name), encoding="utf-8") as fh:
            hooks = json.load(fh)["hooks"]
        start = hooks["SessionStart"]
        check(f"{name}: start on startup|resume, report on clear",
              [g["matcher"] for g in start] == ["startup|resume", "clear"],
              start)
        got = [start[0]["hooks"][0], start[1]["hooks"][0],
               hooks["SessionEnd"][0]["hooks"][0]]
        check(f"{name}: the three hook commands are the pinned strings",
              [h["command"] for h in got]
              == [cmd.format(v) for v in ("start", "report", "end")],
              [h["command"] for h in got])
        if win:
            check(f"{name}: the Windows commands are the pinned strings",
                  [h.get("commandWindows") for h in got]
                  == [win.format(v) for v in ("start", "report", "end")],
                  [h.get("commandWindows") for h in got])
        check(f"{name}: the end hook fits the CLI's limit ({end_timeout}s)",
              got[2]["timeout"] == end_timeout, got[2])

    check("sync.sh holds back at 50 MB a file and 500 MB a folder",
          "HOLD_MB=50" in sync and "HOLD_DIR_MB=500" in sync)
    check("sync.sh carries the header gpm's status and upgrade look for",
          sync.splitlines()[1] == "# github-ai-project-manager sync")

    engine = os.path.join(os.path.dirname(REPO), "paper-engine")
    legacy = os.path.join(engine, "tools", "project_template", "dotfiles")
    if not os.path.isdir(legacy):
        skip("the engine's own files carry the detection strings",
             "no paper-engine checkout beside this one")
        return
    script = open(os.path.join(legacy, "sync.sh"), encoding="utf-8").read()
    settings = json.load(open(os.path.join(legacy, "settings.local.json")))
    cmds = [h["command"] for gs in settings["hooks"].values()
            for g in gs for h in g["hooks"]]
    check("the engine's sync.sh carries the detection mark and kept header",
          LEGACY_MARK in script and LEGACY_KEPT_HEADER in script)
    check("the engine's hook commands are the ones gpm removes",
          sorted(cmds) == sorted(LEGACY_CMD.format(v)
                                 for v in ("start", "report", "end")), cmds)


def test_connect_asks_first():
    section("Connect asks before it creates or commits anything")
    sb = Sandbox()
    try:
        proj = sb.project()
        sized(proj, "data/raw/run1.bin", 40)
        sized(proj, "data/raw/run2.bin", 40)
        sized(proj, "data/raw/run3.bin", 40)
        sized(proj, "scans/a.tif", 30)
        write(proj, "notes/n.md", "n\n")

        r = sb.gpm("connect", proj)
        text = out(r)
        check("with no name and no answers it stops with exit 3", r.returncode == 3, text)
        check("...proposing a private name from the folder",
              "name: example_study (private)" in text, text)
        check("...asking about the folder over 100 MB",
              "data: data/ (holds 120.0 MB)" in text, text)
        check("...and not about a small one", "scans/" not in text, text)
        check("...having committed nothing",
              sb.git("-C", proj, "rev-parse", "-q", "--verify", "HEAD").returncode != 0)
        check("...and having no remote",
              sb.git("-C", proj, "remote").stdout.strip() == "")

        r = sb.gpm("connect", proj, "--repo", "example-study",
                   "--suggest-data", "scans", "--context",
                   "data/ also holds the analysis scripts.")
        text = out(r)
        check("a caller's suggested folder is asked about too",
              "data: scans/ (holds 30.0 MB; the caller says data lives here)" in text, text)
        check("...and the caller's sentence is passed on, not acted on",
              "context: data/ also holds the analysis scripts." in text, text)

        cloud = sb.path("OneDrive - Example University", "proj")
        os.makedirs(cloud)
        r = sb.gpm("connect", cloud, "--url", sb.bare)
        check("a OneDrive folder is refused", r.returncode == 1
              and "REFUSED" in out(r), out(r))
        check("...before anything happens in it",
              not os.path.exists(os.path.join(cloud, ".git")))

        env = dict(sb.env, GIT_CONFIG_GLOBAL=sb.path("empty"))
        open(sb.path("empty"), "w").close()
        noid = sb.project("no_identity")
        r = sb.gpm("connect", noid, "--url", sb.bare, env=env)
        check("with no git identity it says how to set one",
              r.returncode == 1 and "git config --global user.email" in out(r), out(r))
    finally:
        sb.clean()


def test_connect_and_sync():
    section("Connect, the first commit, and the session sync")
    sb = Sandbox()
    try:
        proj = sb.project()
        sized(proj, "data/raw/run1.bin", 60)
        sized(proj, "data/raw/run2.bin", 60)
        write(proj, "data/analysis/fit.R", "x <- 1\n")

        r = sb.connect(proj, "--keep", "data")
        check("connect with an answer and a URL succeeds", r.returncode == 0, out(r))
        pushed = sb.remote_files()
        check("the project reached the remote",
              "plan/README.md" in pushed and ".gpm/sync.sh" in pushed, pushed)
        check("...with both CLIs' hook files",
              ".claude/settings.json" in pushed and ".codex/hooks.json" in pushed, pushed)
        check("the kept folder is not on the remote",
              not any(p.startswith("data/") for p in pushed), pushed)
        first = sb.git("-C", proj, "rev-list", "--max-parents=0", "HEAD").stdout.strip()
        tree = sb.git("-C", proj, "ls-tree", "-r", "--name-only", first).stdout
        check("the first commit already follows the answer",
              "data/" not in tree and ".gitignore" in tree, tree)
        check("the answer is one line in the managed block",
              block(proj) == ["/data/"], block(proj))

        again = sb.connect(proj)
        check("a second connect changes nothing and succeeds",
              again.returncode == 0 and "wrote" not in again.stdout
              and "added" not in again.stdout, out(again))

        # the emergency commit
        write(proj, "plan/left_unsaved.md", "unsaved\n")
        r = sb.sync(proj, "start")
        check("start commits what the last session left",
              "closed before it could save" in r.stdout, r.stdout)
        check("...and pushes it", "plan/left_unsaved.md" in sb.remote_files())
        r = sb.sync(proj, "start")
        check("with nothing to do, start is silent", r.stdout == "", r.stdout)

        # end: commit now, push detached
        write(proj, "drafts/methods.md", "Methods.\n")
        t = time.time()
        r = sb.sync(proj, "end")
        took = time.time() - t
        check("end returns within Codex's 3-second limit", took < 3, f"{took:.2f}s")
        head = sb.git("-C", proj, "log", "-1", "--format=%s").stdout
        check("end committed before returning", head.startswith("Auto-save"), head)
        check("...and the detached push reaches the remote",
              wait_for(lambda: "drafts/methods.md" in sb.remote_files()))

        # a clone on another computer, then the two meet
        other = sb.path("laptop")
        sb.git("clone", "-q", "-b", "main", sb.bare, other)
        write(other, "plan/from_laptop.md", "laptop\n")
        env = dict(sb.env, GPM_NO_DETACH="1")
        sb.sync(other, "end", env=env)
        check("a clone syncs with no gpm installed, from the committed script",
              "plan/from_laptop.md" in sb.remote_files())
        sb.sync(proj, "start")
        check("start brings in the other computer's work",
              os.path.exists(os.path.join(proj, "plan", "from_laptop.md")))

        # the hook commands themselves, run as each CLI runs them
        write(proj, "drafts/hooked.md", "x\n")
        cenv = dict(sb.env, CLAUDE_PROJECT_DIR=proj)
        claude = json.load(open(os.path.join(proj, ".claude", "settings.json")))
        cmd = claude["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        r = subprocess.run([BASH, "-c", cmd], cwd=proj, env=cenv,
                           capture_output=True, text=True)
        check("the Claude Code start hook runs the sync",
              r.returncode == 0 and "closed before it could save" in r.stdout, out(r))
        codex = json.load(open(os.path.join(proj, ".codex", "hooks.json")))
        hook = codex["hooks"]["SessionStart"][0]["hooks"][0]
        write(proj, "drafts/codex.md", "x\n")
        if os.name == "nt":
            # As Codex runs it on Windows: cmd.exe /C "<commandWindows>", the
            # quotes added raw (codex-rs/hooks command_runner.rs build_command).
            r = subprocess.run('cmd.exe /C "' + hook["commandWindows"] + '"',
                               cwd=proj, env=sb.env, capture_output=True, text=True)
            check("the Codex Windows start hook runs the sync through cmd.exe",
                  r.returncode == 0 and "closed before it could save" in r.stdout, out(r))
        else:
            # As Codex runs it on Unix: $SHELL -lc "<command>".
            sub = os.path.join(proj, "drafts")
            r = subprocess.run(["/bin/sh", "-lc", hook["command"]], cwd=sub,
                               env=sb.env, capture_output=True, text=True)
            check("the Codex start hook finds the project from a subfolder",
                  r.returncode == 0 and "closed before it could save" in r.stdout, out(r))
            r = subprocess.run(["/bin/sh", "-lc", hook["command"]], cwd=sb.root,
                               env=sb.env, capture_output=True, text=True)
            # A login shell may print its own profile's noise; the sync
            # itself must print nothing.
            check("...and outside any project it does nothing and exits 0",
                  r.returncode == 0 and "Project sync" not in out(r), out(r))

        r = sb.gpm("status", cwd=proj)
        check("status names the remote, the kept folder and both hooks",
              sb.bare in r.stdout and "/data/" in r.stdout
              and "claude codex" in r.stdout, r.stdout)
    finally:
        sb.clean()


def test_detached_push_survives_group_kill():
    section("The detached push outlives the hook's process group")
    if os.name == "nt":
        skip("process-group kill", "POSIX only; Windows kills a job object "
             "instead, and that is measured on a real machine (spec §9)")
        return
    sb = Sandbox()
    try:
        proj = sb.project()
        r = sb.connect(proj)
        check("connected", r.returncode == 0, out(r))
        # A remote that takes a second to accept, so the kill always lands
        # while the push is still running: against a local remote the push
        # can finish first, and a push that would have died looks like one
        # that survived.
        write(sb.bare, "hooks/pre-receive", "#!/bin/sh\nsleep 1\ncat >/dev/null\n")
        os.chmod(os.path.join(sb.bare, "hooks", "pre-receive"), 0o755)
        routes = [("setsid", shutil.which("setsid")),
                  ("perl", shutil.which("perl")), ("nohup", True)]
        for how, present in routes:
            if not present:
                skip(f"the {how} route", f"no {how} here")
                continue
            name = f"drafts/late_{how}.md"
            write(proj, name, "late\n")
            env = dict(sb.env, GPM_DETACH_WITH=how)
            # As Codex runs a hook: a child in its own process group, killed
            # as a group the moment it returns.
            t = time.time()
            p = subprocess.Popen([BASH, os.path.join(proj, ".gpm", "sync.sh"), "end"],
                                 cwd=proj, env=env, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pgid = os.getpgid(p.pid)
            p.wait(timeout=10)
            took = time.time() - t
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            landed = wait_for(lambda: name in sb.remote_files(), 8)
            if how == "nohup":
                check("the nohup fallback dies with the group (so the test "
                      "can tell): the next start pushes it", not landed)
            else:
                check(f"the {how} route: end returns in {took:.2f}s, under 3s",
                      took < 3, took)
                check(f"the {how} route: the push lands after the group is killed",
                      landed, sb.remote_files())
        sb.sync(proj, "start")
        check("the next start pushes what a killed push left",
              "drafts/late_nohup.md" in sb.remote_files())
    finally:
        sb.clean()


def test_conflict_and_offline():
    section("A conflict stops cleanly; offline is a message")
    sb = Sandbox()
    try:
        proj = sb.project()
        check("connected", sb.connect(proj).returncode == 0)
        other = sb.path("laptop")
        sb.git("clone", "-q", "-b", "main", sb.bare, other)
        env = dict(sb.env, GPM_NO_DETACH="1")
        write(other, "drafts/intro.md", "Laptop version.\n")
        sb.sync(other, "end", env=env)
        write(proj, "drafts/intro.md", "Desk version.\n")
        sb.sync(proj, "end", env=env)
        r = sb.sync(proj, "start")
        check("both computers changed one file: start says so",
              "both changed the same file" in r.stdout, r.stdout)
        check("...leaves no rebase half-done",
              not os.path.exists(os.path.join(proj, ".git", "rebase-merge"))
              and not os.path.exists(os.path.join(proj, ".git", "rebase-apply")))
        check("...keeps this computer's version",
              read(proj, "drafts/intro.md") == "Desk version.\n")
        check("...and GitHub's",
              sb.git("-C", sb.bare, "show", "main:drafts/intro.md").stdout
              == "Laptop version.\n")

        sb.git("-C", proj, "remote", "set-url", "origin", sb.path("gone.git"))
        write(proj, "drafts/offline.md", "x\n")
        r = sb.sync(proj, "start")
        check("offline, start commits and says it will sync next time",
              "could not reach GitHub" in r.stdout
              and "offline.md" in sb.git("-C", proj, "show", "--stat", "HEAD").stdout,
              r.stdout)
    finally:
        sb.clean()


def test_hold_back():
    section("A large new file is held back and asked about, never ignored")
    sb = Sandbox()
    try:
        proj = sb.project()
        check("connected", sb.connect(proj).returncode == 0)
        gi_path = os.path.join(proj, ".gitignore")
        gi_before = read(proj, ".gitignore") if os.path.exists(gi_path) else None
        sized(proj, "results/big map.mrc", 60)
        for i in range(5):
            sized(proj, f"movies/m{i}.tif", 55)
        write(proj, "drafts/more.md", "more\n")
        env = dict(sb.env, GPM_NO_DETACH="1")
        sb.sync(proj, "end", env=env)
        pushed = sb.remote_files()
        check("the rest of the change is committed and pushed",
              "drafts/more.md" in pushed, pushed)
        check("the large file and the folder of them are held back",
              not any(p.startswith("movies/") or p == "results/big map.mrc"
                      for p in pushed), pushed)
        check(".gitignore is untouched: nothing was decided",
              (read(proj, ".gitignore") if os.path.exists(gi_path) else None)
              == gi_before)
        pending = read(proj, ".git/gpm-pending")
        check("both are listed in .git/gpm-pending, the folder as one line",
              "results/big map.mrc" in pending and "movies/" in pending
              and "m0.tif" not in pending, pending)
        r = sb.sync(proj, "start")
        check("the next start asks about them",
              "held back from GitHub" in r.stdout and "movies/ (275.0 MB)" in r.stdout
              and "gpm keep" in r.stdout, r.stdout)
        r = sb.gpm("pending", cwd=proj)
        check("gpm pending lists them", "results/big map.mrc" in r.stdout, r.stdout)

        r = sb.gpm("keep", "movies", cwd=proj)
        check("keep answers for the folder", r.returncode == 0
              and block(proj) == ["/movies/"], out(r))
        r = sb.gpm("include", "results/big map.mrc", cwd=proj)
        check("include answers for the file and commits it",
              r.returncode == 0 and "results/big map.mrc" in
              sb.git("-C", proj, "ls-files").stdout, out(r))
        check("nothing is pending after both answers",
              not os.path.exists(os.path.join(proj, ".git", "gpm-pending"))
              and "Nothing is waiting" in sb.gpm("pending", cwd=proj).stdout)
    finally:
        sb.clean()


def test_keep_and_include():
    section("keep and include: the user's answers, later")
    sb = Sandbox()
    try:
        proj = sb.project()
        write(proj, "data/analysis/fit.R", "x <- 1\n")
        write(proj, "data/raw/r.csv", "1,2\n")
        write(proj, "secret/key.txt", "k\n")
        write(proj, ".gitignore", "*.log\nsecret/\nbuild/*\n")
        write(proj, "debug.log", "log\n")
        write(proj, "build/out/o.txt", "o\n")
        check("connected", sb.connect(proj, "--keep", "data").returncode == 0)

        r = sb.gpm("include", "data/analysis", cwd=proj)
        check("include under a kept folder opens just that subfolder",
              r.returncode == 0
              and block(proj) == ["/data/*", "!/data/analysis/"], block(proj))
        files = sb.git("-C", proj, "ls-files").stdout.splitlines()
        check("...which is committed while the rest stays here",
              "data/analysis/fit.R" in files and "data/raw/r.csv" not in files, files)

        r = sb.gpm("include", "data", cwd=proj)
        check("include on the folder itself removes gpm's lines for it",
              r.returncode == 0 and "data/raw/r.csv" in
              sb.git("-C", proj, "ls-files").stdout, out(r) + str(block(proj)))

        r = sb.gpm("include", "debug.log", cwd=proj)
        check("a rule gpm did not write needs a yes first (exit 2)",
              r.returncode == 2 and ".gitignore line 1: *.log" in r.stdout, out(r))
        check("...and nothing changed", "debug.log" not in
              sb.git("-C", proj, "ls-files").stdout)
        r = sb.gpm("include", "debug.log", "--yes", cwd=proj)
        check("with --yes it adds an exception in gpm's block",
              r.returncode == 0 and "!/debug.log" in block(proj)
              and "debug.log" in sb.git("-C", proj, "ls-files").stdout, out(r))
        check("...and the user's own line is untouched",
              read(proj, ".gitignore").startswith("*.log\nsecret/\nbuild/*\n"))
        r = sb.gpm("include", "secret/key.txt", "--yes", cwd=proj)
        check("inside a folder the user ignores, it refuses and says why",
              r.returncode == 1 and "cannot un-ignore anything inside an ignored folder"
              in r.stdout and "!/secret/key.txt" not in block(proj), out(r))

        sized(proj, "data/huge.bin", 101)
        r = sb.gpm("include", "data/huge.bin", cwd=proj)
        check("include refuses a file over 100 MB", r.returncode == 1
              and "REFUSED" in r.stdout and "data/huge.bin" in r.stdout, out(r))
        r = sb.gpm("include", "data", cwd=proj)
        check("...and a folder holding one", r.returncode == 1, out(r))
        os.remove(os.path.join(proj, "data", "huge.bin"))

        r = sb.gpm("keep", "drafts/intro.md", cwd=proj)
        files = sb.git("-C", proj, "ls-files").stdout.splitlines()
        check("keep untracks a tracked file", r.returncode == 0
              and "drafts/intro.md" not in files
              and os.path.exists(os.path.join(proj, "drafts", "intro.md")), out(r))
        check("...says the copy on GitHub stays in its history",
              "stays in the repository's history" in r.stdout, r.stdout)
        check("...and records the answer", "/drafts/intro.md" in block(proj))
        write(proj, "plan/scratch.md", "s\n")
        r = sb.gpm("keep", "scratch.md", cwd=os.path.join(proj, "plan"))
        check("a path typed in a subfolder is taken from that subfolder",
              r.returncode == 0 and "/plan/scratch.md" in block(proj), out(r))
        r = sb.gpm("keep", "../../elsewhere", cwd=os.path.join(proj, "plan"))
        check("...and one outside the project is refused",
              r.returncode == 1 and "not inside the project" in out(r), out(r))
    finally:
        sb.clean()


LEGACY_SETTINGS = {
    "permissions": {"allow": ["Bash(Rscript:*)", "Bash(python:*)"], "deny": []},
    "hooks": {
        "SessionStart": [
            {"matcher": "startup|resume", "hooks": [
                {"type": "command", "command": LEGACY_CMD.format("start"), "timeout": 60}]},
            {"matcher": "clear", "hooks": [
                {"type": "command", "command": LEGACY_CMD.format("report"), "timeout": 10}]}],
        "SessionEnd": [{"hooks": [
            {"type": "command", "command": LEGACY_CMD.format("end"), "timeout": 30}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "echo mine"}]}],
    },
    "model": "opus",
}

LEGACY_GITIGNORE = """# OS
.DS_Store

.claude/*
!.claude/settings.local.json
!.claude/hooks/

# Raw instrument data stays on the computer that collected it: GitHub refuses
# a file over 100 MB and a repository slows long before that.
*.eer
*.dm4
*.mrcs

{header}
# Each stays on the computer it was made on. Delete a line to put it on GitHub.
/data/raw/movies/
/data/big map.mrc
""".format(header=LEGACY_KEPT_HEADER)


def test_take_over_from_engine():
    section("Taking over from the paper engine's own sync")
    sb = Sandbox()
    try:
        proj = sb.project()
        write(proj, ".claude/hooks/sync.sh",
              "#!/usr/bin/env bash\n# Keeps this project in step\n"
              f"{LEGACY_MARK}\n")
        settings_text = json.dumps(LEGACY_SETTINGS, indent=2) + "\n"
        write(proj, ".claude/settings.local.json", settings_text)
        write(proj, ".gitignore", LEGACY_GITIGNORE)
        sized(proj, "data/raw/movies/m0.tif", 5)
        sized(proj, "data/big map.mrc", 101)
        write(proj, "data/x.mrcs", "s")
        sb.git("init", "-q", "-b", "main", cwd=proj)

        r = sb.connect(proj)
        text = out(r)
        check("the old sync's lines are put to the user, each one",
              r.returncode == 3 and all(f"old: {l} " in text for l in (
                  "*.eer", "*.dm4", "*.mrcs", "/data/raw/movies/",
                  "/data/big map.mrc")), text)
        check("...and nothing was touched yet",
              read(proj, ".claude/settings.local.json") == settings_text
              and os.path.exists(os.path.join(proj, ".claude", "hooks", "sync.sh")))

        r = sb.connect(proj, "--keep", "*.eer", "--keep", "*.dm4",
                       "--sync", "*.mrcs", "--keep", "/data/raw/movies/",
                       "--sync", "/data/big map.mrc")
        check("connect takes over", r.returncode == 0, out(r))
        check("the kept lines move into the managed block; the 101 MB one stays kept",
              block(proj) == ["*.eer", "*.dm4", "/data/raw/movies/",
                              "/data/big map.mrc"], block(proj))
        check("...and the user is told why", "over 100 MB" in r.stdout, r.stdout)
        gi = read(proj, ".gitignore")
        check("the old sync's lines and comments are gone from outside the block",
              "Raw instrument data" not in gi and LEGACY_KEPT_HEADER not in gi
              and "!.claude/hooks/" not in gi and "*.mrcs" not in gi, gi)
        check("the user's own lines stay",
              gi.startswith("# OS\n.DS_Store\n\n.claude/*\n!.claude/settings.local.json\n"), gi)
        check("a line the user chose to sync lets its files through",
              "data/x.mrcs" in sb.remote_files())
        after = json.load(open(os.path.join(proj, ".claude", "settings.local.json")))
        want = json.loads(settings_text)
        for ev in ("SessionStart", "SessionEnd"):
            del want["hooks"][ev]
        check("the old hooks are gone and every other key is unchanged",
              after == want, after)
        check("...byte for byte in the engine's own format",
              read(proj, ".claude/settings.local.json")
              == json.dumps(want, indent=2) + "\n")
        check("the old script is deleted",
              not os.path.exists(os.path.join(proj, ".claude", "hooks", "sync.sh")))
        pushed = sb.remote_files()
        check("gpm's own hook file reaches GitHub past .claude/*",
              ".claude/settings.json" in pushed and ".gpm/sync.sh" in pushed, pushed)
    finally:
        sb.clean()


def test_upgrade_hooks_disconnect():
    section("upgrade, hooks into an existing file, and disconnect")
    sb = Sandbox()
    try:
        proj = sb.project()
        mine = {"permissions": {"allow": ["Bash(ls:*)"]},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}]}}
        write(proj, ".claude/settings.json", json.dumps(mine, indent=2) + "\n")
        check("connected", sb.connect(proj).returncode == 0)
        s = json.load(open(os.path.join(proj, ".claude", "settings.json")))
        check("gpm's hooks are merged into the user's settings, which keep theirs",
              s["permissions"] == mine["permissions"]
              and s["hooks"]["Stop"] == mine["hooks"]["Stop"]
              and s["hooks"]["SessionEnd"][0]["hooks"][0]["command"]
              == CLAUDE_CMD.format("end"), s)

        hook_files = {f: read(proj, f) for f in (".claude/settings.json",
                                                 ".codex/hooks.json")}
        write(proj, ".gpm/sync.sh", "# an old version\n")
        r = sb.gpm("status", cwd=proj)
        check("status notices an out-of-date sync script",
              "gpm upgrade" in r.stdout, r.stdout)
        r = sb.gpm("upgrade", cwd=proj)
        check("upgrade restores the installed sync.sh",
              r.returncode == 0 and read(proj, ".gpm/sync.sh")
              == open(os.path.join(REPO, "lib", "sync.sh")).read(), out(r))
        check("...and never touches a hook command",
              all(read(proj, f) == t for f, t in hook_files.items()))

        r = sb.gpm("disconnect", cwd=proj)
        check("disconnect succeeds", r.returncode == 0, out(r))
        s = json.load(open(os.path.join(proj, ".claude", "settings.json")))
        check("...leaving the user's settings exactly as they were", s == mine, s)
        check("...removing the Codex file gpm wrote and .gpm/",
              not os.path.exists(os.path.join(proj, ".codex"))
              and not os.path.exists(os.path.join(proj, ".gpm")))
        check("...and keeping the repository and its remote",
              sb.git("-C", proj, "remote", "get-url", "origin").stdout.strip() == sb.bare)
        check("...with the removal pushed", ".gpm/sync.sh" not in sb.remote_files())
    finally:
        sb.clean()


def test_run():
    section("gpm run: the route for any CLI")
    sb = Sandbox()
    try:
        proj = sb.project()
        check("connected", sb.connect(proj, "--cli", "agents").returncode == 0)
        check("--cli agents writes the AGENTS.md block, and no hook files",
              "bash .gpm/sync.sh start" in read(proj, "AGENTS.md")
              and not os.path.exists(os.path.join(proj, ".claude")))
        fake = write(sb.root, "bin/fake-cli",
                     "#!/usr/bin/env bash\necho edited > drafts/by_cli.md\nexit 7\n")
        os.chmod(fake, 0o755)
        r = sb.gpm("run", fake, cwd=proj)
        check("run passes the CLI's exit status through", r.returncode == 7, out(r))
        check("...and has pushed its work before returning",
              "drafts/by_cli.md" in sb.remote_files(), out(r))
    finally:
        sb.clean()


def main():
    print("gpm suite - github-ai-project-manager")
    if not shutil.which("git") or not os.path.exists(BASH):
        print("git and bash are required")
        return 1
    test_contracts()
    test_connect_asks_first()
    test_connect_and_sync()
    test_detached_push_survives_group_kill()
    test_conflict_and_offline()
    test_hold_back()
    test_keep_and_include()
    test_take_over_from_engine()
    test_upgrade_hooks_disconnect()
    test_run()
    print(f"\n{PASSED}/{PASSED + FAILED} passed"
          + (f", {FAILED} FAILED" if FAILED else "")
          + (f", {SKIPPED} skipped" if SKIPPED else ""))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
