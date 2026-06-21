https://github.com/user-attachments/assets/230ade11-2b1d-4f66-9d81-694cfdd2f907


# pacmangr

`pacmangr` is an animated terminal package manager for mixed Linux systems. It
autodetects installed package managers, shows a unified searchable package view,
and runs install, remove, and update actions in a background queue with an
in-TUI sudo password prompt and download monitor.

## Features

- ASCII/curses TUI with search, installed packages, package details, and logs.
- Unified search across all detected managers that expose search output.
- Persistent selected packages pinned above new search results.
- Background install/remove/update queue with compact progress, speed, and ETA
  monitor.
- Installed package inventory across distro managers, language package managers,
  Flatpak, and local AppImages.
- Native install/remove/update execution without leaving the TUI.
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
- Nix profile packages: `nix-env`
- Language/tool ecosystems: `cargo`, `npm`, `pip`, `pipx`, `gem`, `luarocks`
- Embedded/other package managers: `opkg`, FreeBSD `pkg`, `guix`

Managers are autodetected at startup. If a manager is missing, it is hidden; if
you install it later, `pacmangr` will pick it up the next time it starts.

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
- `s`: search view
- `Enter`: install focused package or selected packages in the background
- `x`: remove focused installed package or selected packages in the background
- `u`: run update commands for detected managers in the background
- `v`: show package info in the log
- `r`: refresh current section
- `l`: log view
- `?`: help
- `q`: quit

Non-interactive commands:

```sh
pacmangr --version
pacmangr --list-managers
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

The check target compiles the Python script and verifies the non-interactive
entrypoints.

