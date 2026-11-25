"""The five navigable content views and their search/filter/load logic."""

# Views: Browse & Install, Installed, Updates, GitHub and Orphaned Packages.
# ruff: noqa: E402

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gtk

from .core_loader import CORE, MAX_GUI_RESULTS
from .operations import (
    available_update_lines,
    collect_installed_metadata,
    github_repo_slug,
    orphan_remove_command,
    resolve_github_default_branch,
)
from .settings import SETTINGS
from .widgets import EmptyState, PackageRow, load_source_icon

KIND_OPTIONS = ("all", "explicit", "dependency", "orphan")
KINDS = KIND_OPTIONS


class ResultList(Gtk.Box):
    """Heading + scrollable package list shared by every view."""

    def __init__(self, app, *, placeholder: str = "Nothing to show yet.") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.app = app
        self.add_css_class("search-card")
        self.set_hexpand(True)
        self.set_vexpand(True)

        self.heading = Gtk.Label(label="Packages", xalign=0)
        self.heading.add_css_class("title-label")
        self.heading.set_margin_top(14)
        self.heading.set_margin_start(16)
        self.heading.set_margin_end(16)
        self.append(self.heading)

        self.placeholder = EmptyState(
            "No packages to show", placeholder, "edit-find-symbolic"
        )
        self.list_box = Gtk.ListBox()
        self.list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.list_box.connect("row-selected", self._row_selected)
        try:
            self.list_box.set_placeholder(self.placeholder)
        except Exception:
            pass

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self.list_box)
        scroller.set_vexpand(True)
        self.append(scroller)

    def _row_selected(self, list_box, row) -> None:
        if self.app:
            self.app.on_row_selected(list_box, row)

    def clear(self) -> None:
        while child := self.list_box.get_first_child():
            self.list_box.remove(child)

    def populate(
        self, items: list, heading: str, *, auto_select: bool = True, row_factory=None
    ) -> None:
        self.heading.set_text(heading)
        self.clear()
        compact = self.app.view_mode in {"installed", "orphans"}
        for item in items:
            if row_factory is not None:
                row = row_factory(item)
            else:
                row = PackageRow(item, compact=compact)
            self.list_box.append(row)
        if items and auto_select:
            first = self.list_box.get_row_at_index(0)
            if first:
                self.list_box.select_row(first)

    def append_items(self, items: list, heading: str) -> None:
        """Append newly completed backend results without disturbing selection."""
        self.heading.set_text(heading)
        existing = {
            (row.item.source, row.item.package_id)
            for row in self._rows()
            if getattr(row, "item", None) is not None
        }
        max_rows = max(1, int(SETTINGS.get("max_results", MAX_GUI_RESULTS)))
        if len(existing) >= max_rows:
            return
        compact = self.app.view_mode in {"installed", "orphans"}
        for item in items:
            key = (item.source, item.package_id)
            if key in existing or len(existing) >= max_rows:
                continue
            self.list_box.append(PackageRow(item, compact=compact))
            existing.add(key)

    def _rows(self):
        row = self.list_box.get_first_child()
        while row is not None:
            yield row
            row = row.get_next_sibling()


class BaseView(Gtk.Box):
    def __init__(self, app, key: str) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        self.key = key
        self.toolbar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        self.toolbar.add_css_class("view-toolbar")
        self.toolbar.set_hexpand(True)
        self.result_list = ResultList(app)
        self.append(self.toolbar)
        self.append(self.result_list)

    def focus(self) -> None:
        pass

    def refresh(self) -> None:
        pass

    def set_placeholder(self, title: str, detail: str, icon: str = "") -> None:
        self.result_list.placeholder = EmptyState(title, detail, icon)
        try:
            self.result_list.list_box.set_placeholder(self.result_list.placeholder)
        except Exception:
            pass


class BrowseView(BaseView):
    """Search across all sources, GitHub and git URLs."""

    def __init__(self, app, sources: list[tuple[str, str]]) -> None:
        super().__init__(app, "browse")
        self.sources = sources

        # Source sits directly beside the search field; no separate filter row.
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        search_row.add_css_class("search-control")
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.add_css_class("search-field")
        self.search_entry.set_placeholder_text(
            "Search packages, or find repositories on GitHub…"
        )
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("activate", self.on_search)
        search_row.append(self.search_entry)

        self.source_dropdown = Gtk.DropDown.new_from_strings(
            [label for label, _key in self.sources]
        )
        self.source_dropdown.add_css_class("search-source")
        self.source_dropdown.set_tooltip_text("Choose which package source to search")
        self.source_dropdown.set_size_request(154, -1)
        self.source_dropdown.connect("notify::selected", self.on_source_changed)
        search_row.append(self.source_dropdown)

        self.search_button = Gtk.Button.new_from_icon_name("system-search-symbolic")
        self.search_button.add_css_class("search-button")
        self.search_button.add_css_class("browse-search-button")
        self.search_button.set_tooltip_text("Search packages")
        self.search_button.connect("clicked", self.on_search)
        search_row.append(self.search_button)
        self.toolbar.append(search_row)

    def focus(self) -> None:
        self.search_entry.grab_focus()

    def selected_source(self) -> str:
        index = min(int(self.source_dropdown.get_selected()), len(self.sources) - 1)
        return self.sources[index][1]

    def selected_label(self) -> str:
        index = min(int(self.source_dropdown.get_selected()), len(self.sources) - 1)
        return self.sources[index][0]

    def update_controls(self) -> None:
        backend = self.selected_source()
        if backend == "github":
            placeholder = "Search GitHub repositories by name, topic, or description"
            button = "Search GitHub"
        elif backend == "git":
            placeholder = "Paste an HTTPS, SSH, or git@ repository URL"
            button = "Clone repository"
        else:
            placeholder = "Search packages across your enabled sources…"
            button = "Search packages"
        self.search_entry.set_placeholder_text(placeholder)
        self.search_button.set_tooltip_text(button)

    def on_source_changed(self, _dropdown=None, _param=None) -> None:
        self.update_controls()
        if getattr(self.app, "browse_query", ""):
            self.on_search(None)

    def on_search(self, _widget=None) -> None:
        query = self.search_entry.get_text().strip()
        if not query:
            self.app.set_status("Type a package name first.")
            self.search_entry.grab_focus()
            return

        app = self.app
        app.browse_query = query
        app.request_id += 1
        request_id = app.request_id
        backend = self.selected_source()
        source_label = self.selected_label()

        app.begin_search_activity(request_id)
        app.browse_items = []
        self.result_list.clear()
        self.result_list.heading.set_text("Searching…")
        if app.details:
            app.details.reset()

        if backend == "github":
            self._github_search(query, request_id)
            return
        if backend == "all" and CORE.is_git_url(query):
            backend = "git"
            source_label = "Git repository"
        app.set_status(f"Searching {source_label.lower()} for {query!r}…")

        def worker() -> None:
            try:
                engine = app.get_search_engine()
                managers = engine.enabled_search_managers(backend)
                cached = engine.cache.load_search(query, managers)
                cached = engine.rank_results(engine.dedupe_items(cached), query)
                if request_id == app.request_id and cached:
                    GLib.idle_add(self._show_cached_results, request_id, cached, query)

                def on_results(partial: list) -> None:
                    merged = engine.dedupe_items(cached + partial)
                    ranked = engine.rank_results(merged, query)
                    GLib.idle_add(self._show_partial_results, request_id, query, ranked)

                results = engine.search_packages(query, backend, on_results=on_results)
                results = engine.rank_results(
                    engine.dedupe_items(cached + results), query
                )
                GLib.idle_add(self.finish_search, request_id, query, results, "")
            except Exception as exc:
                GLib.idle_add(self.finish_search, request_id, query, [], str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_cached_results(self, request_id: int, items: list, query: str) -> bool:
        if request_id == self.app.request_id and self.app.view_mode == "browse":
            self.app.show_search_progress(items, f"Results for “{query}” · refreshing")
        return False

    def _show_partial_results(self, request_id: int, query: str, items: list) -> bool:
        if request_id == self.app.request_id and self.app.view_mode == "browse":
            self.app.show_search_progress(items, f"Results for “{query}” · updating")
        return False

    def _github_search(self, query: str, request_id: int) -> None:
        self.app.set_status(f"Searching GitHub for {query!r}…")

        def worker() -> None:
            try:
                params = urllib.parse.urlencode(
                    {"q": query, "sort": "stars", "order": "desc", "per_page": 30}
                )
                request = urllib.request.Request(
                    f"https://api.github.com/search/repositories?{params}",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "Pacmangr-GUI",
                    },
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8"))

                results = GitHubView._to_items(payload)
                GLib.idle_add(self.finish_search, request_id, query, results, "")
            except Exception as exc:
                GLib.idle_add(
                    self.finish_search,
                    request_id,
                    query,
                    [],
                    f"GitHub search failed: {exc}",
                )

        threading.Thread(target=worker, daemon=True).start()

    def finish_search(
        self, request_id: int, query: str, items: list, error: str
    ) -> bool:
        app = self.app
        app.end_search_activity(request_id)
        if request_id != app.request_id or app.view_mode != "browse":
            return False
        if error:
            app.set_status(f"Search failed: {error}")
            return False
        app.browse_items = items
        app.show_items(items, f"Results for “{query}”")
        max_r = int(SETTINGS.get("max_results", MAX_GUI_RESULTS))
        suffix = f" · showing first {max_r}" if len(items) > max_r else ""
        noun = "repositories" if self.selected_source() == "github" else "packages"
        app.set_status(f"Found {len(items)} {noun}{suffix}.")
        return False


class InstalledView(BaseView):
    """Filterable installed-package inventory with orphan classification."""

    def __init__(self, app, sources: list[tuple[str, str]]) -> None:
        super().__init__(app, "installed")
        self.sources = sources
        self._load_serial = 0

        # Source belongs beside the filter field; no SOURCE label/row.
        filter_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        filter_row.add_css_class("search-control")
        self.filter_entry = Gtk.SearchEntry()
        self.filter_entry.add_css_class("search-field")
        self.filter_entry.set_placeholder_text(
            "Filter installed packages by name, description, or tag…"
        )
        self.filter_entry.set_hexpand(True)
        self.filter_entry.connect("search-changed", self.on_filter_changed)
        filter_row.append(self.filter_entry)

        self.source_dropdown = Gtk.DropDown.new_from_strings(
            [label for label, _key in self.sources]
        )
        self.source_dropdown.add_css_class("search-source")
        self.source_dropdown.set_tooltip_text("Filter by package source")
        self.source_dropdown.set_size_request(150, -1)
        self.source_dropdown.connect(
            "notify::selected", lambda *_: self.filter_installed()
        )
        filter_row.append(self.source_dropdown)
        self.toolbar.append(filter_row)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.kind_dropdown = Gtk.DropDown.new_from_strings(
            ["All packages", "Explicitly installed", "Dependencies", "Orphans"]
        )
        self.kind_dropdown.set_tooltip_text(
            "Filter installed packages by install reason"
        )
        self.kind_dropdown.set_size_request(190, -1)
        self.kind_dropdown.set_selected(0)
        self.kind_dropdown.connect("notify::selected", self.on_kind_changed)
        action_row.append(self.kind_dropdown)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        action_row.append(spacer)

        refresh = Gtk.Button()
        refresh.set_child(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        refresh.set_tooltip_text("Refresh installed packages (F5)")
        refresh.connect("clicked", lambda *_: self.load_installed(force=True))
        refresh.add_css_class("pill-button")
        action_row.append(refresh)
        self.toolbar.append(action_row)

    def focus(self) -> None:
        self.filter_entry.grab_focus()

    def on_filter_changed(self, entry: Gtk.SearchEntry) -> None:
        self.app.installed_filter_query = entry.get_text().strip().lower()
        self.filter_installed()

    def on_kind_changed(self, dropdown, _param=None) -> None:
        index = int(dropdown.get_selected())
        kind = KIND_OPTIONS[min(index, len(KIND_OPTIONS) - 1)]
        self.app.installed_kind_filter = kind
        self.filter_installed()

    def set_kind_filter(self, kind: str) -> None:
        if kind not in KINDS:
            return
        self.app.installed_kind_filter = kind
        self.kind_dropdown.set_selected(KIND_OPTIONS.index(kind))
        self.filter_installed()

    def selected_source(self) -> str:
        index = min(int(self.source_dropdown.get_selected()), len(self.sources) - 1)
        return self.sources[index][1]

    def source_matches(self, item, source: str) -> bool:
        if source == "all":
            return True
        if source in {"yay", "paru"}:
            return item.manager == source or item.source in {source, "aur", "aur/local"}
        return item.source == source or item.manager == source

    def filter_installed(self) -> None:
        app = self.app
        if not app.all_installed and not app.installed_loaded:
            return
        query = app.installed_filter_query
        kind = app.installed_kind_filter
        source = self.selected_source()
        index = min(int(self.source_dropdown.get_selected()), len(self.sources) - 1)

        filtered = []
        for item in app.all_installed:
            if source != "all" and not self.source_matches(item, source):
                continue
            if kind == "orphan" and not getattr(item, "is_orphan", False):
                continue
            if kind == "explicit" and getattr(item, "install_reason", "") != "explicit":
                continue
            if (
                kind == "dependency"
                and getattr(item, "install_reason", "") != "dependency"
            ):
                continue
            if query:
                haystack = (
                    f"{item.name} {item.package_id} {item.description or ''}".lower()
                )
                if query not in haystack:
                    continue
            filtered.append(item)

        heading_parts = ["Installed packages"]
        if source != "all":
            heading_parts.append(f"from {self.sources[index][0]}")
        if kind != "all":
            heading_parts.append(f"({kind} only)")
        if app.view_mode == "installed":
            app.show_items(
                filtered, " · ".join(heading_parts), remember=False, auto_select=False
            )
            app.set_status(f"{len(filtered)} installed packages matching filter.")

    def load_installed(self, force: bool = False) -> None:
        app = self.app
        show_progress = app.view_mode == "installed"
        self._load_serial += 1
        busy_token = f"installed-load:{self._load_serial}" if show_progress else ""
        if show_progress:
            app.begin_busy(busy_token)
            app.set_status("Scanning installed packages…")
        cached = app.cache.load_installed() if not force else None
        if cached:
            self._apply_installed_data(cached)

        def worker() -> None:
            try:
                explicit, deps, orphans = collect_installed_metadata(
                    getattr(app.tools, "pacman", None)
                )
                items = CORE.collect_installed_packages(app.tools)
                for item in items:
                    name = item.name
                    if name in orphans:
                        item.is_orphan = True
                        item.install_reason = "orphan"
                    elif name in explicit:
                        item.is_orphan = False
                        item.install_reason = "explicit"
                    elif name in deps:
                        item.is_orphan = False
                        item.install_reason = "dependency"
                    else:
                        item.is_orphan = False
                        item.install_reason = "unknown"
                app.cache.save_installed(items)
                GLib.idle_add(
                    self._finish_load_installed,
                    items,
                    explicit,
                    deps,
                    orphans,
                    "",
                    show_progress,
                    busy_token,
                )
            except Exception as exc:
                GLib.idle_add(
                    self._finish_load_installed,
                    [],
                    set(),
                    set(),
                    set(),
                    str(exc),
                    show_progress,
                    busy_token,
                )

        threading.Thread(target=worker, daemon=True).start()

    def _apply_installed_data(self, items: list) -> None:
        self.app.all_installed = list(items)
        self.app.installed_loaded = True
        self.filter_installed()

    def _finish_load_installed(
        self,
        items: list,
        explicit: set,
        deps: set,
        orphans: set,
        error: str,
        show_progress: bool = False,
        busy_token: str = "",
    ) -> bool:
        app = self.app
        if busy_token:
            app.end_busy(busy_token)
        if error:
            if show_progress and app.view_mode == "installed":
                app.set_status(f"Installed packages scan failed: {error}")
            return False
        app.explicit_set = explicit
        app.deps_set = deps
        app.orphans_set = orphans
        app.all_installed = items
        app.installed_loaded = True
        app.update_badges()
        self.filter_installed()
        if app.view_mode == "orphans" and hasattr(app.views["orphans"], "refresh"):
            app.views["orphans"].refresh()
        return False


class _LineItem:
    """Lightweight package row used for checkupdates output."""

    def __init__(self, name: str, old: str, new: str) -> None:
        self.source = "pacman"
        self.manager = "pacman"
        self.name = name
        self.package_id = name
        self.version = new
        self.repo = ""
        self.installed = True
        self.origin = ""
        self.description = f"Installed: {old}    →    Available: {new}"
        self.install_reason = "installed"
        self.is_orphan = False

    def title(self) -> str:
        return self.name

    def info_command(self, tools, installed_view: bool) -> list[str] | None:
        pacman = getattr(tools, "pacman", None)
        return [pacman, "-Qi", self.name] if pacman else None


_UPDATE_RE = re.compile(r"^(\S+)\s+(\S+)\s+->\s+(\S+)")


class UpdatesView(BaseView):
    """Available updates plus the single-authentication update-all action."""

    def __init__(self, app) -> None:
        super().__init__(app, "updates")
        self.loaded = False
        self.checking = False
        self.refresh_pending = False
        self.busy_token = "updates-check"
        self.lines: list[str] = []

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Available package updates", xalign=0)
        title.add_css_class("section-label")
        title.set_hexpand(True)
        action_row.append(title)

        refresh = Gtk.Button()
        refresh.set_child(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        refresh.set_tooltip_text("Check again")
        refresh.connect("clicked", lambda *_: self.refresh())
        action_row.append(refresh)

        self.update_all_button = Gtk.Button(label="Update everything")
        self.update_all_button.add_css_class("suggested-action")
        self.update_all_button.connect(
            "clicked", lambda *_: self.app.confirm_update_all()
        )
        action_row.append(self.update_all_button)
        self.toolbar.append(action_row)
        self.set_placeholder(
            "Checking for updates",
            "Pacmangr checks available updates automatically.",
            "software-update-available-symbolic",
        )

    def focus(self) -> None:
        self.update_all_button.grab_focus()

    def refresh(self) -> None:
        if self.checking:
            self.refresh_pending = True
            return
        self.checking = True
        self.app.begin_busy(self.busy_token)
        self.app.set_status("Checking for updates…")

        def worker() -> None:
            try:
                lines = available_update_lines()
                GLib.idle_add(self.finish, lines, "")
            except Exception as exc:
                GLib.idle_add(self.finish, [], str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def finish(self, lines: list[str], error: str = "") -> bool:
        self.checking = False
        self.app.end_busy(self.busy_token)
        self.loaded = True
        if error:
            if self.app.view_mode == "updates":
                self.app.set_status(f"Update check failed: {error}")
                self.set_placeholder(
                    "Update check failed", error, "dialog-warning-symbolic"
                )
            self._start_pending_refresh()
            return False
        self.lines = list(lines)
        self.app.update_lines = lines
        self.app.update_badges()
        if self.app.view_mode == "updates":
            self.populate(lines)
        status = self.app.status_label.get_text() if self.app.status_label else ""
        if self.app.view_mode == "updates" or status == "Checking for updates…":
            self.app.set_status(
                f"{len(lines)} updates available."
                if lines
                else "All checked packages are up to date."
            )
        self._start_pending_refresh()
        return False

    def _start_pending_refresh(self) -> None:
        if self.refresh_pending:
            self.refresh_pending = False
            GLib.idle_add(self.refresh)

    def populate(self, lines: list[str]) -> None:
        items = []
        for line in lines:
            match = _UPDATE_RE.match(line)
            if match:
                items.append(_LineItem(match.group(1), match.group(2), match.group(3)))
            else:
                parts = line.split()
                name = parts[0] if parts else line
                items.append(_LineItem(name, "?", parts[2] if len(parts) > 2 else "?"))
        if self.app.view_mode == "updates":
            self.app.show_items(
                items,
                f"{len(items)} updates available" if items else "No updates available",
                auto_select=False,
            )


class GitHubRepoRow(Gtk.ListBoxRow):
    """Repository card with clone and browser actions."""

    def __init__(self, item, on_install, on_open) -> None:
        super().__init__()
        self.item = item
        self.add_css_class("package-row")
        self.add_css_class("github-row")

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("package-row-box")
        card.set_margin_top(2)
        card.set_margin_bottom(2)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        avatar = Gtk.Image.new_from_icon_name("avatar-default-symbolic")
        avatar.set_pixel_size(26)
        avatar.set_size_request(38, 38)
        avatar.set_valign(Gtk.Align.CENTER)
        avatar.add_css_class("package-icon")
        load_source_icon(avatar, item)
        top.append(avatar)
        name = Gtk.Label(
            label=getattr(item, "github_full_name", item.title()), xalign=0
        )
        name.set_hexpand(True)
        name.set_ellipsize(2)
        name.add_css_class("package-name")
        top.append(name)
        stars = Gtk.Label(label=f"★ {getattr(item, 'github_stars', 0):,}")
        stars.add_css_class("pill")
        stars.add_css_class("star-pill")
        top.append(stars)
        card.append(top)

        description = Gtk.Label(
            label=getattr(item, "github_description", "") or "No description provided.",
            xalign=0,
        )
        description.set_wrap(True)
        description.set_max_width_chars(90)
        description.add_css_class("muted")
        card.append(description)

        meta_parts = [
            f"{getattr(item, 'github_forks', 0):,} forks",
            getattr(item, "github_language", "") or "language unknown",
        ]
        license_name = getattr(item, "github_license", "")
        if license_name:
            meta_parts.append(f"license: {license_name}")
        meta = Gtk.Label(label="  ·  ".join(meta_parts), xalign=0)
        meta.add_css_class("repo-meta")
        card.append(meta)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        clone = Gtk.Button(
            label="Update checkout" if item.installed else "Clone / Install"
        )
        clone.add_css_class("flat" if item.installed else "suggested-action")
        clone.set_tooltip_text(
            "Fetch this repository into Pacmangr's managed Git directory"
        )
        clone.connect("clicked", lambda *_: on_install(item))
        open_button = Gtk.Button(label="Open")
        open_button.add_css_class("flat")
        open_button.add_css_class("link-button")
        open_button.set_tooltip_text("Open the repository in your browser")
        open_button.connect("clicked", lambda *_: on_open(item))
        actions.append(clone)
        actions.append(open_button)
        card.append(actions)

        self.set_child(card)


class GitHubView(BaseView):
    """Search GitHub repositories and clone them through the git source."""

    API_URL = "https://api.github.com/search/repositories"

    def __init__(self, app) -> None:
        super().__init__(app, "github")
        self.loaded = False
        self.query = ""
        self._result_cache: dict[str, tuple[float, list]] = {}

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.add_css_class("search-field")
        self.search_entry.set_placeholder_text(
            "Search repositories, or paste a GitHub / Git URL…"
        )
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("activate", self.on_search)
        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        search_row.add_css_class("search-control")
        search_row.append(self.search_entry)

        self.search_button = Gtk.Button.new_from_icon_name("system-search-symbolic")
        self.search_button.add_css_class("search-button")
        self.search_button.set_tooltip_text("Search GitHub")
        self.search_button.connect("clicked", self.on_search)
        search_row.append(self.search_button)

        self.open_button = Gtk.Button.new_from_icon_name("web-browser-symbolic")
        self.open_button.add_css_class("open-search-button")
        self.open_button.set_tooltip_text(
            "Open a pasted GitHub/Git URL in your browser"
        )
        self.open_button.connect("clicked", self.on_open_url)
        search_row.append(self.open_button)
        self.toolbar.append(search_row)

        hint = Gtk.Label(
            label="Public repositories · unauthenticated API · rate limits may apply",
            xalign=0,
        )
        hint.add_css_class("muted")
        hint.add_css_class("section-label")
        self.toolbar.append(hint)
        self.set_placeholder(
            "Find a repository",
            "Search public GitHub projects, or paste a Git URL to clone it.",
            "git-branch-symbolic",
        )

    def focus(self) -> None:
        self.search_entry.grab_focus()

    def refresh(self) -> None:
        if self.query:
            self._run_search(self.query)
        else:
            self.focus()

    def on_search(self, *_args) -> None:
        query = self.search_entry.get_text().strip()
        if not query:
            self.app.set_status("Type a repository name or paste a Git URL first.")
            self.focus()
            return
        self.query = query
        if self._add_direct_url(query):
            return
        self._run_search(query)

    @staticmethod
    def _git_url(query: str) -> str | None:
        if CORE.is_git_url(query):
            return query
        if re.fullmatch(r"[\w.-]+/[\w.-]+", query):
            return f"https://github.com/{query}"
        return None

    def _add_direct_url(self, query: str) -> bool:
        url = self._git_url(query)
        if not url:
            return False
        item = CORE.git_package(url)
        if item is None:
            self.app.set_status(f"Could not understand that Git URL: {query}")
            return True
        slug = github_repo_slug(url)
        if slug:
            item.github_full_name = slug
            item.github_html_url = f"https://github.com/{slug}"
            item.github_avatar_url = (
                f"https://github.com/{slug.split('/', 1)[0]}.png?size=96"
            )
            item.icon_url = item.github_avatar_url
            item.github_description = "README.md is available in the Details pane."
            item.github_default_branch = ""

            def resolve() -> None:
                branch = resolve_github_default_branch(slug)
                GLib.idle_add(self._apply_default_branch, item, branch)

            threading.Thread(target=resolve, daemon=True).start()
        self.app.request_id += 1
        self.search_button.set_sensitive(True)
        self.loaded = True
        self._show_items([item], f"Git repository: {item.name}")
        self.app.set_status(f"Ready to clone {item.origin}.")
        return True

    @staticmethod
    def _apply_default_branch(item, branch: str) -> bool:
        if branch:
            item.github_default_branch = branch
        return False

    def _show_items(self, items: list, heading: str) -> None:
        self.app.show_items(items, heading, row_factory=self._make_row)

    def _make_row(self, item) -> GitHubRepoRow:
        return GitHubRepoRow(item, self._install, self._open)

    def _install(self, item) -> None:
        self.app.current_item = item
        if self.app.details:
            self.app.details.show(item)
        self.app.confirm_action("install")

    def _open(self, item) -> None:
        url = getattr(item, "github_html_url", "") or item.origin
        self.app._launch_url(url)

    def on_open_url(self, *_args) -> None:
        query = self.search_entry.get_text().strip()
        if not query:
            self.app.set_status("Paste a GitHub or Git URL first.")
            return
        url = self._git_url(query) or query
        if url.startswith("git@"):
            match = re.match(r"git@[^:]+:(.+?)(?:\.git)?$", url)
            if match:
                url = f"https://github.com/{match.group(1)}"
        self.app._launch_url(url)

    def _run_search(self, query: str) -> None:
        app = self.app
        app.request_id += 1
        request_id = app.request_id
        app.begin_search_activity(request_id)
        cache_key = query.casefold()
        cached_entry = self._result_cache.get(cache_key)
        cached_items = []
        if cached_entry and time.monotonic() - cached_entry[0] < 300:
            cached_items = cached_entry[1]
            self.result_list.populate(
                cached_items,
                f"Results for “{query}” · cached",
                auto_select=False,
                row_factory=self._make_row,
            )
            app.set_status(
                f"Showing {len(cached_items)} cached repositories while refreshing GitHub…"
            )
        else:
            self.result_list.clear()
            self.result_list.heading.set_text("Searching GitHub…")
            if app.details:
                app.details.reset()
            app.set_status(f"Searching GitHub for {query!r}…")
        self.search_button.set_sensitive(False)

        def worker() -> None:
            try:
                params = urllib.parse.urlencode(
                    {"q": query, "sort": "stars", "per_page": 30}
                )
                request = urllib.request.Request(
                    f"{self.API_URL}?{params}",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "Pacmangr-GUI",
                    },
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                items = self._to_items(payload)
                GLib.idle_add(self.finish, request_id, query, items, "")
            except urllib.error.HTTPError as exc:
                GLib.idle_add(self.finish, request_id, query, [], self._http_error(exc))
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", exc)
                GLib.idle_add(
                    self.finish,
                    request_id,
                    query,
                    [],
                    f"Could not reach GitHub: {reason}",
                )
            except (ValueError, TypeError) as exc:
                GLib.idle_add(
                    self.finish,
                    request_id,
                    query,
                    [],
                    f"GitHub returned unreadable data: {exc}",
                )
            except Exception as exc:  # noqa: BLE001 - keep background failures graceful.
                GLib.idle_add(
                    self.finish, request_id, query, [], f"GitHub search failed: {exc}"
                )

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError) -> str:
        if exc.code in {403, 429}:
            reset = ""
            if exc.headers:
                reset_value = exc.headers.get("X-RateLimit-Reset")
                if reset_value:
                    reset = f" (resets at epoch {reset_value})"
            return f"GitHub API rate limit reached{reset}. Please try again later."
        if exc.code == 404:
            return "GitHub's search endpoint was not found."
        reason = getattr(exc, "reason", "unknown error")
        return f"GitHub API returned HTTP {exc.code}: {reason}"

    @staticmethod
    def _to_items(payload: dict) -> list:
        items = []
        for repo in payload.get("items", []) if isinstance(payload, dict) else []:
            if not isinstance(repo, dict):
                continue
            clone_url = repo.get("clone_url") or repo.get("html_url") or ""
            item = CORE.git_package(clone_url)
            if item is None:
                continue
            full_name = repo.get("full_name") or item.name
            stars = int(repo.get("stargazers_count") or 0)
            forks = int(repo.get("forks_count") or 0)
            language = repo.get("language") or ""
            license_info = repo.get("license") or {}
            license_name = (
                license_info.get("spdx_id") if isinstance(license_info, dict) else ""
            )
            html_url = repo.get("html_url") or clone_url
            description = repo.get("description") or "No description provided."

            item.name = full_name
            item.origin = html_url
            item.github_full_name = full_name
            item.github_description = description
            item.github_stars = stars
            item.github_forks = forks
            item.github_language = language
            item.github_license = license_name or ""
            item.github_html_url = html_url
            item.github_default_branch = repo.get("default_branch") or ""
            owner = repo.get("owner") or {}
            item.github_avatar_url = (
                owner.get("avatar_url", "") if isinstance(owner, dict) else ""
            )
            item.icon_url = item.github_avatar_url
            item.repo = f"★ {stars:,} · {forks:,} forks"
            extra = []
            if language:
                extra.append(language)
            if license_name and license_name != "NOASSERTION":
                extra.append(f"license: {license_name}")
            extra.append(
                "Clone uses Pacmangr's managed Git directory; build scripts are not run automatically."
            )
            item.description = f"{description}\n\n{' · '.join(extra)}"
            items.append(item)
        return items

    def finish(self, request_id: int, query: str, items: list, error: str) -> bool:
        app = self.app
        app.end_search_activity(request_id)
        if not error:
            self._result_cache[query.casefold()] = (time.monotonic(), list(items))
            if len(self._result_cache) > 24:
                oldest = min(
                    self._result_cache, key=lambda key: self._result_cache[key][0]
                )
                self._result_cache.pop(oldest, None)
        if request_id != app.request_id:
            return False
        self.search_button.set_sensitive(True)
        if app.view_mode != "github":
            return False
        self.loaded = True
        if error:
            cached_entry = self._result_cache.get(query.casefold())
            if cached_entry and time.monotonic() - cached_entry[0] < 300:
                cached_items = cached_entry[1]
                self.result_list.populate(
                    cached_items,
                    f"Results for “{query}” · cached",
                    auto_select=False,
                    row_factory=self._make_row,
                )
                app.set_status(
                    f"GitHub refresh failed; showing {len(cached_items)} cached repositories. {error}"
                )
                return False
            self._show_items([], "GitHub search unavailable")
            self.set_placeholder(
                "GitHub search unavailable", error, "dialog-warning-symbolic"
            )
            app.set_status(error)
            return False
        if not items:
            self._show_items([], f"No repositories for “{query}”")
            self.set_placeholder(
                "No repositories found",
                "Try a broader name, a topic, or paste a Git URL directly.",
                "git-branch-symbolic",
            )
            app.set_status(f"No GitHub repositories matched {query!r}.")
            return False
        self._show_items(items, f"{len(items)} repositories for “{query}”")
        app.set_status(f"Found {len(items)} GitHub repositories for {query!r}.")
        return False


class OrphansView(BaseView):
    """Unused packages with one-command cleanup."""

    def __init__(self, app) -> None:
        super().__init__(app, "orphans")
        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Unused dependency packages", xalign=0)
        title.add_css_class("section-label")
        title.set_hexpand(True)
        action_row.append(title)

        refresh = Gtk.Button()
        refresh.set_child(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        refresh.set_tooltip_text("Rescan installed packages")
        refresh.connect(
            "clicked", lambda *_: self.app.views["installed"].load_installed(force=True)
        )
        action_row.append(refresh)

        self.remove_selected = Gtk.Button(label="Remove selected")
        self.remove_selected.add_css_class("danger")
        self.remove_selected.connect("clicked", lambda *_: self._remove(False))
        action_row.append(self.remove_selected)

        self.remove_all = Gtk.Button(label="Remove all orphans")
        self.remove_all.add_css_class("danger")
        self.remove_all.connect("clicked", lambda *_: self._remove(True))
        action_row.append(self.remove_all)
        self.toolbar.append(action_row)
        self.set_placeholder(
            "No orphans detected",
            "Installed packages will be scanned automatically.",
            "edit-delete-symbolic",
        )

    def focus(self) -> None:
        self.remove_all.grab_focus()

    def refresh(self) -> None:
        app = self.app
        by_name = {item.name: item for item in app.all_installed}
        items = []
        for name in sorted(app.orphans_set):
            item = by_name.get(name)
            if item is None:
                item = CORE.PackageItem(
                    "pacman",
                    "pacman",
                    name,
                    name,
                    installed=True,
                    description="Unused package dependency",
                )
            item.is_orphan = True
            item.install_reason = "orphan"
            item.installed = True
            items.append(item)
        app.show_items(
            items, f"{len(items)} orphaned packages", remember=False, auto_select=False
        )
        if not items:
            self.set_placeholder(
                "No orphaned packages",
                "Your installed dependencies are all in use.",
                "edit-delete-symbolic",
            )
        app.set_status(f"{len(items)} orphaned packages detected.")

    def _remove(self, all_orphans: bool) -> None:
        names: list[str]
        if all_orphans:
            names = sorted(self.app.orphans_set)
        else:
            row = self.result_list.list_box.get_selected_row()
            names = [row.item.name] if row and getattr(row, "item", None) else []
        if not names:
            self.app.set_status("No orphan packages selected.")
            return
        command = orphan_remove_command(names, self.app.tools)
        self.app.confirm_clean_orphans(names, command=command)
