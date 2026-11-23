"""Public facade for the pacmangr core package.

The original ``pacmangr`` script exposed every helper at module level.  The
facade keeps that API: ``from pacmangr_core import *`` provides the same names.
A few globals are mutable at runtime (notably ``GIT_SOURCE_ROOT``), so reads
and writes of those names are forwarded to :mod:`pacmangr_core.constants`.
"""

from __future__ import annotations

import sys as _sys
from types import ModuleType as _ModuleType

from . import constants as _constants
from .backends import (
    appimage_roots,
    collect_installed_packages,
    find_appimages,
    git_checkout_slug,
    git_package,
    is_git_url,
    managed_git_checkouts,
    managed_pip_venvs,
)
from .cache import PackageCache
from .cli import (
    clear_cache,
    parse_cli_operation,
    print_cache_status,
    print_packages,
    resolve_cli_package,
    run_cli,
    run_cli_command,
    run_git_fetch,
    run_pip_install,
    usage,
)
from .commands import (
    detect_extra_managers,
    manager_spec_command,
    noninteractive_command,
    system_update_commands,
)
from .models import (
    DownloadJob,
    PackageItem,
    PackageVersion,
    Tools,
    package_from_dict,
    package_key,
    package_to_dict,
    version_from_dict,
    version_to_dict,
)
from .parsers import (
    parse_apt_installed,
    parse_apt_search,
    parse_arch_search,
    parse_cargo_installed,
    parse_cargo_search,
    parse_flatpak_installed,
    parse_flatpak_search,
    parse_generic_installed,
    parse_generic_search,
    parse_key_value_block,
    parse_manager_installed,
    parse_manager_search,
    parse_npm_installed,
    parse_npm_search,
    parse_pacman_installed,
    parse_pip_installed,
    parse_pip_search,
    parse_pipx_installed,
    parse_snap_installed,
    parse_snap_search,
)
from .tui import PkgUI, clip, headless_ui, main, pad
from .utils import human_size, run_capture, strip_ansi
from .versions import (
    apt_versions_for,
    arch_versions_for,
    dedupe_versions,
    downgrade_remote_versions,
    format_versions,
    package_files_for,
    package_versions,
    pacman_architecture,
    pacman_cache_dirs,
    pacman_log_versions,
    parse_package_file_version,
    version_sort_key,
)
from .constants import (
    ANSI_RE,
    APPIMAGE_SCAN_DEPTH,
    CARGO_SEARCH_RE,
    CACHE_MAX_AGE_SECONDS,
    CACHE_TTL_SECONDS,
    CORE_MANAGER_NAMES,
    ETA_RE,
    MAX_RESULTS,
    PACMAN_INFO_RE,
    PERCENT_RE,
    PIP_INDEX_RE,
    PKG_HEADER_RE,
    SEARCH_TIMEOUT_SECONDS,
    SEARCH_WORKERS,
    SPEED_RE,
    SPINNER,
    SUDO_PROMPT,
    VERSION,
    APP_NAME,
)

__all__ = [
    "APP_NAME", "VERSION", "SPINNER", "MAX_RESULTS", "APPIMAGE_SCAN_DEPTH", "SEARCH_WORKERS",
    "SEARCH_TIMEOUT_SECONDS", "CACHE_DB_PATH", "GIT_SOURCE_ROOT", "PIP_VENV_ROOT", "CACHE_MAX_AGE_SECONDS", "CACHE_TTL_SECONDS",
    "ANSI_RE", "PKG_HEADER_RE", "CARGO_SEARCH_RE", "PIP_INDEX_RE", "PERCENT_RE", "SPEED_RE",
    "ETA_RE", "PACMAN_INFO_RE", "SUDO_PROMPT", "MANAGER_SPECS", "CORE_MANAGER_NAMES", "detect_extra_managers",
    "manager_spec_command", "system_update_commands", "noninteractive_command", "Tools", "PackageItem", "PackageVersion",
    "DownloadJob", "package_key", "package_to_dict", "package_from_dict", "version_to_dict", "version_from_dict",
    "PackageCache", "strip_ansi", "run_capture", "parse_key_value_block", "parse_package_file_version", "version_sort_key",
    "dedupe_versions", "pacman_architecture", "pacman_cache_dirs", "package_files_for", "pacman_log_versions", "downgrade_remote_versions",
    "arch_versions_for", "apt_versions_for", "package_versions", "format_versions", "parse_arch_search", "parse_pacman_installed",
    "parse_flatpak_search", "parse_flatpak_installed", "parse_apt_search", "parse_apt_installed", "parse_snap_search", "parse_snap_installed",
    "parse_cargo_search", "parse_cargo_installed", "parse_npm_search", "parse_npm_installed", "parse_pip_search", "parse_pip_installed",
    "parse_pipx_installed", "parse_generic_search", "parse_generic_installed", "parse_manager_search", "parse_manager_installed", "is_git_url",
    "git_checkout_slug", "git_package", "managed_git_checkouts", "managed_pip_venvs", "appimage_roots", "find_appimages",
    "human_size", "collect_installed_packages", "PkgUI", "clip", "pad", "headless_ui",
    "print_packages", "print_cache_status", "clear_cache", "parse_cli_operation", "resolve_cli_package", "run_cli_command",
    "run_git_fetch", "run_pip_install", "usage", "main",
]

# These globals can be rebound at runtime by callers (GUI/tests).  Keep a
# single source of truth in ``constants`` and forward both reads and writes.
_FORWARDED = frozenset(
    {"GIT_SOURCE_ROOT", "PIP_VENV_ROOT", "MANAGER_SPECS", "CACHE_DB_PATH"}
)


class _FacadeModule(_ModuleType):
    def __getattr__(self, name: str):
        if name in _FORWARDED:
            return getattr(_constants, name)
        raise AttributeError(f"module {self.__name__!r} has no attribute {name!r}")

    def __setattr__(self, name: str, value) -> None:
        if name in _FORWARDED:
            setattr(_constants, name, value)
            return
        _ModuleType.__setattr__(self, name, value)


_sys.modules[__name__].__class__ = _FacadeModule
