"""Persistent preferences and the categorised settings dialog."""

from __future__ import annotations

import json
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from .core_loader import CORE  # noqa: E402

SETTINGS_PATH = Path.home() / ".config/pacmangr/gui_settings.json"


class SettingsManager:
    """Manages persistent user preferences for pacmangr-gui."""

    DEFAULTS = {
        # Legacy keys (kept for backwards compatibility).
        "default_view": "browse",
        "max_results": 250,
        "confirm_actions": True,
        "aur_helper": "auto",
        "pip_scope": "venv",
        "preferred_terminal": "auto",
        "pacman_animation": True,
        "theme_accent": "auto",
        "compact_rows": False,
        "show_descriptions": True,
        "check_updates_on_launch": True,
        "auto_update_app": True,
        "sort_mode": "relevance",
        "last_source": "all",
        "last_installed_source": "all",
        "window_width": 1180,
        "window_height": 760,
        "window_maximized": False,
        # General.
        "sidebar_collapsed": False,
        "restore_last_source": True,
        "persist_window_geometry": True,
        # Appearance / theming.
        "theme_mode": "auto",  # auto | matugen | accent
        "scheme_path": str(Path.home() / ".local/state/heilios/scheme.json"),
        "wallpaper_path": "",
        "matugen_scheme_type": "tonal-spot",
        "matugen_binary": "matugen",
        "font_scale": 1.0,
        "row_density": "normal",  # compact | normal | comfortable
        # Package managers.
        "enabled_managers": {
            "pacman": True,
            "aur": True,
            "flatpak": True,
            "apt": True,
            "snap": True,
            "cargo": True,
            "npm": True,
            "pip": True,
            "git": True,
            "appimage": True,
        },
        # Updates.
        "auto_refresh_interval": 0,
        "include_aur_updates": True,
        "include_flatpak_updates": True,
        "confirm_update": True,
        # Safety & confirmations.
        "confirm_install": True,
        "confirm_remove": True,
        "confirm_orphan_removal": True,
        "skip_confirm_reinstall": False,
        "trash_or_delete": "trash",
        # Advanced & diagnostics.
        "cache_ttl": 3600,
        "log_level": "info",
        "debug_mode": False,
    }

    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = Path(path)
        self.data = dict(self.DEFAULTS)
        self.load()

    def load(self) -> None:
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data.update(raw)
            except Exception:
                pass

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def update(self, values: dict) -> None:
        """Apply many values with a single disk write."""
        self.data.update(values)
        self.save()

    def get(self, key: str, default=None):
        return self.data.get(key, default if default is not None else self.DEFAULTS.get(key))

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.save()


SETTINGS = SettingsManager()


class SettingsDialog(Gtk.Window):
    """Categorised, searchable-by-section preferences window."""

    CATEGORIES = (
        ("general", "General", "preferences-system-symbolic"),
        ("appearance", "Appearance & Theme", "applications-graphics-symbolic"),
        ("managers", "Package Managers", "package-symbolic"),
        ("updates", "Updates", "software-update-available-symbolic"),
        ("safety", "Safety & Confirmations", "channel-secure-symbolic"),
        ("advanced", "Advanced & Diagnostics", "utilities-system-monitor-symbolic"),
        ("about", "About", "help-about-symbolic"),
    )

    def __init__(self, app) -> None:
        parent = getattr(app, "window", None)
        super().__init__(transient_for=parent if isinstance(parent, Gtk.Window) else None, modal=True)
        self.app = app
        self.set_title("Pacmangr Settings")
        self.set_default_size(860, 640)
        self.set_resizable(True)

        self.controls: dict[str, tuple] = {}
        self.casters = {
            "max_results": int,
            "auto_refresh_interval": int,
            "cache_ttl": int,
            "font_scale": float,
        }

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(False)
        header.set_title_widget(Gtk.Label(label="Settings", css_classes=["title-label"]))

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)

        apply_btn = Gtk.Button(label="Apply")
        apply_btn.connect("clicked", lambda *_: self._apply(False))
        header.pack_end(apply_btn)

        save_btn = Gtk.Button(label="Save & Close")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda *_: self._apply(True))
        header.pack_end(save_btn)
        self.set_titlebar(header)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        side = Gtk.StackSidebar()
        side.set_stack(self.stack)
        side.set_size_request(190, -1)
        side.add_css_class("settings-sidebar")

        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        body.set_margin_top(12)
        body.set_margin_bottom(12)
        body.set_margin_start(12)
        body.set_margin_end(12)
        body.append(side)
        body.append(self.stack)
        self.set_child(body)

        self._build_general()
        self._build_appearance()
        self._build_managers()
        self._build_updates()
        self._build_safety()
        self._build_advanced()
        self._build_about()

    # ------------------------------------------------------------------
    # Page helpers
    # ------------------------------------------------------------------
    def _page(self, key: str, title: str, icon: str) -> Gtk.Box:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(6)
        box.set_margin_bottom(18)
        box.set_margin_start(8)
        box.set_margin_end(18)
        scroll.set_child(box)
        page = self.stack.add_titled(scroll, key, title)
        try:
            page.set_property("icon-name", icon)
        except Exception:
            pass
        return box

    @staticmethod
    def _section(box: Gtk.Box, text: str) -> None:
        label = Gtk.Label(label=text, xalign=0)
        label.add_css_class("section-label")
        label.set_margin_top(10)
        box.append(label)

    @staticmethod
    def _row(title: str, subtitle: str = ""):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        labels.set_hexpand(True)
        name = Gtk.Label(label=title, xalign=0)
        name.add_css_class("package-name")
        labels.append(name)
        if subtitle:
            sub = Gtk.Label(label=subtitle, xalign=0)
            sub.add_css_class("muted")
            sub.set_wrap(True)
            labels.append(sub)
        row.append(labels)
        return row

    def _switch(self, box: Gtk.Box, key: str, title: str, subtitle: str = "", active: bool = False) -> Gtk.Switch:
        row = self._row(title, subtitle)
        widget = Gtk.Switch()
        widget.set_active(bool(active))
        widget.set_valign(Gtk.Align.CENTER)
        row.append(widget)
        box.append(row)
        self.controls[key] = ("switch", widget, None)
        return widget

    def _dropdown(self, box: Gtk.Box, key: str, title: str, subtitle: str,
                  options: list[tuple[str, object]], current) -> Gtk.DropDown:
        row = self._row(title, subtitle)
        widget = Gtk.DropDown.new_from_strings([label for label, _ in options])
        values = [value for _, value in options]
        try:
            index = values.index(current)
        except ValueError:
            index = 0
        widget.set_selected(index)
        widget.set_size_request(230, -1)
        row.append(widget)
        box.append(row)
        self.controls[key] = ("dropdown", widget, values)
        return widget

    def _entry(self, box: Gtk.Box, key: str, title: str, subtitle: str,
               value: str, placeholder: str = "") -> Gtk.Entry:
        row = self._row(title, subtitle)
        widget = Gtk.Entry()
        widget.set_text(str(value or ""))
        if placeholder:
            widget.set_placeholder_text(placeholder)
        widget.set_size_request(250, -1)
        row.append(widget)
        box.append(row)
        self.controls[key] = ("entry", widget, None)
        return widget

    def _spin(self, box: Gtk.Box, key: str, title: str, subtitle: str,
              value, minimum: float, maximum: float, step: float) -> Gtk.SpinButton:
        row = self._row(title, subtitle)
        widget = Gtk.SpinButton.new_with_range(minimum, maximum, step)
        widget.set_value(float(value))
        widget.set_size_request(130, -1)
        row.append(widget)
        box.append(row)
        self.controls[key] = ("spin", widget, None)
        return widget

    def _file(self, box: Gtk.Box, key: str, title: str, subtitle: str, value: str) -> Gtk.Entry:
        row = self._row(title, subtitle)
        group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        entry = Gtk.Entry()
        entry.set_text(str(value or ""))
        entry.set_size_request(250, -1)
        button = Gtk.Button(label="Browse…")
        button.connect("clicked", lambda *_: self._choose_file(entry))
        group.append(entry)
        group.append(button)
        row.append(group)
        box.append(row)
        self.controls[key] = ("entry", entry, None)
        return entry

    def _action(self, box: Gtk.Box, title: str, subtitle: str, label: str, callback) -> Gtk.Button:
        row = self._row(title, subtitle)
        button = Gtk.Button(label=label)
        button.connect("clicked", callback)
        row.append(button)
        box.append(row)
        return button

    def _checks(self, box: Gtk.Box, key: str, title: str, subtitle: str,
                options: list[tuple[str, str]], current: dict) -> None:
        self._section(box, title)
        if subtitle:
            label = Gtk.Label(label=subtitle, xalign=0)
            label.add_css_class("muted")
            label.set_wrap(True)
            box.append(label)
        checks: dict[str, Gtk.CheckButton] = {}
        for label_text, manager_key in options:
            check = Gtk.CheckButton(label=label_text)
            check.set_active(bool(current.get(manager_key, True)))
            checks[manager_key] = check
            box.append(check)
        self.controls[key] = ("checks", checks, None)

    def _choose_file(self, entry: Gtk.Entry) -> None:
        dialog = Gtk.FileChooserDialog(
            title="Choose a file",
            transient_for=self,
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Open", Gtk.ResponseType.ACCEPT)

        def response(_dialog, result):
            if result == Gtk.ResponseType.ACCEPT:
                file = dialog.get_file()
                if file:
                    entry.set_text(file.get_path() or "")
            dialog.destroy()

        dialog.connect("response", response)
        dialog.present()

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------
    def _build_general(self) -> None:
        box = self._page(*self.CATEGORIES[0])
        self._section(box, "STARTUP")
        self._dropdown(
            box, "default_view", "Default view", "Which view opens when pacmangr starts.",
            [("Browse & Install", "browse"), ("Installed", "installed"),
             ("Updates", "updates"), ("GitHub", "github"),
             ("Orphaned Packages", "orphans")],
            SETTINGS.get("default_view", "browse"),
        )
        self._switch(
            box, "sidebar_collapsed", "Collapse navigation rail",
            "Start with the slim icon rail collapsed to a thin edge strip (Ctrl+B).",
            SETTINGS.get("sidebar_collapsed", False),
        )
        self._switch(
            box, "restore_last_source", "Restore last source", "Remember the selected package source between runs.",
            SETTINGS.get("restore_last_source", True),
        )
        self._switch(
            box, "persist_window_geometry", "Remember window size", "Save window dimensions and maximized state.",
            SETTINGS.get("persist_window_geometry", True),
        )

        self._section(box, "RESULTS")
        self._spin(
            box, "max_results", "Maximum results", "Cap the number of rows shown for a search.",
            SETTINGS.get("max_results", 250), 25, 2000, 25,
        )
        self._dropdown(
            box, "sort_mode", "Sort results", "Default ordering for search results.",
            [(label, value) for label, value in (
                ("Relevance", "relevance"), ("Name", "name"),
                ("Source", "source"), ("Installed first", "installed"),
            )],
            SETTINGS.get("sort_mode", "relevance"),
        )
        self._switch(
            box, "show_descriptions", "Show descriptions", "Display package summaries under each row.",
            SETTINGS.get("show_descriptions", True),
        )

    def _build_appearance(self) -> None:
        box = self._page(*self.CATEGORIES[1])
        self._section(box, "THEME SOURCE")
        self.theme_mode_combo = self._dropdown(
            box, "theme_mode", "Theme mode",
            "Automatic follows Heilios/matugen colours when available; no desktop dependency is required.",
            [
                ("Follow matugen/Heilios scheme (automatic)", "auto"),
                ("Matugen from wallpaper", "matugen"),
                ("Fixed accent", "accent"),
            ],
            SETTINGS.get("theme_mode", "auto"),
        )
        self._file(
            box, "scheme_path", "Scheme JSON path",
            "Heilios/caelestia scheme file used by the automatic mode.",
            SETTINGS.get("scheme_path", ""),
        )
        self._dropdown(
            box, "theme_accent", "Accent preset",
            "Used by 'Fixed accent' and by older configurations.",
            [
                ("Automatic / scheme", "auto"), ("Pac-Man Gold", "gold"),
                ("Cyberpunk Cyan", "cyan"), ("Neon Purple", "purple"),
                ("Emerald Green", "green"), ("Sunset Coral", "coral"),
            ],
            SETTINGS.get("theme_accent", "auto"),
        )

        self._section(box, "MATUGEN / WALLPAPER")
        self._file(
            box, "wallpaper_path", "Wallpaper image",
            "Generate a Material You palette from this image.",
            SETTINGS.get("wallpaper_path", ""),
        )
        self._dropdown(
            box, "matugen_scheme_type", "Matugen scheme type", "Colour scheme variant passed to matugen.",
            [(label, value) for label, value in (
                ("tonal-spot", "tonal-spot"), ("schema", "schema"),
                ("expressive", "expressive"), ("fruitsalt", "fruitsalt"),
                ("content", "content"), ("rainbow", "rainbow"),
            )],
            SETTINGS.get("matugen_scheme_type", "tonal-spot"),
        )
        self._entry(
            box, "matugen_binary", "Matugen binary", "Auto-detected when left as 'matugen'.",
            SETTINGS.get("matugen_binary", "matugen"),
        )
        self.matugen_status = Gtk.Label(label="", xalign=0)
        self.matugen_status.add_css_class("muted")
        self.matugen_status.set_wrap(True)
        self._action(
            box, "Generate & apply now", "Runs matugen once and switches to its palette.",
            "Generate theme", self._on_matugen,
        )
        box.append(self.matugen_status)

        self._section(box, "DENSITY & MOTION")
        density = SETTINGS.get("row_density", "normal")
        if density == "normal" and SETTINGS.get("compact_rows", False):
            density = "compact"  # Backwards compatibility with the old switch.
        self._dropdown(
            box, "row_density", "Row density", "Overrides the compact-row switch when not 'normal'.",
            [("Compact", "compact"), ("Normal", "normal"), ("Comfortable", "comfortable")],
            density,
        )
        self._switch(
            box, "compact_rows", "Compact list rows", "Legacy compact switch.",
            SETTINGS.get("compact_rows", False),
        )
        self._spin(
            box, "font_scale", "Font scale", "Scale interface text (1.0 is default).",
            SETTINGS.get("font_scale", 1.0), 0.8, 1.6, 0.05,
        )
        self._switch(
            box, "pacman_animation", "Pac-Man animation", "Animate the progress mascot during operations.",
            SETTINGS.get("pacman_animation", True),
        )

    def _build_managers(self) -> None:
        box = self._page(*self.CATEGORIES[2])
        self._section(box, "DEFAULTS")
        self._dropdown(
            box, "aur_helper", "Preferred AUR helper", "Auto-detect uses yay first, then paru.",
            [("Auto-detect", "auto"), ("yay", "yay"), ("paru", "paru"), ("Disabled", "disabled")],
            SETTINGS.get("aur_helper", "auto"),
        )
        self._dropdown(
            box, "pip_scope", "Default pip scope", "Where Python packages are installed by default.",
            [("Managed venv", "venv"), ("User directory", "user"), ("System", "system")],
            SETTINGS.get("pip_scope", "venv"),
        )
        self._entry(
            box, "preferred_terminal", "Preferred terminal", "Used by the 'Open in terminal' action.",
            SETTINGS.get("preferred_terminal", "auto"), "auto, foot, kitty, alacritty…",
        )
        self._checks(
            box, "enabled_managers", "ENABLED MANAGERS",
            "Disable a backend to keep it out of searches and update-all.",
            [
                ("pacman", "pacman"), ("AUR", "aur"), ("Flatpak", "flatpak"),
                ("APT", "apt"), ("Snap", "snap"), ("Cargo", "cargo"),
                ("npm", "npm"), ("pip", "pip"), ("Git", "git"),
                ("AppImages", "appimage"),
            ],
            dict(SETTINGS.get("enabled_managers", {})),
        )

    def _build_updates(self) -> None:
        box = self._page(*self.CATEGORIES[3])
        self._section(box, "UPDATE CHECKS")
        self._switch(
            box, "check_updates_on_launch", "Check on launch", "Count available updates when pacmangr starts.",
            SETTINGS.get("check_updates_on_launch", True),
        )
        self._switch(
            box, "auto_update_app", "Auto-update Pacmangr",
            "Check GitHub on launch and every six hours; install new commits for this user-local copy.",
            SETTINGS.get("auto_update_app", True),
        )
        self._action(
            box, "Pacmangr app updates", "Check GitHub and install the latest app files now.",
            "Check now", lambda *_: self.app.check_app_updates(manual=True),
        )
        self._spin(
            box, "auto_refresh_interval", "Auto-refresh interval", "Minutes between background checks (0 disables).",
            SETTINGS.get("auto_refresh_interval", 0), 0, 240, 5,
        )
        self._switch(
            box, "include_aur_updates", "Include AUR helpers", "Let update-all delegate to yay/paru when present.",
            SETTINGS.get("include_aur_updates", True),
        )
        self._switch(
            box, "include_flatpak_updates", "Include Flatpak", "Refresh Flatpak applications during update-all.",
            SETTINGS.get("include_flatpak_updates", True),
        )
        # The confirmation switch lives in Safety & Confirmations; see below.

    def _build_safety(self) -> None:
        box = self._page(*self.CATEGORIES[4])
        self._section(box, "CONFIRMATIONS")
        self._switch(
            box, "confirm_actions", "Confirm package actions", "Master switch for install/remove dialogs.",
            SETTINGS.get("confirm_actions", True),
        )
        self._switch(
            box, "confirm_install", "Confirm installs", "Ask before installing a package.",
            SETTINGS.get("confirm_install", True),
        )
        self._switch(
            box, "confirm_remove", "Confirm removals", "Ask before removing a package.",
            SETTINGS.get("confirm_remove", True),
        )
        self._switch(
            box, "confirm_update", "Confirm updates", "Ask before updating all sources.",
            SETTINGS.get("confirm_update", True),
        )
        self._switch(
            box, "confirm_orphan_removal", "Confirm orphan removal", "Ask before removing unused packages.",
            SETTINGS.get("confirm_orphan_removal", True),
        )
        self._switch(
            box, "skip_confirm_reinstall", "Skip reinstall confirmation", "Do not ask when reinstalling an installed package.",
            SETTINGS.get("skip_confirm_reinstall", False),
        )
        self._dropdown(
            box, "trash_or_delete", "Removal method", "Prefer trash for reversible file removals where supported.",
            [("Move to trash", "trash"), ("Permanent delete", "delete")],
            SETTINGS.get("trash_or_delete", "trash"),
        )

    def _build_advanced(self) -> None:
        box = self._page(*self.CATEGORIES[5])
        self._section(box, "CACHE")
        label = Gtk.Label(label=str(SETTINGS.path), xalign=0)
        label.add_css_class("muted")
        label.set_wrap(True)
        box.append(label)
        self._spin(
            box, "cache_ttl", "Cache TTL", "Seconds before cached search data is considered stale.",
            SETTINGS.get("cache_ttl", 3600), 0, 86400, 300,
        )
        self._action(
            box, "Clear local cache", "Removes cached metadata only; installed packages are untouched.",
            "Clear cache", lambda *_: self.app.confirm_clear_cache(),
        )

        self._section(box, "DIAGNOSTICS")
        self._dropdown(
            box, "log_level", "Log level", "Verbosity used by background operations.",
            [("Quiet", "quiet"), ("Info", "info"), ("Debug", "debug")],
            SETTINGS.get("log_level", "info"),
        )
        self._switch(
            box, "debug_mode", "Debug mode", "Show raw commands and extra status information.",
            SETTINGS.get("debug_mode", False),
        )
        self._action(
            box, "Export installed list", "Write a timestamped package list to your home directory.",
            "Export", lambda *_: self.app.export_package_list(),
        )
        self._action(
            box, "Package manager status", "Show detected manager paths and manager notes.",
            "Show status", lambda *_: self.app.show_manager_status(),
        )
        self._action(
            box, "Open configuration folder", "Open the folder containing gui_settings.json.",
            "Open folder", self._open_config_folder,
        )

    def _build_about(self) -> None:
        box = self._page(*self.CATEGORIES[6])
        title = Gtk.Label(label="pacmangr-gui", xalign=0)
        title.add_css_class("title-label")
        box.append(title)
        version = Gtk.Label(label=f"Version {CORE.VERSION}", xalign=0)
        version.add_css_class("muted")
        box.append(version)
        note = Gtk.Label(
            label=(
                "A graphical front-end for the pacmangr package manager toolkit.\n\n"
                "Package operations run through your system's native tools. "
                "Themes can follow Heilios/matugen colours or a fixed accent."
            ),
            xalign=0,
        )
        note.set_wrap(True)
        box.append(note)
        for label, uri in (
            ("Project homepage", "https://github.com/hei/pacmangr"),
            ("Report an issue", "https://github.com/hei/pacmangr/issues"),
        ):
            link = Gtk.LinkButton.new_with_label(uri, label)
            link.set_halign(Gtk.Align.START)
            box.append(link)
        self._action(
            box, "About dialog", "Open the standalone about window.",
            "Open about", self._show_about,
        )

    def _show_about(self, *_button) -> None:
        dialog = Gtk.AboutDialog()
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_program_name("pacmangr-gui")
        dialog.set_version(CORE.VERSION)
        dialog.set_comments("Graphical front-end for the pacmangr package manager toolkit.")
        dialog.set_website("https://github.com/hei/pacmangr")
        dialog.present()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _collect(self) -> dict:
        values: dict = {}
        for key, (kind, widget, extra) in self.controls.items():
            if kind == "switch":
                values[key] = bool(widget.get_active())
            elif kind == "dropdown":
                index = int(widget.get_selected())
                values[key] = extra[index] if 0 <= index < len(extra) else extra[0]
            elif kind == "entry":
                values[key] = widget.get_text().strip()
            elif kind == "spin":
                values[key] = widget.get_value()
            elif kind == "checks":
                values[key] = {name: bool(check.get_active()) for name, check in widget.items()}
        for key, caster in self.casters.items():
            if key in values:
                try:
                    values[key] = caster(values[key])
                except (TypeError, ValueError):
                    pass
        density = values.get("row_density", "normal")
        if density == "compact":
            values["compact_rows"] = True
        elif density == "normal":
            values["compact_rows"] = False
        else:
            values["compact_rows"] = False
        return values

    def _apply(self, close: bool) -> None:
        values = self._collect()
        SETTINGS.update(values)
        if hasattr(self.app, "apply_settings"):
            self.app.apply_settings()
        if close:
            self.close()

    def _on_matugen(self, *_button) -> None:
        from .theme import apply_matugen_from_wallpaper

        values = self._collect()
        wallpaper = Path(values.get("wallpaper_path", "")).expanduser()
        scheme_type = values.get("matugen_scheme_type", "tonal-spot")
        binary = values.get("matugen_binary", "matugen")
        ok, message = apply_matugen_from_wallpaper(wallpaper, scheme_type, binary)
        self.matugen_status.set_text(message)
        if ok:
            SETTINGS.set("theme_mode", "matugen")
            widgets = self.controls.get("theme_mode")
            if widgets:
                options = widgets[2]
                if "matugen" in options:
                    widgets[1].set_selected(options.index("matugen"))
            if hasattr(self.app, "apply_settings"):
                self.app.apply_settings()

    def _open_config_folder(self, *_button) -> None:
        folder = SETTINGS.path.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            Gtk.show_uri(self, folder.as_uri(), Gdk.CURRENT_TIME)
        except Exception:
            self.matugen_status.set_text(f"Configuration folder: {folder}")
