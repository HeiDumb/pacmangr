# Changelog

## 0.3.0

- Added scriptable `install`, `remove`, and `update` CLI commands with native
  manager selection, dry-run output, and optional non-interactive confirmation.
- Added GUI source filtering, package-version lookup, all-source updates,
  manager diagnostics, cache information, cache clearing, and installed refresh.
- Reorganised the GTK layout into a focused search and details workflow, hiding
  unavailable package actions until a result is selected.
- Follow the Heilios palette and use an opaque app-specific Hyprland rule for
  consistently readable package content.
- Search individual extra backends such as Nix instead of requiring a unified
  all-manager search.
- Added managed Git URL fetching and fast-forward updates without automatically
  executing untrusted repository build scripts.
- Added selectable pip installation scopes: isolated venv, user, or privileged
  system installation.

## 0.2.2

- Fixed the search state race that discarded a new query while another
  background lookup was still active.
- Queue the latest query automatically and discard stale results instead of
  labeling them with the new search text.
- Added regression tests for queued, stale, and completed search states.
- Added `pacmangr-gui`, a personal GTK4 interface backed by the same unified
  search, cache, installed-package, details, install, and remove logic.
- Added a desktop entry and desktop-palette integration for the GUI.
- Added a themed Pac-Man eating animation for background installs,
  reinstalls, removals, and future package-operation modes.
- Stream package-manager output through a pseudo-terminal so the GUI can show
  live download percentage, speed, and reported or estimated ETA.

## 0.2.1

- Made `s` open the search prompt directly instead of requiring a second key.
- Added headless `find`, `installed`, `info`, `managers`, `cache`, and `doctor`
  commands.
- Removed the unrelated Git repository plugin layer and development-loop
  artifacts.
- Simplified labels and presentation throughout the TUI.
- Added regression tests for search-key behavior and CLI help.

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
- Cleaned the package list so rows show package names only while versions,
  descriptions, state, and actions stay inside the details panel.
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
