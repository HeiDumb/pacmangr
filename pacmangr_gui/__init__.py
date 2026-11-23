"""Pacmangr GTK front-end, organised into focused modules.

The module-level API mirrors the original monolithic ``pacmangr-gui`` so the
thin launcher script and existing tests keep working unchanged.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .core_loader import (  # noqa: E402
    APP_ID,
    CORE,
    MAX_GUI_RESULTS,
    SORT_CHOICES,
    load_core,
    source_choices,
)
from .settings import (  # noqa: E402
    SETTINGS,
    SETTINGS_PATH,
    SettingsDialog,
    SettingsManager,
)
from .theme import (  # noqa: E402
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
from .operations import (  # noqa: E402
    PacmanActivity,
    ensure_graphical_auth_agent,
    fetch_github_readme,
    format_eta,
    github_repo_slug,
    orphan_remove_command,
    resolve_github_default_branch,
    parse_operation_progress,
    prepare_gui_operation,
    prepare_single_auth_update,
    prime_sudo_timestamp,
    run_single_auth_update,
    run_streamed_operation,
)
from .widgets import (  # noqa: E402
    EmptyState,
    PackageRow,
    cache_summary,
    show_text_dialog,
)
from .sidebar import NAV_ITEMS, SETTINGS_ITEM, NavItem, Sidebar  # noqa: E402
from .views import (  # noqa: E402
    BrowseView,
    GitHubRepoRow,
    GitHubView,
    InstalledView,
    OrphansView,
    ResultList,
    UpdatesView,
)
from .details import DetailsPane  # noqa: E402
from .app import PacmangrGUI  # noqa: E402
from .main import main  # noqa: E402

__all__ = [
    # GTK namespaces (tests import these from the launcher).
    "Gdk", "Gio", "GLib", "Gtk",
    # Backend and constants.
    "CORE", "APP_ID", "MAX_GUI_RESULTS", "SORT_CHOICES", "load_core", "source_choices",
    # Settings.
    "SETTINGS", "SETTINGS_PATH", "SettingsManager", "SettingsDialog",
    # Theme / drawing.
    "ACCENT_PRESETS", "SCHEME_PATH", "PREVIEW_SCHEME_PATH", "HEILIOS_SCHEME_PATH",
    "CAELESTIA_SCHEME_PATH", "MATUGEN_SCHEME_PATH", "CURRENT_CSS_PROVIDER",
    "palette", "install_css", "hex_rgb", "pacman_frame", "PacmangrLogo",
    "apply_matugen_from_wallpaper",
    # Operations.
    "prepare_gui_operation", "ensure_graphical_auth_agent", "parse_operation_progress",
    "format_eta", "run_streamed_operation", "PacmanActivity",
    "prepare_single_auth_update", "prime_sudo_timestamp", "run_single_auth_update",
    "orphan_remove_command", "fetch_github_readme", "github_repo_slug",
    "resolve_github_default_branch",
    # Widgets / navigation / views.
    "PackageRow", "cache_summary", "show_text_dialog", "EmptyState",
    "NavItem", "NAV_ITEMS", "SETTINGS_ITEM", "Sidebar",
    "ResultList", "BrowseView", "InstalledView", "UpdatesView", "GitHubView",
    "GitHubRepoRow", "OrphansView", "DetailsPane",
    # Application.
    "PacmangrGUI", "main",
]
