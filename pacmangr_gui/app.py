"""Application orchestrator: header, sidebar, views, details and operations."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from .core_loader import APP_ID, CORE, load_core, source_choices  # noqa: E402,F401
from .details import DetailsPane  # noqa: E402
from .operations import (  # noqa: E402
    available_update_lines,
    PacmanActivity,
    ensure_graphical_auth_agent,
    format_eta,
    orphan_remove_command,
    parse_operation_progress,
    prepare_gui_operation,
    run_streamed_operation,
)
from .settings import SETTINGS, SettingsDialog  # noqa: E402
from .self_update import UpdateResult, check_and_apply_update  # noqa: E402
from .sidebar import Sidebar  # noqa: E402
from .theme import (  # noqa: E402
    CAELESTIA_SCHEME_PATH,
    MATUGEN_SCHEME_PATH,
    PREVIEW_SCHEME_PATH,
    SCHEME_PATH,
    PacmangrLogo,
    hex_rgb,
    install_css,
    palette,
)
from .views import BrowseView, GitHubView, InstalledView, OrphansView, UpdatesView  # noqa: E402
from .widgets import (  # noqa: E402
    ask_confirmation,
    cache_summary,
    clear_cache_files,
    show_manager_status,
    show_text_dialog,
)

VIEW_LABELS = {
    "browse": "Browse & Install",
    "installed": "Installed",
    "updates": "Updates",
    "github": "GitHub",
    "orphans": "Orphaned Packages",
}

VIEW_META = {
    "browse": "Search and install from every enabled source",
    "installed": "Inspect, filter and export what is on this machine",
    "updates": "Review pending upgrades and apply them once",
    "github": "Discover public repositories and clone them safely",
    "orphans": "Find and remove unused dependencies",
}


class PacmangrGUI(Gtk.Application):
    """Main GTK application; navigation happens exclusively in the sidebar."""

    VIEW_KEYS = ("browse", "installed", "updates", "github", "orphans")

    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window: Gtk.ApplicationWindow | None = None
        self.tools = CORE.Tools.detect()
        self.cache = CORE.PackageCache()
        self.items: list = []
        self.raw_items: list = []
        self.current_item = None
        self.sources = []
        self.request_id = 0
        self._search_engine = None
        self._search_engine_lock = threading.Lock()
        self.active_search_token: str | None = None
        self.operation_running = False
        self.operation_cancel_event: threading.Event | None = None
        self.app_update_running = False
        self.package_activity: Gtk.Widget | None = None
        self.operation_progress: Gtk.ProgressBar | None = None
        self.cancel_operation_button: Gtk.Button | None = None
        self.operation_progress_source = 0
        self.operation_started = 0.0
        self.operation_phase_started = 0.0
        self.operation_percent: int | None = None
        self.operation_speed = ""
        self.operation_eta = ""

        # State shared by views and the detail pane.
        self.view_mode = SETTINGS.get("default_view", "browse")
        if self.view_mode not in self.VIEW_KEYS:
            self.view_mode = "browse"
        self.browse_items: list = []
        self.browse_query: str = ""
        self.installed_filter_query: str = ""
        self.installed_kind_filter: str = "all"
        self.all_installed: list = []
        self.installed_items: list = []
        self.orphans_set: set[str] = set()
        self.explicit_set: set[str] = set()
        self.deps_set: set[str] = set()
        self.installed_loaded = False
        self.update_lines: list[str] = []
        self.sidebar_collapsed = bool(SETTINGS.get("sidebar_collapsed", False))

        self.views: dict[str, Gtk.Widget] = {}
        self.details: DetailsPane | None = None
        self.sidebar: Sidebar | None = None
        self.sidebar_revealer: Gtk.Revealer | None = None
        self.sidebar_strip: Gtk.Button | None = None
        self.stack: Gtk.Stack | None = None
        self.header: Gtk.HeaderBar | None = None
        self.header_title: Gtk.Label | None = None
        self.header_subtitle: Gtk.Label | None = None
        self.brand_logo: PacmangrLogo | None = None
        self._scheme_contents = None
        self._colour_monitors = []
        self._colour_refresh_source = 0
        self.status_label: Gtk.Label | None = None
        self.busy_spinner: Gtk.Spinner | None = None
        self._busy_tokens: set[str] = set()
        self._app_update_timer_started = False
        self._window_state_source = 0

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def do_activate(self) -> None:
        if self.window:
            self.window.present()
            self._grab_search_focus()
            return

        ensure_graphical_auth_agent()
        install_css()
        self.sources = self.sources or source_choices(self.tools)

        window = Gtk.ApplicationWindow(application=self)
        window.set_title("pacmangr")
        window.set_default_size(
            int(SETTINGS.get("window_width", 1180)),
            int(SETTINGS.get("window_height", 760)),
        )
        # Initial restoration is the only place that sets the window size.
        # All later size/maximized changes come from the user and are only saved.
        window.set_size_request(840, 560)
        window.set_resizable(True)
        if SETTINGS.get("window_maximized", False):
            window.maximize()
        window.add_controller(self.make_escape_controller())
        window.connect("close-request", self._on_close_request)
        window.connect("notify::default-width", self._on_window_geometry_changed)
        window.connect("notify::default-height", self._on_window_geometry_changed)
        window.connect("notify::maximized", self._on_window_geometry_changed)
        self.window = window

        self.build_header()
        self.build_content()
        self.refresh_colours()
        self.watch_colours()
        GLib.timeout_add(1000, self.refresh_colours)
        window.present()

        self.set_active_view(self.view_mode, initial=True)
        # Warm the shared backend off the UI thread so the first search does not
        # have to rediscover tools and load the installed-package cache.
        threading.Thread(target=self.get_search_engine, daemon=True).start()
        if SETTINGS.get("check_updates_on_launch", True):
            GLib.timeout_add(1500, self.check_updates_silently)
        if SETTINGS.get("auto_update_app", True):
            self._schedule_app_update_checks()
        GLib.timeout_add(2200, self._refresh_badges)

    def build_brand(self) -> Gtk.Box:
        brand = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9)
        self.brand_logo = PacmangrLogo(palette())
        brand.append(self.brand_logo)
        name = Gtk.Label(label="pacmangr", xalign=0)
        name.add_css_class("brand-name")
        brand.append(name)
        return brand

    def build_header_title(self) -> Gtk.Box:
        title_widget = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        title_widget.add_css_class("header-title-widget")
        title_widget.append(self.build_brand())

        divider = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        divider.add_css_class("header-divider")
        title_widget.append(divider)

        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.header_title = Gtk.Label(label=VIEW_LABELS.get(self.view_mode, "Browse & Install"), xalign=0)
        self.header_title.add_css_class("header-view-title")
        self.header_subtitle = Gtk.Label(label=VIEW_META.get(self.view_mode, ""), xalign=0)
        self.header_subtitle.add_css_class("header-view-subtitle")
        copy.append(self.header_title)
        copy.append(self.header_subtitle)
        title_widget.append(copy)
        return title_widget

    def build_header(self) -> None:
        assert self.window
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        self.header = header
        header.set_title_widget(self.build_header_title())
        self.window.set_titlebar(header)

    def update_header(self) -> None:
        if self.header_title:
            self.header_title.set_text(VIEW_LABELS.get(self.view_mode, ""))
        if self.header_subtitle:
            self.header_subtitle.set_text(VIEW_META.get(self.view_mode, ""))

    def build_content(self) -> None:
        assert self.window
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.add_css_class("app-root")
        root.set_margin_top(14)
        root.set_margin_bottom(14)
        root.set_margin_start(14)
        root.set_margin_end(14)

        main_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        main_row.set_vexpand(True)

        self.sidebar = Sidebar(active=self.view_mode, on_activate=self._sidebar_activated)
        self.sidebar.set_vexpand(True)
        self.sidebar_revealer = Gtk.Revealer()
        self.sidebar_revealer.set_vexpand(True)
        self.sidebar_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_RIGHT)
        self.sidebar_revealer.set_transition_duration(180)
        self.sidebar_revealer.set_reveal_child(not self.sidebar_collapsed)
        self.sidebar_revealer.set_child(self.sidebar)
        main_row.append(self.sidebar_revealer)

        self.sidebar_strip = Gtk.Button()
        self.sidebar_strip.add_css_class("rail-strip")
        self.sidebar_strip.set_size_request(10, -1)
        self.sidebar_strip.set_vexpand(True)
        self.sidebar_strip.set_tooltip_text("Show navigation (Ctrl+B)")
        self.sidebar_strip.connect("clicked", lambda *_: self.set_sidebar_collapsed(False))
        strip_motion = Gtk.EventControllerMotion()
        strip_motion.connect("enter", lambda *_: self.set_sidebar_collapsed(False))
        self.sidebar_strip.add_controller(strip_motion)
        main_row.append(self.sidebar_strip)
        self._sync_sidebar_widgets()

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hexpand(True)
        self.stack.set_vexpand(True)
        self.views = {
            "browse": BrowseView(self, self.sources),
            "installed": InstalledView(self, self.sources),
            "updates": UpdatesView(self),
            "github": GitHubView(self),
            "orphans": OrphansView(self),
        }
        for key, view in self.views.items():
            self.stack.add_titled(view, key, VIEW_LABELS[key])

        self.details = DetailsPane(self)
        main_row.append(self.stack)
        main_row.append(self.details)
        root.append(main_row)

        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.add_css_class("status-card")
        self.package_activity = PacmanActivity(palette())
        self.package_activity.set_margin_start(10)
        self.package_activity.set_valign(Gtk.Align.CENTER)
        status_box.append(self.package_activity)

        self.busy_spinner = Gtk.Spinner()
        self.busy_spinner.set_size_request(18, 18)
        self.busy_spinner.set_margin_start(12)
        self.busy_spinner.set_valign(Gtk.Align.CENTER)
        self.busy_spinner.set_visible(False)
        status_box.append(self.busy_spinner)

        status_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        status_content.set_hexpand(True)
        self.status_label = Gtk.Label(
            label=f"Ready · {len(self.sources) - 1} package sources detected", xalign=0
        )
        self.status_label.set_ellipsize(3)
        self.status_label.set_hexpand(True)
        self.status_label.set_margin_top(8)
        self.status_label.set_margin_bottom(8)
        self.status_label.set_margin_start(12)
        self.status_label.set_margin_end(12)
        status_content.append(self.status_label)

        self.operation_progress = Gtk.ProgressBar()
        self.operation_progress.set_show_text(True)
        self.operation_progress.set_hexpand(True)
        self.operation_progress.set_margin_start(12)
        self.operation_progress.set_margin_end(12)
        self.operation_progress.set_margin_bottom(8)
        self.operation_progress.set_visible(False)
        status_content.append(self.operation_progress)
        status_box.append(status_content)

        self.cancel_operation_button = Gtk.Button(label="Cancel")
        self.cancel_operation_button.add_css_class("danger")
        self.cancel_operation_button.set_margin_end(10)
        self.cancel_operation_button.set_visible(False)
        self.cancel_operation_button.connect("clicked", lambda *_: self.cancel_operation())
        status_box.append(self.cancel_operation_button)
        root.append(status_box)

        self.window.set_child(root)

    # ------------------------------------------------------------------
    # Navigation & keyboard
    # ------------------------------------------------------------------
    def _sidebar_activated(self, key: str) -> None:
        if key == "settings":
            self.open_settings_dialog()
        elif key in self.views:
            self.set_active_view(key)

    def set_active_view(self, key: str, initial: bool = False) -> None:
        if key not in self.views:
            key = "browse"
        if self.view_mode == "github" and key != "github":
            self.views["github"].search_button.set_sensitive(True)
        self.view_mode = key
        if not self.operation_running:
            self.set_busy(False)
        if self.stack:
            self.stack.set_visible_child_name(key)
        if self.sidebar:
            self.sidebar.set_active(key)
        self.update_header()
        view = self.views[key]

        if key == "browse":
            if self.browse_items:
                self.show_items(self.browse_items, f"Results for “{self.browse_query}”",
                                remember=False, auto_select=False)
            elif not initial:
                self.clear_rows()
                self.result_heading_set("Search for packages")
                self.set_status("Ready · type a package name above to search.")
            view.focus()
        elif key == "installed":
            if not self.installed_loaded:
                view.load_installed()
            else:
                view.filter_installed()
            if not initial:
                view.focus()
        elif key == "updates":
            if not view.loaded:
                view.refresh()
            else:
                view.populate(view.lines)
        elif key == "github":
            if not initial:
                view.focus()
        elif key == "orphans":
            view.refresh()

    def switch_view_mode(self, mode: str, initial: bool = False) -> None:
        """Backwards-compatible name for sidebar navigation."""
        self.set_active_view(mode, initial=initial)

    def _sync_sidebar_widgets(self) -> None:
        if self.sidebar_revealer:
            self.sidebar_revealer.set_reveal_child(not self.sidebar_collapsed)
            self.sidebar_revealer.set_visible(not self.sidebar_collapsed)
        if self.sidebar_strip:
            self.sidebar_strip.set_visible(self.sidebar_collapsed)

    def set_sidebar_collapsed(self, collapsed: bool, persist: bool = True) -> None:
        self.sidebar_collapsed = bool(collapsed)
        self._sync_sidebar_widgets()
        if persist:
            SETTINGS.set("sidebar_collapsed", self.sidebar_collapsed)

    def toggle_sidebar(self) -> None:
        """Ctrl+B: collapse the rail to an edge strip or bring it back."""
        self.set_sidebar_collapsed(not self.sidebar_collapsed)

    def make_escape_controller(self) -> Gtk.EventControllerKey:
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self.on_key_pressed)
        return controller

    def on_key_pressed(self, _controller, keyval, _keycode, state) -> bool:
        if keyval == Gdk.KEY_Escape:
            if (self.sidebar_revealer and not self.sidebar_collapsed
                    and isinstance(self.window, Gtk.Window)):
                self.set_sidebar_collapsed(True)
                return True
            if self.window:
                self.window.close()
                return True

        control = state & Gdk.ModifierType.CONTROL_MASK

        if control and keyval in {Gdk.KEY_comma, Gdk.KEY_less}:
            self.open_settings_dialog()
            return True
        if control and keyval in {Gdk.KEY_b, Gdk.KEY_B}:
            self.toggle_sidebar()
            return True
        if control and keyval in {Gdk.KEY_f, Gdk.KEY_F}:
            self._grab_search_focus()
            return True
        if control:
            for index, key in enumerate(self.VIEW_KEYS, start=1):
                if keyval == getattr(Gdk, f"KEY_{index}"):
                    self.set_active_view(key)
                    return True

        if keyval == Gdk.KEY_F5:
            if self.view_mode == "installed":
                self.views["installed"].load_installed(force=True)
            elif self.view_mode == "updates":
                self.views["updates"].refresh()
            elif self.view_mode == "github":
                self.views["github"].refresh()
            elif self.view_mode == "orphans":
                self.views["installed"].load_installed(force=True)
            elif self.browse_query:
                self.views["browse"].on_search()
            return True

        return False

    def _grab_search_focus(self) -> None:
        view = self.views.get(self.view_mode)
        if view and hasattr(view, "focus"):
            view.focus()

    def _grab_focus_compat(self) -> None:
        self._grab_search_focus()

    def result_heading_set(self, text: str) -> None:
        view = self.views.get(self.view_mode)
        if view and hasattr(view, "result_list"):
            view.result_list.heading.set_text(text)

    def open_settings_dialog(self) -> None:
        dialog = SettingsDialog(self)
        dialog.present()

    def apply_settings(self) -> None:
        """Apply settings live after the dialog saves."""
        if SETTINGS.get("auto_update_app", True):
            self._schedule_app_update_checks()
        self.apply_colours()
        if self.header:
            self.header.set_title_widget(self.build_header_title())
        self.set_sidebar_collapsed(bool(SETTINGS.get("sidebar_collapsed", False)), persist=False)
        view = self.views.get(self.view_mode)
        if view:
            if self.view_mode == "browse" and self.browse_items:
                self.show_items(self.browse_items, f"Results for “{self.browse_query}”",
                                remember=False, auto_select=False)
            elif self.view_mode == "installed" and self.installed_loaded:
                view.filter_installed()
            elif hasattr(view, "refresh") and getattr(view, "loaded", False):
                view.refresh()
        self.update_badges()
        self.set_status("Settings applied.")

    def update_badges(self) -> None:
        if not self.sidebar:
            return
        self.sidebar.set_badge("updates", len(self.update_lines))
        self.sidebar.set_badge("orphans", len(self.orphans_set))

    def _scheme_paths(self) -> tuple[Path, ...]:
        configured = Path(SETTINGS.get("scheme_path") or SCHEME_PATH).expanduser()
        return (
            PREVIEW_SCHEME_PATH,
            CAELESTIA_SCHEME_PATH,
            configured,
            SCHEME_PATH,
            MATUGEN_SCHEME_PATH,
        )

    def _active_scheme_path(self) -> Path | None:
        mode = SETTINGS.get("theme_mode", "auto")
        if mode == "accent":
            return None
        if mode == "matugen":
            return MATUGEN_SCHEME_PATH if MATUGEN_SCHEME_PATH.is_file() else None
        return next((path for path in self._scheme_paths() if path.is_file()), None)

    def watch_colours(self) -> None:
        """Watch wallpaper palette files and refresh styling when they change."""
        directories = {path.parent for path in self._scheme_paths()}
        for directory in directories:
            try:
                monitor = Gio.File.new_for_path(str(directory)).monitor_directory(
                    Gio.FileMonitorFlags.NONE, None
                )
                monitor.connect("changed", self.on_colour_file_changed)
                self._colour_monitors.append(monitor)
            except GLib.Error:
                pass  # The periodic refresh remains a fallback.

    def on_colour_file_changed(self, _monitor, file, other_file, _event) -> None:
        paths = set(self._scheme_paths())
        if not any(f and f.get_path() and Path(f.get_path()) in paths for f in (file, other_file)):
            return
        if self._colour_refresh_source:
            GLib.source_remove(self._colour_refresh_source)
        self._colour_refresh_source = GLib.timeout_add(30, self.refresh_colours_from_event)

    def refresh_colours_from_event(self) -> bool:
        self._colour_refresh_source = 0
        self.refresh_colours()
        return GLib.SOURCE_REMOVE

    def refresh_colours(self) -> bool:
        """Reload Caelestia/Heilios/matugen colours without restarting the app."""
        scheme_path = self._active_scheme_path()
        if scheme_path is None:
            contents, colours = None, None
        else:
            try:
                contents = scheme_path.read_text(encoding="utf-8")
                payload = json.loads(contents)
                colours = payload.get("colours", payload.get("colors", payload))
                if not isinstance(colours, dict) or not colours:
                    return GLib.SOURCE_CONTINUE
            except (OSError, ValueError, TypeError, AttributeError):
                return GLib.SOURCE_CONTINUE

        signature = (str(scheme_path) if scheme_path else "", contents)
        if signature != self._scheme_contents:
            self.apply_colours(scheme_colours=colours)
            self._scheme_contents = signature
        return GLib.SOURCE_CONTINUE

    def apply_colours(self, *, scheme_colours: dict | None = None) -> None:
        colours = palette(scheme_colours=scheme_colours) if scheme_colours is not None else palette()
        install_css(colours, SETTINGS.get("compact_rows", False))
        for widget in (self.brand_logo, self.package_activity):
            if widget is None:
                continue
            widget._body = hex_rgb(colours["primary"])
            widget._eye = hex_rgb(colours["on_primary"])
            widget._pellet = hex_rgb(colours["success"])
            if isinstance(widget, PacmanActivity):
                widget._remove_pellet = hex_rgb(colours["error"])
            widget.queue_draw()

    def _periodic_app_update_check(self) -> bool:
        if SETTINGS.get("auto_update_app", True):
            self.check_app_updates()
        return GLib.SOURCE_CONTINUE

    def _schedule_app_update_checks(self) -> None:
        if self._app_update_timer_started:
            return
        self._app_update_timer_started = True
        GLib.timeout_add(6000, self.check_app_updates)
        GLib.timeout_add_seconds(21600, self._periodic_app_update_check)

    def check_app_updates(self, manual: bool = False) -> bool:
        if self.app_update_running:
            return GLib.SOURCE_REMOVE
        if self.operation_running:
            if manual:
                self.set_status("Wait for the current package operation to finish before updating Pacmangr.")
            elif SETTINGS.get("auto_update_app", True):
                GLib.timeout_add_seconds(60, self.check_app_updates)
            return GLib.SOURCE_REMOVE
        if not manual and not SETTINGS.get("auto_update_app", True):
            return GLib.SOURCE_REMOVE

        now = time.time()
        last_check = float(SETTINGS.get("last_app_update_check", 0) or 0)
        if not manual and now - last_check < 6 * 60 * 60:
            return GLib.SOURCE_REMOVE
        if not manual:
            SETTINGS.set("last_app_update_check", now)
        self.app_update_running = True
        self.begin_busy("app-update")
        if manual:
            self.set_status("Checking GitHub for Pacmangr updates…")

        def worker() -> None:
            try:
                result = check_and_apply_update()
            except Exception as exc:  # Keep an unexpected updater failure from leaving the UI busy.
                result = UpdateResult("error", detail=str(exc))
            GLib.idle_add(self._finish_app_update_check, result, manual)

        start_thread(worker)
        return GLib.SOURCE_REMOVE

    def _finish_app_update_check(self, result: UpdateResult, manual: bool) -> bool:
        self.app_update_running = False
        self.end_busy("app-update")
        if manual:
            SETTINGS.set("last_app_update_check", time.time())

        if result.status == "updated":
            message = (
                f"Pacmangr updated to {result.commit[:8]}. Restart the app to load the update."
            )
        elif result.status == "current":
            message = f"Pacmangr is up to date ({result.commit[:8]})."
        elif result.status == "local_changes":
            message = result.detail
        elif result.status == "unsupported":
            message = f"Automatic app updates are unavailable: {result.detail}"
        else:
            message = result.detail or "Could not check for Pacmangr updates."

        if manual or result.status in {"updated", "local_changes"}:
            self.set_status(message)
        return GLib.SOURCE_REMOVE

    def _refresh_badges(self) -> bool:
        if not self.installed_loaded:
            self.views["installed"].load_installed()
        self.update_badges()
        return GLib.SOURCE_REMOVE

    # ------------------------------------------------------------------
    # Status, lists and details
    # ------------------------------------------------------------------
    def set_status(self, text: str, busy: bool = False) -> None:
        if self.status_label:
            self.status_label.set_text(text)
        if busy:
            self._busy_tokens.add("status")
        else:
            self._busy_tokens.discard("status")
        self._sync_busy_spinner()

    def set_busy(self, busy: bool) -> None:
        if busy:
            self._busy_tokens.add("status")
        else:
            self._busy_tokens.discard("status")
        self._sync_busy_spinner()

    def begin_busy(self, token: str) -> None:
        self._busy_tokens.add(token)
        self._sync_busy_spinner()

    def end_busy(self, token: str) -> None:
        self._busy_tokens.discard(token)
        self._sync_busy_spinner()

    def begin_search_activity(self, request_id: int) -> None:
        if self.active_search_token:
            self.end_busy(self.active_search_token)
        self.active_search_token = f"search:{request_id}"
        self.begin_busy(self.active_search_token)

    def end_search_activity(self, request_id: int) -> None:
        token = f"search:{request_id}"
        self.end_busy(token)
        if self.active_search_token == token:
            self.active_search_token = None

    def _sync_busy_spinner(self) -> None:
        if self.busy_spinner:
            if self._busy_tokens:
                self.busy_spinner.start()
                self.busy_spinner.set_visible(True)
            else:
                self.busy_spinner.stop()
                self.busy_spinner.set_visible(False)

    def get_search_engine(self):
        """Create the shared headless search engine once, off the GTK thread."""
        with self._search_engine_lock:
            if self._search_engine is None:
                self._search_engine = CORE.headless_ui(tools=self.tools, cache=self.cache)
            return self._search_engine

    def show_search_progress(self, items: list, heading: str) -> None:
        if self.view_mode != "browse":
            return
        self.browse_items = list(items[:int(SETTINGS.get("max_results", MAX_GUI_RESULTS))])
        view = self.views["browse"]
        view.result_list.append_items(self.browse_items, heading)

    def show_items(self, items: list, heading: str, remember: bool = True,
                   auto_select: bool = True, row_factory=None) -> None:
        max_r = int(SETTINGS.get("max_results", 250))
        if remember:
            self.raw_items = list(items)
        self.items = items[:max_r]
        self.current_item = None
        view = self.views.get(self.view_mode)
        if self.details:
            self.details.reset()
        if view and hasattr(view, "result_list"):
            view.result_list.populate(
                self.items, heading, auto_select=auto_select, row_factory=row_factory
            )

    def clear_rows(self) -> None:
        view = self.views.get(self.view_mode)
        if view and hasattr(view, "result_list"):
            view.result_list.clear()
        self.current_item = None
        if self.details:
            self.details.reset()

    def on_row_selected(self, _listbox, row) -> None:
        if row is None:
            return
        item = getattr(row, "item", None)
        if item is None:
            return
        self.current_item = item
        if self.details:
            self.details.show(item)
            self.details.set_loading(item)
        # Clicking a row immediately fetches its details (README.md for GitHub items).
        self.on_info()

    def set_detail_text(self, text: str) -> None:
        if self.details:
            self.details.set_text(text)

    def on_info(self, *_args) -> None:
        if self.details:
            self.details.on_info()

    def finish_info(self, item, code: int, output: str) -> bool:
        return bool(self.details and self.details.finish_info(item, code, output))

    def on_versions(self, *_args) -> None:
        if self.details:
            self.details.on_versions()

    def finish_versions(self, item, versions: list, error: str) -> bool:
        return bool(self.details and self.details.finish_versions(item, versions, error))

    def on_package_files(self, *_args) -> None:
        if self.details:
            self.details.on_package_files()

    def _finish_package_files(self, item, output: str) -> bool:
        if not self.details:
            return False
        return bool(self.details._finish_package_files(item, output))

    def on_copy_name(self, *_args) -> None:
        if self.details:
            self.details.on_copy_name()

    def on_open_website(self, *_args) -> None:
        if self.details:
            self.details.on_open_website()

    def _launch_url(self, url: str) -> bool:
        if self.details:
            return bool(self.details._launch_url(url))
        return False

    # Compatibility aliases used by the old GUI layout.
    @property
    def detail_text(self):
        return self.details.detail_text if self.details else None

    @property
    def detail_name(self):
        return self.details.detail_name if self.details else None

    @property
    def detail_meta(self):
        return self.details.detail_meta if self.details else None

    @property
    def detail_actions(self):
        return self.details.detail_actions if self.details else None

    @property
    def info_button(self):
        return self.details.info_button if self.details else None

    @property
    def versions_button(self):
        return self.details.versions_button if self.details else None

    @property
    def files_button(self):
        return self.details.files_button if self.details else None

    @property
    def copy_button(self):
        return self.details.copy_button if self.details else None

    @property
    def website_button(self):
        return self.details.website_button if self.details else None

    @property
    def install_button(self):
        return self.details.install_button if self.details else None

    @property
    def remove_button(self):
        return self.details.remove_button if self.details else None

    @property
    def result_list(self):
        view = self.views.get(self.view_mode)
        return getattr(view, "result_list", None)

    # ------------------------------------------------------------------
    # Search / source helpers (delegated to the browse view)
    # ------------------------------------------------------------------
    def selected_source(self) -> str:
        return self.views["browse"].selected_source()

    def source_matches(self, item, source: str) -> bool:
        return self.views["installed"].source_matches(item, source)

    def on_source_changed(self, _dropdown=None, _param=None) -> None:
        self.views["browse"].on_source_changed(_dropdown, _param)

    def on_search(self, _widget=None) -> None:
        self.views["browse"].on_search(_widget)

    def finish_search(self, request_id: int, query: str, items: list, error: str) -> bool:
        return self.views["browse"].finish_search(request_id, query, items, error)

    def on_installed_filter_changed(self, entry) -> None:
        self.views["installed"].on_filter_changed(entry)

    def on_installed_kind_changed(self, dropdown, _param=None) -> None:
        self.views["installed"].on_kind_changed(dropdown, _param)

    def set_installed_kind_filter(self, kind: str) -> None:
        self.views["installed"].set_kind_filter(kind)

    def filter_installed(self) -> None:
        self.views["installed"].filter_installed()

    def load_installed(self, force: bool = False) -> None:
        self.views["installed"].load_installed(force=force)

    def refresh_installed(self, _widget=None) -> None:
        self.set_active_view("installed")
        self.load_installed(force=True)

    def on_installed_toggled(self, _button=None) -> None:
        self.set_active_view("installed")

    # ------------------------------------------------------------------
    # Update checks
    # ------------------------------------------------------------------
    def check_updates_silently(self) -> bool:
        updates_view = self.views.get("updates")
        if updates_view:
            updates_view.refresh()
        return GLib.SOURCE_REMOVE

    def check_updates_dialog(self) -> None:
        self.begin_busy("updates-dialog")
        self.set_status("Checking for updates…")

        def worker() -> None:
            try:
                lines = available_update_lines()
                GLib.idle_add(self._show_updates_dialog, lines, "")
            except Exception as exc:
                GLib.idle_add(self._show_updates_dialog, [], str(exc))

        start_thread(worker)

    def _run_checkupdates(self) -> int:
        return len(available_update_lines())

    def _get_checkupdates_lines(self) -> list[str]:
        return available_update_lines()

    def _show_updates_dialog(self, lines: list[str], error: str = "") -> bool:
        self.end_busy("updates-dialog")
        self.set_status(f"Update check failed: {error}" if error else "Update check completed.")
        if error:
            self.show_text_dialog("Update Check Failed", error)
            return False
        self.update_lines = lines
        self.update_badges()
        self.views["updates"].populate(lines)
        if not lines:
            self.show_text_dialog("System Up to Date", "Everything is up to date! No updates available.")
            return False

        detail = f"{len(lines)} updates available:\n\n" + "\n".join(lines[:40])
        if len(lines) > 40:
            detail += f"\n...and {len(lines) - 40} more."
        ask_confirmation(
            self.window, f"{len(lines)} Package Updates Available", detail,
            "Update All", lambda: self.confirm_update_all(),
        )
        return False

    # ------------------------------------------------------------------
    # Diagnostics and cache
    # ------------------------------------------------------------------
    def show_text_dialog(self, title: str, detail: str) -> None:
        show_text_dialog(self.window, title, detail)

    def show_manager_status(self, _widget=None) -> None:
        self.show_text_dialog("Package manager status", show_manager_status(self.tools, self.sources))

    def show_cache_status(self, _widget=None) -> None:
        self.show_text_dialog("Local package cache", cache_summary(self.cache))

    def confirm_clear_cache(self, _widget=None) -> None:
        ask_confirmation(
            self.window,
            "Clear Pacmangr's local cache?",
            "Only cached search, installed-package, and version metadata is removed. No packages are changed.",
            "Clear cache",
            self._clear_cache,
        )

    def _clear_cache(self) -> None:
        removed = clear_cache_files(self.cache)
        self.set_status("Local cache cleared." if removed else "Local cache was already empty.")

    def export_package_list(self) -> None:
        if not self.all_installed:
            self.set_status("No installed packages loaded to export.")
            return
        export_path = Path.home() / "pacmangr-installed-packages.txt"
        try:
            lines = [
                f"# pacmangr package export - {time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"# Total packages: {len(self.all_installed)}",
                "",
            ]
            for item in sorted(self.all_installed, key=lambda x: x.name):
                reason = f" [{item.install_reason}]" if hasattr(item, "install_reason") else ""
                lines.append(f"{item.name} {item.version} ({item.source}){reason}")
            export_path.write_text("\n".join(lines), encoding="utf-8")
            self.set_status(f"Exported package list to {export_path}")
            self.show_text_dialog(
                "Export Successful",
                f"Exported {len(self.all_installed)} installed packages to:\n{export_path}",
            )
        except Exception as exc:
            self.set_status(f"Export failed: {exc}")

    # ------------------------------------------------------------------
    # Operation plumbing
    # ------------------------------------------------------------------
    def _begin_operation(self, mode: str, status: str) -> threading.Event:
        self.operation_running = True
        self.operation_cancel_event = threading.Event()
        if self.cancel_operation_button:
            self.cancel_operation_button.set_sensitive(True)
            self.cancel_operation_button.set_visible(True)
        for button in (self.install_button, self.remove_button):
            if button:
                button.set_sensitive(False)
        if self.package_activity:
            self.package_activity.start(mode)
        self.start_operation_progress()
        self.begin_busy("package-operation")
        self.set_status(status)
        return self.operation_cancel_event

    def cancel_operation(self) -> None:
        if not self.operation_running or not self.operation_cancel_event:
            return
        self.operation_cancel_event.set()
        if self.cancel_operation_button:
            self.cancel_operation_button.set_sensitive(False)
        self.set_status("Cancelling…")

    def _end_operation(self) -> None:
        self.operation_running = False
        self.operation_cancel_event = None
        self.end_busy("package-operation")
        if self.cancel_operation_button:
            self.cancel_operation_button.set_visible(False)
            self.cancel_operation_button.set_sensitive(True)
        if self.package_activity:
            self.package_activity.stop()
        self.stop_operation_progress()
        item = self.current_item
        if item and self.details:
            self.details.install_button.set_sensitive(
                item.source != "appimage"
                and (item.source != "git" or bool(getattr(self.tools, "git", None)))
            )
            self.details.remove_button.set_sensitive(
                (item.installed or item.source == "appimage") and item.source != "git"
            )

    def start_operation_progress(self) -> None:
        self.operation_started = time.monotonic()
        self.operation_phase_started = self.operation_started
        self.operation_percent = None
        self.operation_speed = ""
        self.operation_eta = ""
        if self.operation_progress:
            self.operation_progress.set_fraction(0)
            self.operation_progress.set_text("Starting package manager…")
            self.operation_progress.set_visible(True)
        if not self.operation_progress_source:
            self.operation_progress_source = GLib.timeout_add(200, self.tick_operation_progress)

    def stop_operation_progress(self) -> None:
        if self.operation_progress_source:
            GLib.source_remove(self.operation_progress_source)
            self.operation_progress_source = 0
        if self.operation_progress:
            self.operation_progress.set_visible(False)

    def tick_operation_progress(self) -> bool:
        if not self.operation_running:
            self.operation_progress_source = 0
            return GLib.SOURCE_REMOVE
        self.render_operation_progress()
        return GLib.SOURCE_CONTINUE

    def render_operation_progress(self) -> None:
        if not self.operation_progress:
            return
        if self.operation_percent is None:
            self.operation_progress.pulse()
            parts = ["Working…"]
            if self.operation_speed:
                parts.append(self.operation_speed)
            if self.operation_eta:
                parts.append(f"ETA {self.operation_eta}")
            self.operation_progress.set_text(" · ".join(parts))
            return

        percent = max(0, min(100, self.operation_percent))
        self.operation_progress.set_fraction(percent / 100)
        eta = self.operation_eta
        if not eta and 0 < percent < 100:
            elapsed = time.monotonic() - self.operation_phase_started
            eta = format_eta(elapsed * (100 - percent) / percent)
        parts = [f"{percent}%"]
        if self.operation_speed:
            parts.append(self.operation_speed)
        parts.append(f"ETA {eta or 'calculating…'}")
        self.operation_progress.set_text(" · ".join(parts))

    def update_operation_progress(self, raw_line: str) -> bool:
        if not self.operation_running:
            return False
        _line, percent, speed, eta = parse_operation_progress(raw_line)
        if percent is not None:
            if self.operation_percent is None or percent + 10 < self.operation_percent:
                self.operation_phase_started = time.monotonic()
                self.operation_eta = ""
            self.operation_percent = percent
        if speed:
            self.operation_speed = speed
        if eta:
            self.operation_eta = eta
        self.render_operation_progress()
        return False

    def launch_raw_operation(self, title: str, cmd: list[str], on_done=None) -> None:
        if self.operation_running:
            self.set_status("Another package operation is already running.")
            return
        try:
            argv = prepare_gui_operation(cmd, self.tools, "remove", shutil.which("pkexec"))
        except RuntimeError as exc:
            self.set_status(str(exc))
            return

        cancel_event = self._begin_operation("remove", f"{title} in progress…")

        def worker() -> None:
            env = os.environ.copy()
            env.update({"DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C"})
            try:
                code, output = run_streamed_operation(
                    argv, env=env,
                    on_line=lambda line: GLib.idle_add(self.update_operation_progress, line),
                    cancel_event=cancel_event,
                )
            except OSError as exc:
                code, output = 126, str(exc)

            def done() -> bool:
                self._end_operation()
                self.set_detail_text(output or "Operation completed.")
                self.set_status(
                    f"{title} cancelled."
                    if code == 130
                    else f"{title} completed." if code == 0
                    else f"{title} failed with code {code}."
                )
                if on_done and code == 0:
                    on_done()
                elif code == 130 and self.installed_loaded:
                    self.load_installed(force=True)
                return False

            GLib.idle_add(done)

        start_thread(worker)

    # ------------------------------------------------------------------
    # Single-authentication update-all
    # ------------------------------------------------------------------
    def confirm_update_all(self, _button=None) -> None:
        commands = self._update_commands()
        if not commands:
            self.set_status("No update-capable package manager was detected.")
            return
        if not SETTINGS.get("confirm_update", True):
            self.launch_maintenance(commands)
            return

        detail = (
            "All of the following native managers will run under ONE graphical "
            "authentication prompt:\n\n"
            + "\n".join(f"• {label}: {shlex.join(command)}" for label, command in commands)
        )
        ask_confirmation(
            self.window, "Update all package sources?", detail,
            "Update all", lambda: self.launch_maintenance(commands),
        )

    def _update_commands(self) -> list[tuple[str, list[str]]]:
        commands = CORE.system_update_commands(self.tools)
        filtered: list[tuple[str, list[str]]] = []
        for label, command in commands:
            if label in {"yay", "paru"} and not SETTINGS.get("include_aur_updates", True):
                continue
            if label == "flatpak" and not SETTINGS.get("include_flatpak_updates", True):
                continue
            filtered.append((label, command))
        return filtered

    def launch_maintenance(self, commands: list[tuple[str, list[str]]]) -> None:
        from . import operations as ops

        if self.operation_running:
            self.set_status("Another package operation is already running.")
            return
        argv = ops.prepare_single_auth_update(commands, self.tools)
        if not argv:
            self.set_status(
                "No authentication tool found. Install polkit (pkexec) or sudo to update everything."
            )
            return
        if ops.SINGLE_AUTH_NEEDS_PASSWORD:
            parent = self.window if isinstance(self.window, Gtk.Window) else None
            if not ops.prime_sudo_timestamp(parent, argv[0]):
                self.set_status("Authentication was cancelled; no updates were run.")
                return

        cancel_event = self._begin_operation(
            "update", f"Updating {len(commands)} package sources with one authentication…"
        )

        def worker() -> None:
            try:
                code, output = run_streamed_operation(
                    argv,
                    ops.operation_environment(),
                    lambda line: GLib.idle_add(self.update_operation_progress, line),
                    cancel_event=cancel_event,
                )
            except OSError as exc:
                code, output = 126, f"Could not start update operation: {exc}"
            GLib.idle_add(self.finish_maintenance, code, output, code == 130)

        start_thread(worker)

    def finish_maintenance(self, code: int, output: str, cancelled: bool = False) -> bool:
        self._end_operation()
        self.set_detail_text(output or "No package-manager output.")
        self.set_status(
            "Package update cancelled." if cancelled
            else "All package updates completed." if code == 0
            else f"Package update stopped with status {code}."
        )
        if (code == 0 or cancelled) and self.installed_loaded:
            self.load_installed(force=True)
        return False

    # ------------------------------------------------------------------
    # Install / remove / orphan cleanup
    # ------------------------------------------------------------------
    def _confirm_enabled(self, key: str) -> bool:
        return bool(SETTINGS.get(key, SETTINGS.get("confirm_actions", True)))

    def confirm_action(self, action: str, install_scope: str | None = None) -> None:
        item = self.current_item
        if not item or not self.window:
            return
        if action == "install" and (item.source == "pip" or item.manager == "pip") and install_scope is None:
            self.choose_pip_scope(item)
            return

        scope = install_scope or SETTINGS.get("pip_scope", "venv")
        command = (
            item.install_command(self.tools, install_scope=scope)
            if action == "install"
            else item.remove_command(self.tools)
        )
        if not command:
            self.set_status(f"No {action} command is available for {item.title()}.")
            return

        reinstall = action == "install" and item.installed
        confirm_key = "confirm_install" if action == "install" else "confirm_remove"
        if reinstall and SETTINGS.get("skip_confirm_reinstall", False):
            self.launch_operation(action, item, command)
            return
        if not self._confirm_enabled(confirm_key):
            self.launch_operation(action, item, command)
            return

        action_label = "Clone" if action == "install" and item.source == "git" and not item.installed else action.title()
        detail = (
            "This runs quietly in the background. If administrator access is "
            "needed, the desktop will show a graphical password prompt.\n\n"
            + shlex.join(command)
        )
        ask_confirmation(
            self.window, f"{action_label} {item.title()}?", detail,
            action_label, lambda: self.launch_operation(action, item, command),
            danger=action == "remove",
        )

    def choose_pip_scope(self, item) -> None:
        if not self.window:
            return
        dialog = Gtk.AlertDialog()
        dialog.set_message(f"Install {item.title()} with Python Pip")
        dialog.set_detail(
            "Choose where Pip should place the package:\n\n"
            "• Managed venv: Isolated under ~/.local/share/pacmangr/pip-venvs\n"
            "• User install: Into ~/.local without touching system files\n"
            "• System install: Requires root privileges"
        )
        dialog.set_buttons(["Cancel", "Managed venv", "User install", "System install"])
        dialog.set_cancel_button(0)
        dialog.set_default_button(1)

        def finished(alert: Gtk.AlertDialog, result) -> None:
            try:
                response = alert.choose_finish(result)
            except GLib.Error:
                return
            scope = {1: "venv", 2: "user", 3: "system"}.get(response)
            if scope:
                self.confirm_action("install", install_scope=scope)

        dialog.choose(self.window, None, finished)

    def confirm_clean_orphans(self, names: list[str] | None = None, command: list[str] | None = None) -> None:
        orphans = sorted(names) if names else sorted(self.orphans_set)
        if not orphans:
            self.set_status("No orphan packages detected.")
            return
        if command is None:
            command = orphan_remove_command(orphans, self.tools)
        if not SETTINGS.get("confirm_orphan_removal", True):
            self.launch_raw_operation("Remove orphans", command,
                                      on_done=lambda: self.load_installed(force=True))
            return

        detail = (
            f"The following {len(orphans)} unused packages will be safely removed:\n\n"
            + "\n".join(f"• {pkg}" for pkg in orphans[:30])
        )
        if len(orphans) > 30:
            detail += f"\n...and {len(orphans) - 30} more."
        ask_confirmation(
            self.window, f"Remove {len(orphans)} orphaned packages?", detail,
            "Remove Orphans",
            lambda: self.launch_raw_operation(
                "Remove orphans", command, on_done=lambda: self.load_installed(force=True)
            ),
            danger=True,
        )

    def launch_operation(self, action: str, item, command: list[str]) -> None:
        if self.operation_running:
            self.set_status("Another package operation is already running.")
            return
        try:
            argv = prepare_gui_operation(command, self.tools, action, shutil.which("pkexec"))
        except RuntimeError as exc:
            self.set_status(str(exc))
            return

        verb = "Installing" if action == "install" else "Removing"
        cancel_event = self._begin_operation(action, f"{verb} {item.title()} in the background…")

        def worker() -> None:
            env = os.environ.copy()
            env["DEBIAN_FRONTEND"] = "noninteractive"
            env["LC_ALL"] = "C"
            env.setdefault("TERM", "xterm-256color")
            try:
                code, output = run_streamed_operation(
                    argv, env=env,
                    on_line=lambda line: GLib.idle_add(self.update_operation_progress, line),
                    cancel_event=cancel_event,
                )
            except OSError as exc:
                output = f"Could not start package operation: {exc}"
                code = 126
            GLib.idle_add(
                self.finish_operation, action, item, code, output, code == 130
            )

        start_thread(worker)

    def finish_operation(
        self, action: str, item, code: int, output: str, cancelled: bool = False
    ) -> bool:
        self._end_operation()
        text = output.strip() or f"The package manager exited with status {code}."
        self.set_detail_text(text)
        if cancelled:
            self.set_status(f"{action.title()} cancelled.")
            if self.installed_loaded:
                self.load_installed(force=True)
        elif code == 0:
            item.installed = action == "install"
            self.set_status(f"{action.title()} completed for {item.title()}.")
            if self.installed_loaded:
                self.load_installed(force=True)
        elif code in {126, 127} and "pkexec" in text:
            self.set_status("Graphical authentication is unavailable; package operation stopped.")
        else:
            last_line = text.splitlines()[-1]
            self.set_status(f"{action.title()} failed ({code}): {last_line}")

        if self.current_item is item and self.details:
            self.details.install_button.set_label("Reinstall" if item.installed else "Install")
            if item.source == "git":
                self.details.install_button.set_label(
                    "Update checkout" if item.installed else "Clone repository"
                )
            self.details.install_button.set_sensitive(
                item.source != "appimage" and (item.source != "git" or bool(self.tools.git))
            )
            self.details.remove_button.set_sensitive(
                (item.installed or item.source == "appimage") and item.source != "git"
            )
            self.details.files_button.set_sensitive(bool(item.installed))
        return False

    def on_open_tui(self, _button=None) -> None:
        preferred = SETTINGS.get("preferred_terminal", "auto")
        terminal = shutil.which(preferred) if preferred != "auto" else None
        if not terminal:
            terminal = (
                shutil.which("foot") or shutil.which("kitty")
                or shutil.which("alacritty") or shutil.which("xterm")
            )
        backend = Path(CORE.__file__) if getattr(CORE, "__file__", None) else Path("pacmangr")
        if not terminal:
            self.set_status("No terminal found.")
            return
        argv = (
            [terminal, "-a", "pacmangr-tui", "-T", "pacmangr", str(backend)]
            if Path(terminal).name == "foot"
            else [terminal, "-T", "pacmangr", "-e", str(backend)]
        )
        subprocess.Popen(argv, start_new_session=True)

    # ------------------------------------------------------------------
    # Window state & shutdown
    # ------------------------------------------------------------------
    def save_window_state(self) -> None:
        """Persist the user's geometry; never use this to resize the window."""
        if not SETTINGS.get("persist_window_geometry", True):
            return
        if not isinstance(self.window, Gtk.Window):
            return
        try:
            width, height = self.window.get_default_size()
            SETTINGS.update({
                "window_width": max(840, int(width)),
                "window_height": max(560, int(height)),
                "window_maximized": bool(self.window.is_maximized()),
            })
        except Exception:
            pass

    def _on_window_geometry_changed(self, *_args) -> None:
        """User resize/maximize: coalesce writes, never apply a new size."""
        if not SETTINGS.get("persist_window_geometry", True):
            return
        if self._window_state_source:
            return
        self._window_state_source = GLib.timeout_add(400, self._flush_window_state)

    def _flush_window_state(self) -> bool:
        self._window_state_source = 0
        self.save_window_state()
        return GLib.SOURCE_REMOVE

    def _on_close_request(self, _window) -> bool:
        self.save_window_state()
        return False

    def do_shutdown(self) -> None:
        if self.package_activity:
            self.package_activity.stop()
        self.stop_operation_progress()
        self.save_window_state()
        Gtk.Application.do_shutdown(self)


def start_thread(target) -> threading.Thread:
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread
