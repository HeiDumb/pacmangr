# Manager Support

`pacmangr` detects managers from an internal registry at startup. A manager is
enabled when all commands declared by its adapter are available in `PATH`.

Support levels:

- `search`: the manager can contribute to unified search.
- `installed`: the manager can contribute to the installed package view.
- `install/remove/update/info`: actions are exposed when selected packages map
  to those commands.

Install, remove, and update operations are still delegated to the real manager
command, but they run in `pacmangr`'s background queue. For sudo-backed commands,
`pacmangr` asks for the sudo password inside the TUI, validates it, then feeds
it to sudo without logging it.

When multiple selected packages share the same command shape, `pacmangr` batches
them into one native command. Otherwise it queues the native commands one at a
time. The download monitor parses progress, transfer speed, ETA, and recent
output when the manager prints those details.

For managers whose CLI output is not stable JSON, parsing is conservative and
best-effort. Failed manager commands are logged in the TUI log view.
