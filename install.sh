#!/usr/bin/env bash
# Put `gpm` on PATH: the route for a CLI that does not install plugins.
#
#   bash install.sh [--prefix DIR]     default: ~/.local/bin
#
# Writes one small wrapper that runs this checkout's bin/gpm, so a `git pull`
# here upgrades it. A wrapper rather than a symlink, because Git Bash on
# Windows makes a copy when asked for a symlink. Installs nothing else.

set -u
prefix=$HOME/.local/bin
[ "${1:-}" = --prefix ] && prefix=$2

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
mkdir -p "$prefix" || { echo "could not create $prefix" >&2; exit 1; }
cat >"$prefix/gpm" <<WRAP
#!/usr/bin/env bash
exec bash "$here/bin/gpm" "\$@"
WRAP
chmod +x "$prefix/gpm"
echo "Installed: $prefix/gpm -> $here/bin/gpm"

case ":$PATH:" in
  *":$prefix:"*) "$prefix/gpm" version ;;
  *) echo "$prefix is not on PATH. Add this line to ~/.bashrc (or ~/.zshrc), then open a new terminal:"
     echo "  export PATH=\"$prefix:\$PATH\"" ;;
esac
