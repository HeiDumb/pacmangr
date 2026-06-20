# pacmangr

`pacmangr` is an animated terminal package manager for mixed Linux systems. It
autodetects installed package managers, shows a unified searchable package view,
and drops into the real package command for install, remove, and update actions
so password prompts, confirmations, and download progress stay native.

## Features

- ASCII/curses TUI with search, installed packages, package details, and logs.
- Unified search across all detected managers that expose search output.
- Installed package inventory across distro managers, language package managers,
  Flatpak, and local AppImages.
- Native install/remove/update execution through the real backend command.
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
- `i`: installed packages
- `s`: search view
- `Enter`: install selected search result, or show info in installed view
- `x`: remove selected installed package
- `u`: run update commands for detected managers
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
