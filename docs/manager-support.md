# Manager Support

`pacmangr` detects managers from an internal registry at startup. A manager is
enabled when all commands declared by its adapter are available in `PATH`.

Support levels:

- `search`: the manager can contribute to unified search.
- `installed`: the manager can contribute to the installed package view.
- `install/remove/update/info`: actions are exposed when selected packages map
  to those commands.

Install, remove, and update operations are intentionally delegated to the real
manager command. This preserves native prompts, password handling, progress
output, conflict handling, and package-manager-specific behavior.

When multiple marked packages share the same command shape, `pacmangr` batches
them into one native command. Otherwise it queues the native commands and keeps
the terminal attached so password prompts and progress output remain visible.

For managers whose CLI output is not stable JSON, parsing is conservative and
best-effort. Failed manager commands are logged in the TUI log view.
