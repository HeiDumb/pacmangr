# pacmangr

![Pacmangr](showcase.gif)

`pacmangr` is a terminal interface for the package managers already installed
on your system. It is not a replacement for `pacman`, `yay`, `paru`, `flatpak`,
`apt`, or any other native manager; it gives those tools one fast searchable
terminal interface and still delegates real install, remove, update, and info
actions to the native commands underneath.

It autodetects available managers, keeps a local SQLite cache for fast repeat
searches and installed-package startup, shows a unified searchable package view,
and runs install, remove, and update actions in a background queue with an
in-TUI sudo password prompt and download monitor.

For the local desktop, `pacmangr-gui` provides an organised GTK interface using
the same search, cache, and package backend. It follows the current Heilios
colour scheme, offers per-source search and installed-package filters, and runs
package operations in the background. Privileged operations use a graphical
polkit prompt instead of opening a terminal.

## Features

- ASCII/curses TUI with search, installed packages, package details, and logs.
- GTK GUI with source filters, installed view, package details and versions,
  all-source updates, manager/cache diagnostics, graphical authentication, and
  live percentage, speed, and ETA while package operations run.
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
- The terminal interface has no Python dependencies outside the standard
  library. The optional desktop interface uses GTK 4 through PyGObject.
- Non-interactive checks for packaging: `--version` and `--list-managers`.

## Supported Managers

Native support is provided for:

- Arch: `pacman`, `yay`, `paru`, `pacseek`
- Universal app formats: `flatpak`, local `.AppImage` files
- Git repositories: managed fetch/update checkouts under `~/.local/src/pacmangr`
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
- Nix profile packages: `nix-env`
- Language/tool ecosystems: `cargo`, `npm`, `pip`, `pipx`, `gem`, `luarocks`
- Embedded/other package managers: `opkg`, FreeBSD `pkg`, `guix`

Managers are autodetected at startup. If a manager is missing, it is hidden; if
you install it later, `pacmangr` will pick it up the next time it starts.

## Usage

Run:

```sh
pacmangr
pacmangr-gui
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
pacmangr install firefox --source pacman
pacmangr install org.mozilla.firefox --source flatpak -y
pacmangr install https://github.com/owner/project.git --source git
pacmangr install requests --source pip --scope venv
pacmangr remove firefox --dry-run
pacmangr update --dry-run
pacmangr update flatpak -y
pacmangr installed python
pacmangr info pacman
pacmangr versions hyprland
pacmangr cache status
pacmangr doctor
```

`--source` selects a native manager such as `pacman`, `yay`, `flatpak`, `nix`,
or another detected backend. `--dry-run` prints the exact native command and
`-y`/`--yes` adds that manager's non-interactive confirmation option. Nix
operations affect only the detected imperative profile; Pacmangr never edits
NixOS or Home Manager declarations automatically.

Git URLs are fetched into Pacmangr's managed source directory and can be
fast-forward updated later; repository build scripts are never executed
automatically. Pip installs ask for an isolated venv (recommended), user scope,
or explicit privileged system scope. CLI users choose the same behavior with
`--scope venv|user|system`.

## Install

The desktop app installs as **pacmangr** in your application launcher, with the
included icon and a standard desktop entry. It is intentionally not distributed
as a Flatpak: Pacmangr needs access to the host's package managers, their
databases, and polkit, which a normal Flatpak sandbox cannot safely provide.

### Requirements

- Python 3
- GTK 4 and PyGObject (`gtk4` and `python-gobject` on Arch)
- Polkit for graphical authentication when managing system packages

The terminal-only `pacmangr` command only needs Python 3. Native package
managers such as `pacman`, `flatpak`, or `apt` remain optional and are detected
automatically.

### Install from source

Clone the repository, then choose either a user-local or system-wide install:

User-local install:

```sh
git clone https://github.com/HeiDumb/pacmangr.git
cd pacmangr
./scripts/install.sh --user
```

This installs `pacmangr`, `pacmangr-gui`, the launcher entry, and the icon under
`~/.local`. Sign out and back in if your launcher does not show Pacmangr
immediately.

System install:

```sh
sudo make install
```

### Arch Linux package

Build and install the included Arch package with:

```sh
makepkg -si
```

It installs both the terminal and GTK applications plus the launcher icon.

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
