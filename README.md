# pacmangr

`pacmangr` is a terminal interface for the package managers already installed
on your system. It is not a replacement for `pacman`, `yay`, `paru`, `flatpak`,
`apt`, or any other native manager; it gives those tools one fast searchable
terminal interface and still delegates real install, remove, update, and info
actions to the native commands underneath.

It autodetects available managers, keeps a local SQLite cache for fast repeat
searches and installed-package startup, shows a unified searchable package view,
and runs install, remove, and update actions in a background queue with an
in-TUI sudo password prompt and download monitor.

## Features

- ASCII/curses TUI with search, installed packages, package details, and logs.
- Unified search across all detected managers that expose search output, with
  cached results shown immediately while live manager commands refresh.
- Local SQLite database at `~/.cache/pacmangr/pacmangr.sqlite` for search and
  installed-package caches, plus cached version lists.
- Version list lookup with `V` in the TUI or `pacmangr versions <package>` from
  a shell.
- Persistent package selections across new search results.
- Background install/remove/update queue with compact progress, speed, and ETA
  monitor.
- Installed package inventory across distro managers, language package managers,
  Flatpak, and local AppImages, loaded from cache first and refreshed live.
- Native install/remove/update execution through the real package managers
  without leaving the TUI.
- Default-yes confirmations: pressing Enter on `Y/n` prompts accepts the action.
- No Python dependencies outside the standard library.
- Non-interactive checks for packaging: `--version` and `--list-managers`.

## Supported Managers

Native support is provided for:

- Arch: `pacman`, `yay`, `paru`, `pacseek`
- Universal app formats: `flatpak`, local `.AppImage` files
- Debian/Ubuntu: `apt`, `apt-cache`, `dpkg-query`
- Snap: `snap`
- Fedora/RHEL: `dnf`
- openSUSE: `zypper`
- Alpine: `apk`
- Void: `xbps-query`, `xbps-install`, `xbps-remove`
- Gentoo: `emerge`
- Solus: `eopkg`
- Clear Linux: `swupd`
- Homebrew/Linuxbrew: `brew`
- Nix user profiles: modern `nix profile`/`nix search`, with `nix-env` fallback
- Language/tool ecosystems: `cargo`, `npm`, `pip`, `pipx`, `gem`, `luarocks`
- Embedded/other package managers: `opkg`, FreeBSD `pkg`, `guix`

Managers are autodetected at startup. If a manager is missing, it is hidden; if
you install it later, `pacmangr` will pick it up the next time it starts.

For Nix, pacmangr deliberately manages the current user's imperative profile.
It does not edit declarative NixOS configuration or Home Manager files. Modern
Nix is preferred and invoked with `nix-command flakes` for JSON search/profile
data; `nix-env` is used only when the modern `nix` command is unavailable,
because the two profile formats cannot safely be mixed.

## Usage

Run:

```sh
pacmangr
```

Keys:

- `/`: search packages, or filter installed packages in the installed view
- `Space`: select or unselect the focused package
- `a`: select all packages currently shown
- `c`: clear selected packages
- `i`: installed packages
- `s`: open package search
- `Enter`: install focused package or selected packages in the background
- `x`: remove focused installed package or selected packages in the background
- `u`: run update commands for detected managers in the background
- `v`: show package info in the log
- `V`: show cached/available versions for the focused package
- `r`: refresh current section
- `l`: log view
- `?`: help
- `q`: quit

Non-interactive commands:

```sh
pacmangr --version
pacmangr managers
pacmangr find hyprland
pacmangr installed python
pacmangr info pacman
pacmangr versions hyprland
pacmangr cache status
pacmangr doctor
```

## Install From Source

User-local install:

```sh
./scripts/install.sh --user
```

System install:

```sh
sudo make install
```

Uninstall:

```sh
sudo make uninstall
```

## Development Checks

```sh
make check
```

The check target compiles the Python script, runs the unit tests, and verifies
the non-interactive entrypoints.
