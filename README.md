# pacmangr

![Pacmangr](assets/showcase.gif)

**One package-management front end for the package managers already on your
computer.** Pacmangr is available as an interactive terminal UI, a GTK desktop
application, and a scriptable command-line tool.

It does not replace `pacman`, `apt`, `flatpak`, `yay`, `pip`, or another native
tool. It discovers what is installed, gives those tools one searchable
interface, and delegates every action back to the appropriate manager.

## What it does

- Search packages across detected system, universal, language, and developer
  package managers.
- Browse installed packages, package metadata, and available versions.
- Install, remove, and update through the native manager that owns a package.
- Run as a keyboard-first curses TUI, a full GTK 4 desktop application, or a
  non-interactive CLI for scripts.
- Navigate the desktop app with a slim, collapsible icon rail covering Browse &
  Install, Installed, Updates, GitHub, Orphaned Packages, and Settings.
- See full package details automatically when you select a result.
- Theme the GTK app from your wallpaper with matugen (or follow an existing
  Heilios scheme / fixed accent), so colours adapt to any desktop.
- Update every detected source with a **single** authentication prompt.
- Cache search results and installed-package data locally for a fast startup.
- Show live operation progress, download speed, and ETA in the desktop app.
- Use graphical polkit authentication for privileged GUI operations.
- Keep the implementation organized as small `pacmangr_core/` and
  `pacmangr_gui/` Python packages behind thin launcher scripts.

## Interfaces

| Interface | Command | Best for |
| --- | --- | --- |
| Terminal UI | `pacmangr` | Fast keyboard-driven package management in a terminal |
| Desktop app | `pacmangr-gui` | Searching, reviewing details, and managing packages graphically |
| Headless CLI | `pacmangr <command>` | Scripts, aliases, automation, and dry runs |

## Requirements

### Core terminal interface

- Linux or another supported Unix-like host
- Python **3.10 or newer**
- At least one package manager you want Pacmangr to use
- A terminal with curses support for the interactive TUI

The terminal command uses only the Python standard library.

### Desktop application

The GTK app additionally needs:

- GTK 4
- PyGObject with GTK 4 bindings
- A running graphical session
- Polkit (`pkexec`) and a desktop polkit agent for system-level install,
  removal, and update actions

Optional extras:

- `matugen` — generate the app palette from a wallpaper (Appearance settings)

On Arch Linux, install the runtime requirements with:

```sh
sudo pacman -S python python-gobject gtk4 polkit
```

The included Arch package declares the GUI dependencies automatically. Package
names differ on other distributions; install their Python 3, GTK 4, PyGObject,
and polkit equivalents.

### Supported backends

Pacmangr only shows a backend after its executable is detected.

| Category | Backends |
| --- | --- |
| Arch | `pacman`, `yay`, `paru`, `pacseek`, `downgrade` |
| Debian/Ubuntu | `apt`, `apt-cache`, `dpkg-query` |
| Fedora/RHEL | `dnf` |
| openSUSE | `zypper` |
| Alpine / Void / Gentoo / Solus / Clear Linux | `apk`, `xbps`, `emerge`, `eopkg`, `swupd` |
| Universal apps | `flatpak`, local AppImages |
| Developer tools | `cargo`, `npm`, `pip`, `pipx`, `gem`, `luarocks` |
| Other environments | `brew`, `nix-env`, `opkg`, FreeBSD `pkg`, `guix` |
| Source repositories | Git URLs, managed directly under your home directory (`~/repository`) |

## Installation

Pacmangr installs like a normal desktop application: the GUI launcher and its
icon are added to the standard application and icon directories. It is not
distributed as a Flatpak because a sandboxed app cannot safely operate the
host's package managers, package databases, and polkit services.

### Arch Linux package

Build and install the included package:

```sh
git clone https://github.com/HeiDumb/pacmangr.git
cd pacmangr
makepkg -si
```

This installs `pacmangr`, `pacmangr-gui`, the desktop entry, and the Pacmangr
icon.

### Install from source

For a user-local installation under `~/.local`:

```sh
git clone https://github.com/HeiDumb/pacmangr.git
cd pacmangr
./scripts/install.sh --user
```

For a system-wide installation:

```sh
sudo make install
```

If the desktop launcher does not appear immediately after a user-local install,
sign out and back in, or refresh your desktop environment's application cache.

### Uninstall

For a system-wide Makefile install:

```sh
sudo make uninstall
```

For a user-local install, remove the installed files:

```sh
rm -f ~/.local/bin/pacmangr ~/.local/bin/pacmangr-gui
rm -f ~/.local/share/applications/io.github.hei.pacmangr.desktop
rm -f ~/.local/share/icons/hicolor/512x512/apps/io.github.hei.pacmangr.png
```

## Quick start

Open the desktop app from your launcher, or run either interface directly:

```sh
pacmangr
pacmangr-gui
```

To check what Pacmangr can use on the current host:

```sh
pacmangr managers
pacmangr doctor
```

## How it works

```text
                 ┌──────────────────┐
                 │  pacmangr GUI    │
                 │  pacmangr TUI    │
                 │  pacmangr CLI    │
                 └────────┬─────────┘
                          │
                  shared Python backend
                          │
          detect tools ───┼─── cache search / installed data
                          │
      ┌───────────────────┼────────────────────┐
      ▼                   ▼                    ▼
   pacman/yay          flatpak              apt/dnf/etc.
      │                   │                    │
      └───────────────────┴────────────────────┘
                          │
                  host package databases
```

The executable `pacmangr` and `pacmangr-gui` files are thin launchers. All logic
lives in the importable `pacmangr_core/` and `pacmangr_gui/` packages, split by
responsibility (constants, models, cache, parsers, backends, operations, TUI,
CLI; and for the GUI: app, sidebar, views, details, operations, settings, theme,
widgets). Pacmangr constructs and runs each native manager's normal command
rather than reimplementing package installation. It keeps a local SQLite cache at
`~/.cache/pacmangr/pacmangr.sqlite` to make search and installed-package views
responsive; clearing the cache never removes installed packages.

## Desktop app guide

1. Start **Pacmangr** from your application launcher or run `pacmangr-gui`.
2. Use the slim icon rail on the left to pick a view: **Browse & Install**,
   **Installed**, **Updates**, **GitHub**, **Orphaned Packages**, or **Settings**
   at the bottom. Hover an icon for its name; `Ctrl+B` collapses or restores the
   rail.
3. In **Browse & Install**, choose a source or leave it on **All sources**, then
   search (the source selector sits right beside the search bar). Selecting a
   result shows its details automatically — package metadata, or a repository's
   `README.md` for GitHub results.
4. Use **Install**, **Reinstall**, or **Remove** from the detail pane. **Versions**
   and **Files** are available there too.
5. **Updates** lists available upgrades and updates every detected source with
   one authentication prompt.
6. **GitHub** searches public repositories (or accepts a pasted Git URL), shows
   each repository's `README.md` in the details pane, and can clone/install it
   through Pacmangr's git source.
7. **Orphaned Packages** lists unused dependencies and can remove them safely.

Backend and cache diagnostics, cache clearing, export, and the full theme and
behaviour options live in **Settings**, organized into categorized pages. The
app allows one package operation at a time and displays its command output and
progress in the details pane. The window keeps whatever size you choose: switching
views or loading content never resizes it, and your geometry is restored on the
next launch. **Settings → Updates** can check for Pacmangr commits on GitHub at
launch and every six hours, then update a user-local installation automatically.
The package manager's **Cancel** button stops an active install, removal, or update.

Privileged operations use polkit, so a graphical authentication prompt appears
when the native manager needs administrator access. Update-all wraps all native
update commands in a single authenticated invocation (or one cached `sudo`
authorization) so you are only asked once. Flatpak actions do not need host root
access when the selected Flatpak installation is user-scoped.

## Terminal UI guide

Run `pacmangr` with no arguments to open the curses interface.

| Key | Action |
| --- | --- |
| `/` | Search packages, or filter the installed view |
| `s` | Open package search |
| `i` | Show installed packages |
| `Space` | Select or clear the focused package |
| `a` / `c` | Select all visible packages / clear selections |
| `Enter` | Install the focused or selected packages |
| `x` | Remove the focused installed package(s) |
| `u` | Update detected package sources |
| `v` / `V` | Show package information / available versions |
| `r` | Refresh the active view |
| `l` | Open the log view |
| `?` | Show help |
| `q` | Quit |

The TUI asks for a sudo password only when its native command needs elevated
access. Read each native manager prompt before accepting it.

## Command-line usage

The headless commands are intended for scripts and repeatable workflows.

```sh
# Discover available package sources
pacmangr managers
pacmangr doctor

# Search and inspect
pacmangr find firefox
pacmangr installed python
pacmangr info pacman
pacmangr versions firefox

# Preview a native action before running it
pacmangr install firefox --source pacman --dry-run
pacmangr remove firefox --source pacman --dry-run
pacmangr update flatpak --dry-run

# Run a confirmed operation
pacmangr install org.mozilla.firefox --source flatpak --yes
pacmangr update --yes
```

`--source` selects a detected manager, such as `pacman`, `yay`, `flatpak`, or
`nix`. `--dry-run` prints the native command without running it. `-y` and
`--yes` pass the appropriate non-interactive confirmation flag to the selected
backend where one is supported.

### Pip and Git sources

Pip installs can use an isolated virtual environment (recommended), the current
user's package location, or the system site-packages:

```sh
pacmangr install requests --source pip --scope venv
pacmangr install requests --source pip --scope user
pacmangr install requests --source pip --scope system
```

Git URLs are cloned or fast-forwarded directly under your home directory. For
example, `https://github.com/owner/project.git` is stored at `~/project` (with
a collision-safe owner-qualified name if that path already belongs to another
repository):

```sh
pacmangr install https://github.com/owner/project.git --source git
```

Pacmangr does **not** automatically execute a repository's build, install, or
hook scripts. Review a repository before running its instructions yourself.

## Safety and scope

- Pacmangr never substitutes its own package database for the host manager.
- Each backend remains responsible for dependency resolution, signatures,
  repositories, and rollback behavior.
- Nix operations use a detected imperative profile only; Pacmangr does not edit
  NixOS or Home Manager declarations.
- Package actions can change the host system. Use `--dry-run`, inspect details,
  and keep backups appropriate for your distribution.
- Cache clearing affects only `~/.cache/pacmangr`.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| A source is missing | Run `pacmangr managers`; install the native backend and restart Pacmangr. |
| GUI does not start | Confirm GTK 4 and PyGObject are installed, then run `pacmangr-gui` from a terminal for the error. |
| No authentication dialog | Install and start a graphical polkit agent, and confirm `pkexec` is available. |
| Multiple password prompts on update | Keep `pkexec` available; update-all uses one authenticated invocation. Without it, a cached `sudo` authorization is requested once. |
| Theme does not match wallpaper | Install `matugen`, choose a wallpaper in **Settings → Appearance & Theme**, and select **Matugen from wallpaper**. |
| GitHub search shows a rate-limit message | The unauthenticated GitHub API allows limited requests per hour; wait or paste a Git URL directly. |
| Search data seems stale | Use **Settings → Advanced & Diagnostics → Clear local cache** or `pacmangr cache clear`, then search again. |
| An action fails | Read the native manager's output in the details/log view; Pacmangr reports the underlying tool's result. |

## Development

Run the local checks before contributing:

```sh
make check
```

This compiles both entry points, runs unit tests, and checks their
non-interactive commands.

Source layout:

```text
pacmangr          # thin TUI/CLI launcher
pacmangr-gui      # thin GTK launcher
pacmangr_core/    # constants, models, cache, parsers, backends, operations, tui, cli
pacmangr_gui/     # app, sidebar, views, details, operations, settings, theme, widgets
backup/           # original monolithic files, kept for reference
tests/            # unit tests load the launchers through SourceFileLoader
```

To validate the Arch packaging metadata and sources:

```sh
makepkg --verifysource
```

## License

Pacmangr is licensed under the [MIT License](LICENSE).

### Wallpaper-derived colors

When available, the GTK interface follows the Caelestia color scheme and reloads it while running. If no Caelestia scheme exists, it falls back to the Helios scheme or the built-in colors. A custom integration may publish temporary wallpaper preview colors to `~/.local/state/caelestia/wallpaper/preview-scheme.json`; Pacmangr uses that file until it is removed. Stock Caelestia does not currently publish this preview file, so browsing previews requires a separate Caelestia integration.
