#!/usr/bin/env sh
set -eu

prefix=/usr/local

if [ "${1:-}" = "--user" ]; then
  prefix="${HOME}/.local"
elif [ "${1:-}" = "--prefix" ] && [ -n "${2:-}" ]; then
  prefix="$2"
fi

bindir="${prefix}/bin"
datadir="${prefix}/share"
root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
mkdir -p "$bindir"
install -m 755 "$root/pacmangr" "$bindir/pacmangr"
install -m 755 "$root/pacmangr-gui" "$bindir/pacmangr-gui"
install -Dm644 "$root/io.github.hei.pacmangr.desktop" "$datadir/applications/io.github.hei.pacmangr.desktop"
install -Dm644 "$root/assets/io.github.hei.pacmangr.png" "$datadir/icons/hicolor/512x512/apps/io.github.hei.pacmangr.png"
install -Dm644 "$root/assets/pacmangr-exit.png" "$datadir/pacmangr/assets/pacmangr-exit.png"
printf 'installed %s and %s\n' "$bindir/pacmangr" "$bindir/pacmangr-gui"
