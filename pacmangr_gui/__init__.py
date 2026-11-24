"""Pacmangr GTK front-end, organised into focused modules.

The module-level API mirrors the original monolithic ``pacmangr-gui`` so the
thin launcher script and existing tests keep working unchanged.
"""

# ruff: noqa: E402

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from .app import PacmangrGUI
from .core_loader import (
    APP_ID,
    CORE,
    MAX_GUI_RESULTS,
    SORT_CHOICES,
    load_core,
    source_choices,
)
from .details import DetailsPane
from .main import main
from .operations import (
    PacmanActivity,
    ensure_graphical_auth_agent,
    fetch_github_readme,
    format_eta,
    github_repo_slug,
    orphan_remove_command,
    parse_operation_progress,
    prepare_gui_operation,
    prepare_single_auth_update,
    prime_sudo_timestamp,
    resolve_github_default_branch,
    run_single_auth_update,
    run_streamed_operation,
)
from .settings import (
    SETTINGS,
    SETTINGS_PATH,
    SettingsDialog,
    SettingsManager,
)
from .sidebar import NAV_ITEMS, SETTINGS_ITEM, NavItem, Sidebar
from .theme import (
    ACCENT_PRESETS,
    CAELESTIA_SCHEME_PATH,
    CURRENT_CSS_PROVIDER,
    HEILIOS_SCHEME_PATH,
    MATUGEN_SCHEME_PATH,
    PREVIEW_SCHEME_PATH,
    SCHEME_PATH,
    PacmangrLogo,
    apply_matugen_from_wallpaper,
    hex_rgb,
    install_css,
    pacman_frame,
    palette,
)
from .views import (
    BrowseView,
    GitHubRepoRow,
    GitHubView,
    InstalledView,
    OrphansView,
    ResultList,
    UpdatesView,
)
from .widgets import (
    EmptyState,
    PackageRow,
    cache_summary,
    show_text_dialog,
)

__all__ = [
    # GTK namespaces (tests import these from the launcher).
    "Gdk",
    "Gio",
    "GLib",
    "Gtk",
    # Backend and constants.
    "CORE",
    "APP_ID",
    "MAX_GUI_RESULTS",
    "SORT_CHOICES",
    "load_core",
    "source_choices",
    # Settings.
    "SETTINGS",
    "SETTINGS_PATH",
    "SettingsManager",
    "SettingsDialog",
    # Theme / drawing.
    "ACCENT_PRESETS",
    "SCHEME_PATH",
    "PREVIEW_SCHEME_PATH",
    "HEILIOS_SCHEME_PATH",
    "CAELESTIA_SCHEME_PATH",
    "MATUGEN_SCHEME_PATH",
    "CURRENT_CSS_PROVIDER",
    "palette",
    "install_css",
    "hex_rgb",
    "pacman_frame",
    "PacmangrLogo",
    "apply_matugen_from_wallpaper",
    # Operations.
    "prepare_gui_operation",
    "ensure_graphical_auth_agent",
    "parse_operation_progress",
    "format_eta",
    "run_streamed_operation",
    "PacmanActivity",
    "prepare_single_auth_update",
    "prime_sudo_timestamp",
    "run_single_auth_update",
    "orphan_remove_command",
    "fetch_github_readme",
    "github_repo_slug",
    "resolve_github_default_branch",
    # Widgets / navigation / views.
    "PackageRow",
    "cache_summary",
    "show_text_dialog",
    "EmptyState",
    "NavItem",
    "NAV_ITEMS",
    "SETTINGS_ITEM",
    "Sidebar",
    "ResultList",
    "BrowseView",
    "InstalledView",
    "UpdatesView",
    "GitHubView",
    "GitHubRepoRow",
    "OrphansView",
    "DetailsPane",
    # Application.
    "PacmangrGUI",
    "main",
]
