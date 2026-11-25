"""Shared detail pane with automatic details on row selection."""

# ruff: noqa: E402

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from .core_loader import CORE
from pacmangr_core.appimages import (
    integrate_appimage,
    launch_arguments,
    launch_environment,
    make_executable,
)
from .operations import fetch_github_files, fetch_github_readme, github_repo_slug
from .widgets import EmptyState


class DetailsPane(Gtk.Box):
    """The right-hand detail card, populated as soon as a row is clicked."""

    def __init__(self, app) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        self._detail_generation = 0
        self._detail_busy_tokens: set[str] = set()
        self._overview_cache: dict[tuple, tuple[str, bool]] = {}
        self._overview_loading_key: tuple | None = None
        self.add_css_class("detail-card")
        self.set_size_request(400, -1)
        self.set_vexpand(True)

        self.detail_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.detail_header.set_margin_top(24)
        self.detail_header.set_margin_start(18)
        self.detail_header.set_margin_end(18)

        self.detail_name = Gtk.Label(label="Select a package", xalign=0)
        self.detail_name.set_wrap(True)
        self.detail_name.set_hexpand(True)
        self.detail_name.set_halign(Gtk.Align.CENTER)
        self.detail_name.set_xalign(0.5)
        self.detail_name.add_css_class("title-label")
        self.detail_header.append(self.detail_name)

        self.status_pill = Gtk.Label(label="")
        self.status_pill.add_css_class("pill")
        self.status_pill.add_css_class("status-pill")
        self.status_pill.set_visible(False)
        self.detail_header.append(self.status_pill)
        self.append(self.detail_header)

        self.empty_state = EmptyState(
            "Select a package",
            "Choose a package to see its details and actions.",
            "package-x-generic-symbolic",
        )
        self.empty_state.set_hexpand(True)
        self.empty_state.set_vexpand(True)
        self.append(self.empty_state)

        self.detail_meta = Gtk.Label(label="Package details appear here.", xalign=0)
        self.detail_meta.set_wrap(True)
        self.detail_meta.set_halign(Gtk.Align.CENTER)
        self.detail_meta.set_xalign(0.5)
        self.detail_meta.add_css_class("muted")
        self.detail_meta.add_css_class("detail-meta")
        self.detail_meta.set_margin_top(4)
        self.detail_meta.set_margin_start(18)
        self.detail_meta.set_margin_end(18)
        self.append(self.detail_meta)

        self.detail_section = Gtk.Label(label="DETAILS", xalign=0)
        self.detail_section.add_css_class("section-label")
        self.detail_section.set_margin_top(12)
        self.detail_section.set_margin_start(18)
        self.detail_section.set_margin_end(18)
        self.append(self.detail_section)

        scroller = Gtk.ScrolledWindow()
        self.detail_scroller = scroller
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_margin_start(18)
        scroller.set_margin_end(18)
        self.detail_text = Gtk.TextView()
        self.detail_text.set_editable(False)
        self.detail_text.set_cursor_visible(False)
        self.detail_text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.detail_text.set_monospace(True)
        self.detail_text.add_css_class("detail-mono")
        self.detail_text.set_top_margin(4)
        self.detail_text.set_bottom_margin(4)
        self.detail_text.set_left_margin(8)
        self.detail_text.set_right_margin(8)
        scroller.set_child(self.detail_text)
        self.append(scroller)

        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        actions.add_css_class("detail-actions")
        actions.set_margin_start(18)
        actions.set_margin_end(18)
        actions.set_margin_bottom(18)
        actions.set_visible(False)
        self.detail_actions = actions

        # Selecting a row loads details; this button shows the cached overview.
        self.info_button = Gtk.Button(label="Overview")
        self.info_button.add_css_class("tab-btn")
        self.info_button.set_sensitive(False)
        self.info_button.connect("clicked", self.on_info)
        self.info_button.set_hexpand(True)

        self.versions_button = Gtk.Button(label="Versions")
        self.versions_button.add_css_class("tab-btn")
        self.versions_button.set_sensitive(False)
        self.versions_button.connect("clicked", self.on_versions)
        self.versions_button.set_hexpand(True)

        self.files_button = Gtk.Button(label="Files")
        self.files_button.add_css_class("tab-btn")
        self.files_button.set_sensitive(False)
        self.files_button.connect("clicked", self.on_package_files)
        self.files_button.set_hexpand(True)

        self.copy_button = Gtk.Button(label="Copy Name")
        self.copy_button.add_css_class("flat")
        self.copy_button.set_sensitive(False)
        self.copy_button.connect("clicked", self.on_copy_name)
        self.copy_button.set_hexpand(True)

        self.run_button = Gtk.Button(label="Run AppImage")
        self.run_button.add_css_class("suggested-action")
        self.run_button.set_sensitive(False)
        self.run_button.set_visible(False)
        self.run_button.connect("clicked", self.on_run_appimage)
        self.run_button.set_hexpand(True)

        self.install_button = Gtk.Button(label="Install")
        self.install_button.add_css_class("suggested-action")
        self.install_button.set_sensitive(False)
        self.install_button.connect(
            "clicked", lambda *_: self.app.confirm_action("install")
        )
        self.install_button.set_hexpand(True)

        self.remove_button = Gtk.Button(label="Remove")
        self.remove_button.add_css_class("danger")
        self.remove_button.set_sensitive(False)
        self.remove_button.connect(
            "clicked", lambda *_: self.app.confirm_action("remove")
        )
        self.remove_button.set_hexpand(True)

        self.website_button = Gtk.Button(label="Website")
        self.website_button.add_css_class("flat")
        self.website_button.add_css_class("link-button")
        self.website_button.set_sensitive(False)
        self.website_button.connect("clicked", self.on_open_website)
        self.website_button.set_hexpand(True)

        info_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for button in (self.info_button, self.versions_button, self.files_button):
            info_row.append(button)
        utility_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        utility_row.append(self.copy_button)
        utility_row.append(self.run_button)
        utility_row.append(self.website_button)
        operation_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        operation_row.append(self.install_button)
        operation_row.append(self.remove_button)
        actions.append(info_row)
        actions.append(utility_row)
        actions.append(operation_row)

        self.append(actions)
        self.reset()

    # ------------------------------------------------------------------
    # Presentation
    # ------------------------------------------------------------------
    def set_text(self, text: str) -> None:
        self.set_text_style(readme=False)
        self.detail_text.get_buffer().set_text(text)

    def set_text_style(self, readme: bool) -> None:
        self.detail_text.set_monospace(not readme)
        if readme:
            self.detail_text.remove_css_class("detail-mono")
            self.detail_text.add_css_class("readme-text")
        else:
            self.detail_text.remove_css_class("readme-text")
            self.detail_text.add_css_class("detail-mono")

    def set_readme(self, text: str) -> None:
        self.set_text_style(readme=True)
        buffer = self.detail_text.get_buffer()
        buffer.set_text(text)
        table = buffer.get_tag_table()
        heading = table.lookup("readme-heading")
        if heading is None:
            heading = Gtk.TextTag.new("readme-heading")
            heading.set_property("weight", Pango.Weight.BOLD)
            heading.set_property("scale", 1.12)
            heading.set_property("pixels-above-lines", 10)
            heading.set_property("pixels-below-lines", 3)
            table.add(heading)
        code = table.lookup("readme-code")
        if code is None:
            code = Gtk.TextTag.new("readme-code")
            code.set_property("family", "monospace")
            table.add(code)

        lines = text.splitlines()
        for index, line in enumerate(lines):
            start = buffer.get_iter_at_line(index)
            end = start.copy()
            end.forward_to_line_end()
            if index + 1 < len(lines) and lines[index + 1].startswith("─"):
                buffer.apply_tag(heading, start, end)
            elif line.startswith("    "):
                buffer.apply_tag(code, start, end)

    def reset(self) -> None:
        self._cancel_detail_activity()
        self.detail_header.set_margin_top(24)
        self.detail_name.set_text("Select a package")
        self.detail_name.set_halign(Gtk.Align.CENTER)
        self.detail_name.set_xalign(0.5)
        self.status_pill.set_label("")
        self.status_pill.set_visible(False)
        self.status_pill.remove_css_class("orphan-pill")
        self.empty_state.set_visible(True)
        self.detail_header.set_visible(False)
        self.detail_meta.set_visible(False)
        self.detail_meta.set_text(
            "Package details appear here. Click a package to load its details."
        )
        self.detail_meta.set_halign(Gtk.Align.CENTER)
        self.detail_meta.set_xalign(0.5)
        self.set_text("")
        self.detail_section.set_visible(False)
        self.detail_scroller.set_visible(False)
        for button in (
            self.info_button,
            self.versions_button,
            self.files_button,
            self.copy_button,
            self.website_button,
            self.install_button,
            self.remove_button,
        ):
            button.set_sensitive(False)
        self.versions_button.set_visible(False)
        self.run_button.set_visible(False)
        self.detail_actions.set_visible(False)

    def show(self, item) -> None:
        self._cancel_detail_activity()
        self.detail_header.set_margin_top(16)
        self.empty_state.set_visible(False)
        self.detail_header.set_visible(True)
        self.detail_meta.set_visible(True)
        self.detail_section.set_visible(True)
        self.detail_scroller.set_visible(True)
        self.detail_name.set_text(item.title())
        self.detail_name.set_halign(Gtk.Align.START)
        self.detail_name.set_xalign(0.0)
        self.detail_meta.set_halign(Gtk.Align.START)
        self.detail_meta.set_xalign(0.0)

        state = "installed" if item.installed else "available to install"
        if getattr(item, "is_orphan", False):
            state = "installed (unused orphan)"
        elif getattr(item, "install_reason", "") == "explicit":
            state = "installed explicitly"
        elif getattr(item, "install_reason", "") == "dependency":
            state = "installed as dependency"

        pill_text = (
            "orphan"
            if getattr(item, "is_orphan", False)
            else ("installed" if item.installed else "available")
        )
        self.status_pill.set_label(pill_text)
        self.status_pill.set_visible(True)
        if pill_text == "orphan":
            self.status_pill.add_css_class("orphan-pill")
        else:
            self.status_pill.remove_css_class("orphan-pill")

        meta = [
            f"source: {item.source} · {state}",
            f"package: {item.package_id}",
            f"version: {item.version or 'unknown'}",
        ]
        if item.repo:
            meta.append(f"repository: {item.repo}")
        self.detail_meta.set_text("\n".join(meta))

        description = item.description or "No description available."
        if item.source == "nix" or item.manager == "nix":
            description += (
                "\n\nPacmangr changes only your imperative Nix profile. "
                "Declarative NixOS or Home Manager files are left untouched."
            )
        self.set_text(description)
        self.detail_actions.set_visible(True)
        self.info_button.set_label(
            "README" if self._is_github_item(item) else "Overview"
        )
        self.info_button.set_sensitive(True)
        supports_versions = item.source in {
            "pacman",
            "aur",
            "aur/local",
            "apt",
        } or item.manager in {"pacman", "yay", "paru"}
        self.versions_button.set_visible(supports_versions)
        self.versions_button.set_sensitive(supports_versions)
        self.files_button.set_sensitive(
            bool(item.installed) or self._is_github_item(item)
        )
        self.copy_button.set_sensitive(True)
        self.website_button.set_sensitive(True)
        self.install_button.set_label("Reinstall" if item.installed else "Install")
        if item.source == "git":
            self.install_button.set_label(
                "Update checkout" if item.installed else "Clone repository"
            )
        tools = self.app.tools
        appimage_catalog_item = item.source == "appimage" and bool(item.origin)
        self.install_button.set_sensitive(
            (appimage_catalog_item and (not item.installed or bool(getattr(item, "local_path", ""))))
            or (
                item.source != "appimage"
                and (item.source != "git" or bool(getattr(tools, "git", None)))
            )
        )
        self.remove_button.set_sensitive(
            item.installed and item.source != "git"
        )
        self.run_button.set_visible(item.source == "appimage" and item.installed)
        self.run_button.set_sensitive(
            item.source == "appimage"
            and item.installed
            and bool(getattr(item, "local_path", "") or item.package_id.startswith("/"))
        )

    def set_loading(self, item) -> None:
        self.set_text(f"Loading full details for {item.title()}…")

    def _cancel_detail_activity(self) -> None:
        self._detail_generation += 1
        self._overview_loading_key = None
        for token in tuple(self._detail_busy_tokens):
            self.app.end_busy(token)
        self._detail_busy_tokens.clear()

    def _begin_detail_activity(self, status: str) -> int:
        self._cancel_detail_activity()
        token = f"details:{self._detail_generation}"
        self._detail_busy_tokens.add(token)
        self.app.begin_busy(token)
        self.app.set_status(status)
        return self._detail_generation

    def _end_detail_activity(self, generation: int) -> None:
        token = f"details:{generation}"
        if token in self._detail_busy_tokens:
            self._detail_busy_tokens.remove(token)
            self.app.end_busy(token)

    # ------------------------------------------------------------------
    # Detail actions
    # ------------------------------------------------------------------
    @staticmethod
    def _is_github_item(item) -> bool:
        if getattr(item, "github_full_name", ""):
            return True
        if item.source != "git":
            return False
        return bool(github_repo_slug(item))

    def on_info(self, *_args) -> None:
        item = self.app.current_item
        if not item:
            return
        key = (item.source, item.package_id, item.origin)
        cached = self._overview_cache.get(key)
        if cached:
            text, is_readme = cached
            if is_readme:
                self.set_readme(text)
            else:
                self.set_text(text)
            return
        if self._overview_loading_key == key:
            return
        if self._is_github_item(item):
            self._load_readme(item)
            return
        if item.source == "appimage":
            self.set_text(item.description or "No details are available.")
            self.app.set_status(f"Overview shown for {item.title()}.")
            return
        installed_view = self.app.view_mode in {"installed", "orphans"} or bool(
            item.installed
        )
        command = item.info_command(self.app.tools, installed_view)
        if not command:
            self._cancel_detail_activity()
            self.app.set_status(f"No details are available for {item.title()}.")
            return
        self.set_loading(item)
        generation = self._begin_detail_activity(f"Loading details for {item.title()}…")
        self._overview_loading_key = key

        def worker() -> None:
            try:
                code, output = CORE.run_capture(command, timeout=30)
            except Exception as exc:
                code, output = 126, str(exc)
            GLib.idle_add(self.finish_info, item, code, output, generation)

        threading.Thread(target=worker, daemon=True).start()

    def _load_readme(self, item) -> None:
        slug = github_repo_slug(item) or getattr(
            item, "github_full_name", "this repository"
        )
        key = (item.source, item.package_id, item.origin)
        cached = self._overview_cache.get(key)
        if cached and cached[1]:
            self.set_readme(cached[0])
            return
        self.set_text(f"Loading README.md for {slug}…")
        generation = self._begin_detail_activity(f"Loading README.md for {slug}…")
        self._overview_loading_key = key

        def worker() -> None:
            try:
                text, error = fetch_github_readme(item)
            except Exception as exc:  # noqa: BLE001 - keep detail loading graceful.
                text, error = "", str(exc)
            GLib.idle_add(self.finish_readme, item, slug, text, error, generation)

        threading.Thread(target=worker, daemon=True).start()

    def finish_readme(
        self, item, slug: str, text: str, error: str, generation: int | None = None
    ) -> bool:
        if generation is None:
            generation = self._detail_generation
        self._end_detail_activity(generation)
        if generation != self._detail_generation or self.app.current_item is not item:
            return False
        self._overview_loading_key = None
        if error:
            self.set_text(error)
            self.app.set_status(error)
            return False
        self.set_readme(text)
        self._overview_cache[(item.source, item.package_id, item.origin)] = (text, True)
        self.app.set_status(f"Loaded README.md for {slug}")
        return False

    def finish_info(
        self, item, code: int, output: str, generation: int | None = None
    ) -> bool:
        if generation is None:
            generation = self._detail_generation
        self._end_detail_activity(generation)
        if generation != self._detail_generation or self.app.current_item is not item:
            return False
        self._overview_loading_key = None
        text = output.strip() or "No details are available."
        self.set_text(text)
        if code == 0:
            self._overview_cache[(item.source, item.package_id, item.origin)] = (
                text,
                False,
            )
        self.app.set_status(
            f"Loaded details for {item.title()}."
            if code == 0
            else f"Details command exited {code}."
        )
        return False

    def on_versions(self, *_args) -> None:
        item = self.app.current_item
        if not item:
            return
        manager = item.manager or item.source
        cached = self.app.cache.load_versions(manager, item.package_id)
        if cached:
            self.set_text(CORE.format_versions(item.package_id, cached))
        generation = self._begin_detail_activity(
            f"Checking versions for {item.title()}…"
        )

        def worker() -> None:
            try:
                versions = CORE.package_versions(self.app.tools, item)
                if versions:
                    self.app.cache.save_versions(manager, item.package_id, versions)
                GLib.idle_add(self.finish_versions, item, versions, "", generation)
            except Exception as exc:
                GLib.idle_add(self.finish_versions, item, [], str(exc), generation)

        threading.Thread(target=worker, daemon=True).start()

    def finish_versions(
        self, item, versions: list, error: str, generation: int | None = None
    ) -> bool:
        if generation is None:
            generation = self._detail_generation
        self._end_detail_activity(generation)
        if generation != self._detail_generation or self.app.current_item is not item:
            return False
        if error:
            self.app.set_status(f"Version check failed: {error}")
            return False
        self.set_text(CORE.format_versions(item.package_id, versions))
        self.app.set_status(f"Found {len(versions)} versions for {item.title()}.")
        return False

    def on_package_files(self, *_args) -> None:
        item = self.app.current_item
        if not item:
            return
        if self._is_github_item(item):
            self.set_text(f"Loading files for {github_repo_slug(item)}…")
            generation = self._begin_detail_activity(
                f"Loading repository files for {item.title()}…"
            )

            def github_worker() -> None:
                try:
                    text, error = fetch_github_files(item)
                except Exception as exc:
                    text, error = "", str(exc)
                GLib.idle_add(self._finish_github_files, item, text, error, generation)

            threading.Thread(target=github_worker, daemon=True).start()
            return
        generation = self._begin_detail_activity(
            f"Listing installed files for {item.title()}…"
        )

        def worker() -> None:
            try:
                pacman = getattr(self.app.tools, "pacman", None) or shutil.which(
                    "pacman"
                )
                if pacman and item.source in {"pacman", "aur", "aur/local"}:
                    out = subprocess.check_output(
                        [pacman, "-Ql", item.name], text=True, stderr=subprocess.STDOUT
                    )
                else:
                    out = f"File listing is not supported for {item.source} packages."
                GLib.idle_add(self._finish_package_files, item, out, generation)
            except subprocess.CalledProcessError as err:
                GLib.idle_add(
                    self._finish_package_files,
                    item,
                    f"Could not list files: {err.output}",
                    generation,
                )
            except Exception as exc:
                GLib.idle_add(
                    self._finish_package_files, item, f"Error: {exc}", generation
                )

        threading.Thread(target=worker, daemon=True).start()

    def _finish_github_files(
        self, item, text: str, error: str, generation: int | None = None
    ) -> bool:
        if generation is None:
            generation = self._detail_generation
        self._end_detail_activity(generation)
        if generation != self._detail_generation or self.app.current_item is not item:
            return False
        self.set_text(error or text)
        self.app.set_status(error or f"Loaded repository files for {item.title()}.")
        return False

    def _finish_package_files(
        self, item, output: str, generation: int | None = None
    ) -> bool:
        if generation is None:
            generation = self._detail_generation
        self._end_detail_activity(generation)
        if generation != self._detail_generation or self.app.current_item is not item:
            return False
        self.set_text(output.strip() or "No files found.")
        self.app.set_status(f"Loaded files for {item.title()}.")
        return False

    def on_copy_name(self, *_args) -> None:
        if not self.app.current_item:
            return
        name = self.app.current_item.name
        display = Gdk.Display.get_default()
        if display:
            display.get_clipboard().set(name)
            self.app.set_status(f"Copied '{name}' to clipboard.", duration_ms=2200)

    def on_run_appimage(self, *_args) -> None:
        item = self.app.current_item
        if not item or item.source != "appimage":
            return
        path_value = getattr(item, "local_path", "")
        if not path_value and item.package_id.startswith("/"):
            path_value = item.package_id
        path = Path(path_value).expanduser() if path_value else None
        if path is None or not path.is_file():
            self.app.set_status(f"The AppImage file for {item.title()} could not be found.")
            return
        try:
            path = make_executable(path)
            try:
                integrate_appimage(path, item.title())
                integration_error = ""
            except OSError as exc:
                integration_error = str(exc)
            subprocess.Popen(
                launch_arguments(path),
                cwd=str(path.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=launch_environment(),
                start_new_session=True,
            )
        except OSError as exc:
            self.app.set_status(f"Could not launch {item.title()}: {exc}")
            return
        self.app.set_status(
            f"Launched and integrated {item.title()}."
            if not integration_error
            else f"Launched {item.title()}, but menu integration failed: {integration_error}"
        )

    def on_open_website(self, *_args) -> None:
        item = self.app.current_item
        if not item:
            return

        def worker() -> None:
            url = ""
            if item.origin and item.origin.startswith(("http://", "https://")):
                url = item.origin
            elif item.source in {"pacman", "aur", "aur/local"}:
                pacman = getattr(self.app.tools, "pacman", None) or shutil.which(
                    "pacman"
                )
                if pacman:
                    try:
                        out = subprocess.check_output(
                            [pacman, "-Qi", item.name],
                            text=True,
                            stderr=subprocess.DEVNULL,
                        )
                        for line in out.splitlines():
                            if line.startswith("URL"):
                                parts = line.split(":", 1)
                                if len(parts) > 1:
                                    url = parts[1].strip()
                                    break
                    except Exception:
                        pass
            if not url:
                if item.source in {"aur", "aur/local"}:
                    url = f"https://aur.archlinux.org/packages/{item.name}"
                else:
                    url = f"https://archlinux.org/packages/?q={item.name}"
            GLib.idle_add(self._launch_url, url)

        threading.Thread(target=worker, daemon=True).start()

    def _launch_url(self, url: str) -> bool:
        if url:
            try:
                Gtk.show_uri(self.app.window, url, Gdk.CURRENT_TIME)
                self.app.set_status(f"Opened {url}")
            except Exception as exc:
                self.app.set_status(f"Could not open link: {exc}")
        return False
