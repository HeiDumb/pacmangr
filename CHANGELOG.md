# Changelog

## 0.2.0

- Added a local SQLite cache at `~/.cache/pacmangr/pacmangr.sqlite` for search
  results, installed-package inventory, and version lists.
- Load cached installed packages at startup, then refresh the live manager data
  in the background.
- Show cached search results immediately for repeated queries while native
  manager searches refresh.
- Added `V` in the TUI and `pacmangr versions <package>` for package version
  listing.
- Fixed background `yay`/`paru` sudo handling by passing helper sudo flags and
  feeding the in-TUI password through stdin.
- Cleaned the package grid so rows show package names only while versions,
  descriptions, state, and actions stay inside the dossier panel.
- Rank and de-duplicate cached and live results so exact and installed matches
  stay near the top.
- Clarified the project docs: `pacmangr` is a TUI wrapper over native package
  managers, not a replacement for them.

## 0.1.3

- Moved the download monitor into a bottom package-view band so it is visible
  on normal terminal widths, not only wide layouts.

## 0.1.2

- Added in-TUI sudo password prompt for background package operations.
- Added background install/remove/update queue with a download monitor.
- Added progress, speed, ETA, and last-output tracking for running package jobs.
- Kept selected packages pinned at the top of search results across new
  searches.
- Removed the separate marked queue view from the main navigation.

## 0.1.1

- Added persistent marked package queue across searches.
- Added multi-package install/remove batching from marked packages.
- Added Space, `a`, `m`, and `c` queue controls.
- Changed confirmations to default yes when pressing Enter.
- Hardened interactive command return handling around password prompts,
  failed commands, and EOF.

## 0.1.0

- Initial release.
- Animated ASCII terminal UI.
- Unified search and installed package views.
- Autodetection registry for distro, universal, language, and local AppImage
  managers.
- Native command execution for install, remove, update, and info actions.
- AUR-ready packaging files.
