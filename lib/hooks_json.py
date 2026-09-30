"""Merge gpm's hooks into a CLI's JSON settings file, or take them out.

gpm is bash, and bash cannot edit JSON safely. When the target file does not
exist, gpm writes the adapter as-is and never calls this. When it does exist,
it belongs to the user, so this edits only the hook entries whose command is
one of gpm's and leaves every other key's value as it was.

    hooks_json.py add    <file> <adapter.json>   add each missing entry
    hooks_json.py remove <file> <command>...     drop entries running these
    hooks_json.py has    <file> <command>...     exit 0 if any is present

Prints one line per change. Exits 1 with the reason when the file is not
valid JSON, and changes nothing.
"""
import json
import os
import sys


def load(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return json.loads(text) if text.strip() else {}


def save(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def commands(data):
    for groups in (data.get("hooks") or {}).values():
        for group in groups or []:
            for hook in group.get("hooks") or []:
                yield hook.get("command")


def add(path, adapter):
    data = load(path) if os.path.exists(path) else {}
    with open(adapter, encoding="utf-8") as fh:
        wanted = json.load(fh)["hooks"]
    hooks = data.setdefault("hooks", {})
    have = set(commands(data))
    added = []
    for event, groups in wanted.items():
        for group in groups:
            if group["hooks"][0]["command"] in have:
                continue
            hooks.setdefault(event, []).append(group)
            added.append(f"{event}({group.get('matcher', 'any')})")
    if added:
        save(path, data)
        print("added hooks: " + ", ".join(added))


def remove(path, drop):
    data = load(path)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return
    removed = 0
    for event in list(hooks):
        kept_groups = []
        for group in hooks[event] or []:
            inner = [h for h in group.get("hooks") or []
                     if h.get("command") not in drop]
            removed += len(group.get("hooks") or []) - len(inner)
            if inner:
                kept_groups.append(dict(group, hooks=inner))
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        del data["hooks"]
    if removed:
        save(path, data)
        print(f"removed {removed} hook(s)")


def main(argv):
    op, path, rest = argv[1], argv[2], argv[3:]
    try:
        if op == "add":
            add(path, rest[0])
        elif op == "remove":
            if os.path.exists(path):
                remove(path, set(rest))
        elif op == "has":
            if not os.path.exists(path):
                return 1
            return 0 if set(commands(load(path))) & set(rest) else 1
    except ValueError as e:
        print(f"{path} is not valid JSON ({e}); it was left as it was.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
