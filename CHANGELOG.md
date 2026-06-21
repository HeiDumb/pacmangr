# Changelog

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
