#!/usr/bin/env sh
set -eu

prefix=/usr/local

if [ "${1:-}" = "--user" ]; then
  prefix="${HOME}/.local"
elif [ "${1:-}" = "--prefix" ] && [ -n "${2:-}" ]; then
  prefix="$2"
fi

bindir="${prefix}/bin"
mkdir -p "$bindir"
install -m 755 "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/pacmangr" "$bindir/pacmangr"
printf 'installed %s\n' "$bindir/pacmangr"
