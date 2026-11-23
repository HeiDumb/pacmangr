"""Constants shared by the pacmangr core package."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

APP_NAME = "pacmangr"
VERSION = "0.3.0"
SPINNER = "|/-\\"
MAX_RESULTS = 500
APPIMAGE_SCAN_DEPTH = 4
SEARCH_WORKERS = 8
SEARCH_TIMEOUT_SECONDS = {
    "pacman": 8,
    "yay": 10,
    "paru": 10,
    "flatpak": 10,
    "apt": 8,
    "snap": 10,
    "cargo": 8,
    "npm": 8,
    "pip": 8,
    "pipx": 8,
}
CACHE_DB_PATH = Path.home() / ".cache" / APP_NAME / "pacmangr.sqlite"
GIT_SOURCE_ROOT = Path.home() / ".local" / "src" / APP_NAME
CLI_ENTRY_PATH = Path(__file__).resolve().parent.parent / "pacmangr"
PIP_VENV_ROOT = Path.home() / ".local" / "share" / APP_NAME / "venvs"
CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
CACHE_TTL_SECONDS = {
    "pacman": 6 * 60 * 60,
    "yay": 3 * 60 * 60,
    "paru": 3 * 60 * 60,
    "flatpak": 6 * 60 * 60,
    "apt": 12 * 60 * 60,
    "snap": 12 * 60 * 60,
    "dnf": 12 * 60 * 60,
    "zypper": 12 * 60 * 60,
    "apk": 12 * 60 * 60,
    "xbps": 12 * 60 * 60,
    "cargo": 24 * 60 * 60,
    "npm": 24 * 60 * 60,
    "pip": 24 * 60 * 60,
    "pipx": 24 * 60 * 60,
    "gem": 24 * 60 * 60,
    "luarocks": 24 * 60 * 60,
    "appimage": 6 * 60 * 60,
    "downgrade": 6 * 60 * 60,
}


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PKG_HEADER_RE = re.compile(r"^([^\s/]+)/([^\s]+)\s+([^\s]+)(.*)$")
CARGO_SEARCH_RE = re.compile(r"^([A-Za-z0-9_.+@/-]+)\s+=\s+\"([^\"]+)\"(?:\s+#\s*(.*))?$")
PIP_INDEX_RE = re.compile(r"^([A-Za-z0-9_.+-]+)\s+\(([^)]+)\)")
PERCENT_RE = re.compile(r"(?<!\d)(100|[1-9]?\d)%")
SPEED_RE = re.compile(r"(\d+(?:\.\d+)?\s*(?:[KMGT]?i?B|[kMGT]?B|B)/s)", re.IGNORECASE)
ETA_RE = re.compile(r"(?:eta\s*)?(\d{1,2}:\d{2}(?::\d{2})?)", re.IGNORECASE)
PACMAN_INFO_RE = re.compile(r"^([^:]+)\s*:\s*(.*)$")
SUDO_PROMPT = "pacmangr-sudo:"


MANAGER_SPECS: dict[str, dict[str, object]] = {
    "dnf": {
        "commands": ("dnf",),
        "search": ("dnf", "-q", "search", "{query}"),
        "installed": ("dnf", "-q", "list", "installed"),
        "install": ("dnf", "install", "{package}"),
        "remove": ("dnf", "remove", "{package}"),
        "update": ("dnf", "upgrade"),
        "info": ("dnf", "info", "{package}"),
        "privileged": True,
        "parser": "generic",
    },
    "zypper": {
        "commands": ("zypper",),
        "search": ("zypper", "search", "{query}"),
        "installed": ("zypper", "search", "--installed-only"),
        "install": ("zypper", "install", "{package}"),
        "remove": ("zypper", "remove", "{package}"),
        "update": ("zypper", "update"),
        "info": ("zypper", "info", "{package}"),
        "privileged": True,
        "parser": "generic",
    },
    "apk": {
        "commands": ("apk",),
        "search": ("apk", "search", "-v", "{query}"),
        "installed": ("apk", "info", "-v"),
        "install": ("apk", "add", "{package}"),
        "remove": ("apk", "del", "{package}"),
        "update": ("apk", "upgrade"),
        "info": ("apk", "info", "-a", "{package}"),
        "privileged": True,
        "parser": "generic",
    },
    "xbps": {
        "commands": ("xbps-query", "xbps-install", "xbps-remove"),
        "search": ("xbps-query", "-Rs", "{query}"),
        "installed": ("xbps-query", "-l"),
        "install": ("xbps-install", "-S", "{package}"),
        "remove": ("xbps-remove", "-R", "{package}"),
        "update": ("xbps-install", "-Syu"),
        "info": ("xbps-query", "-RS", "{package}"),
        "privileged": True,
        "parser": "generic",
    },
    "emerge": {
        "commands": ("emerge",),
        "search": ("emerge", "--searchdesc", "{query}"),
        "install": ("emerge", "{package}"),
        "remove": ("emerge", "--deselect", "{package}"),
        "update": ("emerge", "--sync"),
        "info": ("emerge", "--info", "{package}"),
        "privileged": True,
        "parser": "generic",
    },
    "eopkg": {
        "commands": ("eopkg",),
        "search": ("eopkg", "search", "{query}"),
        "installed": ("eopkg", "list-installed"),
        "install": ("eopkg", "install", "{package}"),
        "remove": ("eopkg", "remove", "{package}"),
        "update": ("eopkg", "upgrade"),
        "info": ("eopkg", "info", "{package}"),
        "privileged": True,
        "parser": "generic",
    },
    "swupd": {
        "commands": ("swupd",),
        "search": ("swupd", "search", "{query}"),
        "installed": ("swupd", "bundle-list"),
        "install": ("swupd", "bundle-add", "{package}"),
        "remove": ("swupd", "bundle-remove", "{package}"),
        "update": ("swupd", "update"),
        "info": ("swupd", "bundle-info", "{package}"),
        "privileged": True,
        "parser": "generic",
    },
    "brew": {
        "commands": ("brew",),
        "search": ("brew", "search", "{query}"),
        "installed": ("brew", "list", "--versions"),
        "install": ("brew", "install", "{package}"),
        "remove": ("brew", "uninstall", "{package}"),
        "update": ("brew", "upgrade"),
        "info": ("brew", "info", "{package}"),
        "parser": "generic",
    },
    "nix": {
        "commands": ("nix-env",),
        "search": ("nix-env", "-qaP", "{query}"),
        "installed": ("nix-env", "-q"),
        "install": ("nix-env", "-iA", "{package}"),
        "remove": ("nix-env", "-e", "{package}"),
        "update": ("nix-env", "-u"),
        "parser": "generic",
    },
    "cargo": {
        "commands": ("cargo",),
        "search": ("cargo", "search", "{query}", "--limit", "50"),
        "installed": ("cargo", "install", "--list"),
        "install": ("cargo", "install", "{package}"),
        "remove": ("cargo", "uninstall", "{package}"),
        "parser": "cargo",
    },
    "npm": {
        "commands": ("npm",),
        "search": ("npm", "search", "--json", "{query}"),
        "installed": ("npm", "list", "-g", "--depth=0", "--json"),
        "install": ("npm", "install", "-g", "{package}"),
        "remove": ("npm", "uninstall", "-g", "{package}"),
        "update": ("npm", "update", "-g"),
        "info": ("npm", "view", "{package}"),
        "parser": "npm",
    },
    "pip": {
        "commands": ("pip",),
        "search": ("pip", "index", "versions", "{query}"),
        "installed": ("pip", "list", "--format=json"),
        "install": ("pip", "install", "--user", "{package}"),
        "remove": ("pip", "uninstall", "{package}"),
        "info": ("pip", "show", "{package}"),
        "parser": "pip",
    },
    "pipx": {
        "commands": ("pipx",),
        "installed": ("pipx", "list", "--json"),
        "install": ("pipx", "install", "{package}"),
        "remove": ("pipx", "uninstall", "{package}"),
        "update": ("pipx", "upgrade-all"),
        "parser": "pipx",
    },
    "gem": {
        "commands": ("gem",),
        "search": ("gem", "search", "-r", "{query}"),
        "installed": ("gem", "list", "--local"),
        "install": ("gem", "install", "{package}"),
        "remove": ("gem", "uninstall", "{package}"),
        "update": ("gem", "update"),
        "info": ("gem", "info", "{package}"),
        "parser": "generic",
    },
    "luarocks": {
        "commands": ("luarocks",),
        "search": ("luarocks", "search", "{query}"),
        "installed": ("luarocks", "list"),
        "install": ("luarocks", "install", "{package}"),
        "remove": ("luarocks", "remove", "{package}"),
        "parser": "generic",
    },
    "opkg": {
        "commands": ("opkg",),
        "search": ("opkg", "find", "*{query}*"),
        "installed": ("opkg", "list-installed"),
        "install": ("opkg", "install", "{package}"),
        "remove": ("opkg", "remove", "{package}"),
        "update": ("opkg", "update"),
        "info": ("opkg", "info", "{package}"),
        "privileged": True,
        "parser": "generic",
    },
    "pkg": {
        "commands": ("pkg",),
        "search": ("pkg", "search", "{query}"),
        "installed": ("pkg", "info"),
        "install": ("pkg", "install", "{package}"),
        "remove": ("pkg", "delete", "{package}"),
        "update": ("pkg", "upgrade"),
        "info": ("pkg", "info", "{package}"),
        "privileged": True,
        "parser": "generic",
    },
    "guix": {
        "commands": ("guix",),
        "search": ("guix", "search", "{query}"),
        "installed": ("guix", "package", "--list-installed"),
        "install": ("guix", "install", "{package}"),
        "remove": ("guix", "remove", "{package}"),
        "update": ("guix", "upgrade"),
        "parser": "generic",
    },
}


CORE_MANAGER_NAMES = {"pacman", "yay", "paru", "flatpak", "apt", "snap"}
