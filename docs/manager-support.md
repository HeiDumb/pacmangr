# Manager Support

`pacmangr` is a TUI wrapper around native package-manager commands. It detects
managers from an internal registry at startup, then enables a manager when all
commands declared by its adapter are available in `PATH`.

Support levels:

- `search`: the manager can contribute to unified search.
- `installed`: the manager can contribute to the installed package view.
- `install/remove/update/info`: actions are exposed when selected packages map
  to those commands.

Install, remove, and update operations are still delegated to the real manager
command, but they run in `pacmangr`'s background queue. For sudo-backed commands,
`pacmangr` asks for the sudo password inside the TUI, validates it, then feeds
it to sudo without logging it.

Search results and installed-package inventory are cached in a local SQLite
database at `~/.cache/pacmangr/pacmangr.sqlite`. Cached installed packages load
at startup before the live refresh finishes. Cached search results appear
immediately for repeated queries, then the native managers run again in the
background and replace stale results.

Version lists are cached in the same database. For Arch packages, `pacmangr`
combines the selected result, installed package metadata, repository metadata,
local pacman/yay/paru cache files, and pacman log history when those sources are
readable. The optional `downgrade` tool is detected so version/downgrade flows
can be exposed cleanly without treating it as a replacement backend.

Cache entries use manager-specific TTLs so slower or remote-heavy lookups do not
block the interface every time. Old cache rows are cleaned automatically.

When multiple selected packages share the same command shape, `pacmangr` batches
them into one native command. Otherwise it queues the native commands one at a
time. The download monitor parses progress, transfer speed, ETA, and recent
output when the manager prints those details.

For AUR helpers such as `yay` and `paru`, background operations pass sudo flags
that make the helper read sudo from stdin. `pacmangr` asks for and validates the
sudo password inside the TUI, then feeds it to the helper process without logging
the password.

For managers whose CLI output is not stable JSON, parsing is conservative and
best-effort. Failed manager commands are logged in the TUI log view.
