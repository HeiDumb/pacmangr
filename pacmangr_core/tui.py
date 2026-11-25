"""Curses terminal UI for pacmangr."""

from __future__ import annotations

import concurrent.futures
import curses
import json
import os
import pty
import queue
import shlex
import subprocess
import stat
import textwrap
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import constants
from .backends import (
    collect_installed_packages,
    find_appimages,
    search_appimage_catalog,
    git_package,
    is_git_url,
)
from .cache import PackageCache
from .commands import manager_spec_command, system_update_commands
from .models import DownloadJob, PackageItem, PackageVersion, Tools, package_key
from .parsers import (
    parse_apt_search,
    parse_arch_search,
    parse_flatpak_search,
    parse_manager_search,
    parse_snap_search,
)
from .utils import clip, human_size, pad, run_capture, strip_ansi
from .versions import format_versions, package_versions


class PkgUI:
    def __init__(self, stdscr: curses._CursesWindow, initial_query: str = "") -> None:
        self.stdscr = stdscr
        self.tools = Tools.detect()
        self.cache = PackageCache()
        self.initial_query = initial_query.strip()
        self.mode = "search"
        self.search_backend = "all"
        self.query = ""
        self.installed_filter = ""
        self.search_results: list[PackageItem] = []
        self.installed_items: list[PackageItem] = []
        self.marked: dict[tuple[str, str, str], PackageItem] = {}
        self.download_jobs: list[DownloadJob] = []
        self.next_download_id = 1
        self.download_thread_active = False
        self.version_rows: list[PackageVersion] = []
        self.version_target_key: tuple[str, str, str] | None = None
        self.version_pending_manager = ""
        self.version_pending_package = ""
        self.version_shelf_open = False
        self.version_focus = False
        self.version_cursor = 0
        self.version_scroll = 0
        self.installed_names: set[str] = set()
        self.installed_apt_names: set[str] = set()
        self.installed_flatpak_ids: set[str] = set()
        self.installed_snap_names: set[str] = set()
        self.installed_extra_names: dict[str, set[str]] = {}
        self.selected = 0
        self.scroll = 0
        self.log_lines: list[str] = []
        self.status = "Press / to search, i for installed packages."
        self.busy = False
        self.busy_label = ""
        self.spinner_index = 0
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.pending_search_query: str | None = None
        self.active_search_query = ""
        self.last_installed_load = 0.0
        self.running = True

    def setup(self) -> None:
        self.set_cursor(False)
        self.setup_colors()
        self.stdscr.keypad(True)
        self.stdscr.timeout(120)
        self.log(f"Detected tools: {self.tools.enabled_labels()}")
        self.cache.cleanup()
        self.load_cached_installed()
        if self.initial_query:
            self.start_search(self.initial_query)

    def set_cursor(self, visible: bool) -> None:
        try:
            curses.curs_set(1 if visible else 0)
        except curses.error:
            pass

    def setup_colors(self) -> None:
        try:
            curses.start_color()
            curses.use_default_colors()
        except curses.error:
            return

        pairs = None
        scheme_path = Path.home() / ".local/state/caelestia/scheme.json"
        try:
            colours = json.loads(scheme_path.read_text(encoding="utf-8")).get(
                "colours", {}
            )
            if not isinstance(colours, dict):
                colours = {}
        except (OSError, ValueError, TypeError):
            colours = {}

        if colours and curses.can_change_color() and curses.COLORS >= 16:
            roles = (
                (8, colours.get("primary") or colours.get("secondary"), "adc9ea"),
                (9, colours.get("onPrimary") or colours.get("background"), "26425e"),
                (10, colours.get("secondary") or colours.get("primary"), "e6bad7"),
                (11, colours.get("success") or colours.get("term2"), "b5ccba"),
                (12, colours.get("error") or colours.get("term1"), "fa746f"),
                (13, colours.get("tertiary") or colours.get("primaryFixed"), "c3c3eb"),
            )
            try:
                for colour_id, value, fallback in roles:
                    rgb = str(value or fallback).strip().lstrip("#")[:6]
                    red, green, blue = (
                        int(rgb[index : index + 2], 16) for index in (0, 2, 4)
                    )
                    curses.init_color(
                        colour_id,
                        round(red * 1000 / 255),
                        round(green * 1000 / 255),
                        round(blue * 1000 / 255),
                    )
                pairs = (
                    (1, 8, -1),
                    (2, 9, 8),
                    (3, 10, -1),
                    (4, 11, -1),
                    (5, 12, -1),
                    (6, 13, -1),
                )
            except (curses.error, ValueError):
                pairs = None

        if pairs is None:
            pairs = (
                (1, curses.COLOR_CYAN, -1),
                (2, curses.COLOR_BLACK, curses.COLOR_CYAN),
                (3, curses.COLOR_YELLOW, -1),
                (4, curses.COLOR_GREEN, -1),
                (5, curses.COLOR_RED, -1),
                (6, curses.COLOR_MAGENTA, -1),
            )
        for pair_id, foreground, background in pairs:
            try:
                curses.init_pair(pair_id, foreground, background)
            except curses.error:
                pass

    def log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        for line in str(message).splitlines() or [""]:
            self.log_lines.append(f"[{stamp}] {line}")
        self.log_lines = self.log_lines[-1000:]

    def load_cached_installed(self) -> None:
        cached = self.cache.load_installed()
        if not cached:
            return
        self.apply_installed_items(cached)
        self.status = f"Loaded {len(cached)} installed packages from local cache."
        self.log(self.status)

    def apply_installed_items(self, items: list[PackageItem]) -> None:
        self.installed_items = items
        self.installed_names = {
            item.package_id
            for item in self.installed_items
            if item.source in ("pacman", "aur/local")
        }
        self.installed_apt_names = {
            item.package_id for item in self.installed_items if item.source == "apt"
        }
        self.installed_flatpak_ids = {
            item.package_id for item in self.installed_items if item.source == "flatpak"
        }
        self.installed_snap_names = {
            item.package_id for item in self.installed_items if item.source == "snap"
        }
        self.installed_extra_names = {
            manager: {
                item.package_id
                for item in self.installed_items
                if item.source == manager
            }
            for manager in self.tools.extra_managers
        }
        self.refresh_marked_metadata(self.installed_items)

    def spawn_job(self, label: str, fn: Callable[[], object]) -> None:
        if self.busy:
            self.status = f"Still {self.busy_label}; wait for it to finish."
            return
        self.busy = True
        self.busy_label = label
        self.status = f"{label}..."

        def worker() -> None:
            try:
                result = fn()
                self.events.put(("done", (label, result, None)))
            except Exception as exc:  # noqa: BLE001 - surface unexpected tool failures in the log.
                self.events.put(("done", (label, None, exc)))

        threading.Thread(target=worker, daemon=True).start()

    def poll_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                return
            if event == "download_started":
                job = self.download_job(int(payload))
                if job:
                    job.status = "running"
                    job.started = time.time()
                    self.status = f"Downloading: {job.label}"
                continue
            if event == "download_line":
                job_id, line = payload  # type: ignore[misc]
                job = self.download_job(int(job_id))
                if job:
                    self.apply_download_line(job, str(line))
                continue
            if event == "download_done":
                job_id, code = payload  # type: ignore[misc]
                job = self.download_job(int(job_id))
                if job:
                    job.code = int(code)
                    job.status = "done" if job.code == 0 else "failed"
                    job.finished = time.time()
                    self.log(
                        f"Download job {job.status}: {job.label} exited {job.code}"
                    )
                continue
            if event == "download_queue_done":
                self.download_thread_active = False
                failures = sum(
                    1 for job in self.download_jobs if job.status == "failed"
                )
                self.status = f"Download queue finished. {failures} failed."
                self.refresh_installed(background=True)
                continue
            if event == "done":
                label, result, error = payload  # type: ignore[misc]
                self.busy = False
                self.busy_label = ""
                if error:
                    self.status = f"{label} failed: {error}"
                    self.log(self.status)
                else:
                    if label == "searching":
                        completed_query = self.active_search_query
                        if completed_query == self.query:
                            self.search_results = result  # type: ignore[assignment]
                            self.refresh_marked_metadata(self.search_results)
                            self.selected = 0
                            self.scroll = 0
                            self.status = (
                                f"Found {len(self.search_results)} packages "
                                f"for {completed_query!r}."
                            )
                            self.log(self.status)
                        else:
                            self.log(
                                f"Discarded stale results for {completed_query!r}; "
                                f"latest search is {self.query!r}."
                            )
                    elif label == "loading installed packages":
                        self.apply_installed_items(result)  # type: ignore[arg-type]
                        self.cache.save_installed(self.installed_items)
                        self.last_installed_load = time.time()
                        self.status = (
                            f"Loaded {len(self.installed_items)} installed packages."
                        )
                        self.log(self.status)
                    elif label.startswith("loading versions"):
                        versions = result if isinstance(result, list) else []
                        self.version_rows = versions  # type: ignore[assignment]
                        self.cache.save_versions(
                            self.version_pending_manager,
                            self.version_pending_package,
                            self.version_rows,
                        )
                        self.version_shelf_open = True
                        self.version_focus = True
                        self.version_cursor = 0
                        self.version_scroll = 0
                        self.status = f"Loaded {len(self.version_rows)} versions for {self.version_pending_package}."
                        self.log(
                            format_versions(
                                self.version_pending_package, self.version_rows
                            )
                        )
                    elif label.startswith("loading info"):
                        self.mode = "log"
                        self.selected = len(self.log_lines) - 1
                        self.scroll = 0
                        self.status = "Info loaded in log view."
                    else:
                        self.status = f"{label} finished."

                pending_search = self.pending_search_query
                if pending_search:
                    self.pending_search_query = None
                    if not (
                        error is None
                        and label == "searching"
                        and pending_search == self.active_search_query
                    ):
                        self.start_search(pending_search)

    def search(self) -> None:
        query = self.prompt("Search packages")
        if not query:
            self.status = "Search cancelled."
            return
        self.start_search(query)

    def start_search(self, query: str) -> None:
        self.query = query
        self.mode = "search"
        self.selected = 0
        self.scroll = 0
        cached = self.cache.load_search(query, self.enabled_search_managers("all"))
        if cached:
            self.search_results = self.rank_results(self.dedupe_items(cached), query)[
                : constants.MAX_RESULTS
            ]
            self.refresh_marked_metadata(self.search_results)
            self.status = (
                f"Loaded {len(self.search_results)} cached results; refreshing live."
            )
            self.log(self.status)
        else:
            self.search_results = []

        if self.busy:
            self.pending_search_query = query
            self.status = f"Queued search for {query!r}; finishing {self.busy_label}."
            self.log(self.status)
            return

        self.active_search_query = query

        def job() -> list[PackageItem]:
            return self.search_packages(query, "all")

        self.spawn_job("searching", job)

    def enabled_search_managers(self, backend: str) -> set[str]:
        managers: set[str] = set()
        if backend in ("all", "pacman") and self.tools.pacman:
            managers.add("pacman")
        if backend in ("all", "yay") and self.tools.yay:
            managers.add("yay")
        if backend in ("all", "paru") and self.tools.paru:
            managers.add("paru")
        if backend in ("all", "flatpak") and self.tools.flatpak:
            managers.add("flatpak")
        if backend in ("all", "apt") and self.tools.apt_cache:
            managers.add("apt")
        if backend in ("all", "snap") and self.tools.snap:
            managers.add("snap")
        if backend in ("all", "git") and self.tools.git:
            managers.add("git")
        if backend in ("all", "appimage"):
            managers.add("appimage")
        if backend == "all" or backend in self.tools.extra_managers:
            for manager in self.tools.extra_managers:
                if backend != "all" and manager != backend:
                    continue
                if "search" in constants.MANAGER_SPECS.get(manager, {}):
                    managers.add(manager)
        return managers

    def dedupe_items(self, items: list[PackageItem]) -> list[PackageItem]:
        deduped: list[PackageItem] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = (item.source, item.package_id)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def result_score(self, item: PackageItem, query: str) -> int:
        q = query.lower().strip()
        name = item.name.lower()
        description = item.description.lower()
        score = 0
        if q and name == q:
            score += 1000
        elif q and name.startswith(q):
            score += 700
        elif q and q in name:
            score += 500
        elif q and q in description:
            score += 250
        if item.installed:
            score += 300
        if item.manager in {"pacman", "apt", "dnf", "zypper", "apk", "xbps"}:
            score += 200
        elif item.manager == "flatpak":
            score += 150
        elif item.manager in {"yay", "paru"}:
            score += 120
        elif item.manager in {"npm", "pip", "cargo", "gem", "luarocks"}:
            score -= 150
        score -= min(len(item.name), 80) // 8
        return score

    def rank_results(self, items: list[PackageItem], query: str) -> list[PackageItem]:
        return sorted(
            items,
            key=lambda item: (
                -self.result_score(item, query),
                item.name.lower(),
                item.source,
            ),
        )

    def search_packages(
        self,
        query: str,
        backend: str,
        on_results: Callable[[list[PackageItem]], None] | None = None,
    ) -> list[PackageItem]:
        results: list[PackageItem] = []
        seen: set[tuple[str, str]] = set()
        per_manager_limit = 80 if backend == "all" else constants.MAX_RESULTS
        jobs: list[
            tuple[str, Callable[[], tuple[str, list[PackageItem], bool, str]]]
        ] = []

        def add_many(items: list[PackageItem], limit: int = per_manager_limit) -> None:
            added = 0
            for item in items:
                if added >= limit:
                    break
                key = (item.source, item.package_id)
                if key in seen:
                    continue
                seen.add(key)
                results.append(item)
                added += 1

        def timeout_for(manager: str) -> int:
            return constants.SEARCH_TIMEOUT_SECONDS.get(
                manager, 10 if backend == "all" else 20
            )

        def command_job(
            manager: str,
            label: str,
            cmd: list[str],
            parser: Callable[[str], list[PackageItem]],
        ) -> Callable[[], tuple[str, list[PackageItem], bool, str]]:
            def run() -> tuple[str, list[PackageItem], bool, str]:
                code, output = run_capture(cmd, timeout=timeout_for(manager))
                if code not in (0, 1):
                    return (
                        manager,
                        [],
                        False,
                        f"{label} exited {code}:\n{output.strip()}",
                    )
                return manager, parser(output), True, ""

            return run

        def appimage_job() -> tuple[str, list[PackageItem], bool, str]:
            local = find_appimages(query)
            try:
                catalog = search_appimage_catalog(query)
            except Exception as exc:  # Keep local AppImages searchable offline.
                return "appimage", local, True, f"AppImage catalog unavailable: {exc}"
            return "appimage", local + catalog, True, ""

        if backend in ("all", "pacman") and self.tools.pacman:
            jobs.append(
                (
                    "pacman",
                    command_job(
                        "pacman",
                        "pacman search",
                        [self.tools.pacman, "-Ss", query],
                        lambda output: parse_arch_search(
                            output, "pacman", self.installed_names
                        ),
                    ),
                )
            )

        if backend in ("all", "git") and self.tools.git and is_git_url(query):
            item = git_package(query)
            if item:
                jobs.append(("git", lambda package=item: ("git", [package], True, "")))

        if backend in ("all", "yay") and self.tools.yay:
            jobs.append(
                (
                    "yay",
                    command_job(
                        "yay",
                        "yay AUR search",
                        [self.tools.yay, "-Ssa", query],
                        lambda output: parse_arch_search(
                            output, "yay", self.installed_names, "aur"
                        ),
                    ),
                )
            )

        if backend in ("all", "paru") and self.tools.paru:
            jobs.append(
                (
                    "paru",
                    command_job(
                        "paru",
                        "paru AUR search",
                        [self.tools.paru, "-Ssa", query],
                        lambda output: parse_arch_search(
                            output, "paru", self.installed_names, "aur"
                        ),
                    ),
                )
            )

        if backend in ("all", "flatpak") and self.tools.flatpak:
            jobs.append(
                (
                    "flatpak",
                    command_job(
                        "flatpak",
                        "flatpak search",
                        [self.tools.flatpak, "search", "--json", query],
                        lambda output: parse_flatpak_search(
                            output, self.installed_flatpak_ids
                        ),
                    ),
                )
            )

        if backend in ("all", "apt") and self.tools.apt_cache:
            jobs.append(
                (
                    "apt",
                    command_job(
                        "apt",
                        "apt-cache search",
                        [self.tools.apt_cache, "search", query],
                        lambda output: parse_apt_search(
                            output, self.installed_apt_names
                        ),
                    ),
                )
            )

        if backend in ("all", "snap") and self.tools.snap:
            jobs.append(
                (
                    "snap",
                    command_job(
                        "snap",
                        "snap find",
                        [self.tools.snap, "find", query],
                        lambda output: parse_snap_search(
                            output, self.installed_snap_names
                        ),
                    ),
                )
            )

        if backend in ("all", "appimage"):
            jobs.append(("appimage", appimage_job))

        if backend == "all" or backend in self.tools.extra_managers:
            for manager in self.tools.extra_managers:
                if backend != "all" and manager != backend:
                    continue
                spec = constants.MANAGER_SPECS.get(manager, {})
                if "search" not in spec:
                    continue
                cmd = manager_spec_command(manager, "search", self.tools, query=query)
                if not cmd:
                    continue
                jobs.append(
                    (
                        manager,
                        command_job(
                            manager,
                            f"{manager} search",
                            cmd,
                            lambda output, name=manager: parse_manager_search(
                                name,
                                output,
                                self.installed_extra_names.get(name, set()),
                            ),
                        ),
                    )
                )

        if jobs:
            workers = max(1, min(constants.SEARCH_WORKERS, len(jobs)))
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_manager = {
                    executor.submit(job): manager for manager, job in jobs
                }
                for future in concurrent.futures.as_completed(future_to_manager):
                    manager = future_to_manager[future]
                    try:
                        cache_manager, parsed, cacheable, log_message = future.result()
                    except Exception as exc:  # noqa: BLE001 - keep one bad backend from killing search.
                        self.log(f"{manager} search failed: {exc}")
                        continue
                    if log_message:
                        self.log(log_message)
                    if cacheable:
                        self.cache.save_search(cache_manager, query, parsed)
                    add_many(parsed)
                    if on_results is not None:
                        try:
                            on_results(
                                self.rank_results(list(results), query)[
                                    : constants.MAX_RESULTS
                                ]
                            )
                        except Exception as exc:  # Keep optional UI updates from interrupting backend searches.
                            self.log(f"Search result update failed: {exc}")

        return self.rank_results(results, query)[: constants.MAX_RESULTS]

    def refresh_installed(self, background: bool = False) -> None:
        def job() -> list[PackageItem]:
            return collect_installed_packages(self.tools, self.log)

        if background:
            self.spawn_job("loading installed packages", job)
        else:
            self.mode = "installed"
            self.selected = 0
            self.scroll = 0
            self.spawn_job("loading installed packages", job)

    def current_items(self) -> list[PackageItem]:
        if self.mode == "search":
            selected_items = self.marked_items()
            selected_keys = {package_key(item) for item in selected_items}
            return selected_items + [
                item
                for item in self.search_results
                if package_key(item) not in selected_keys
            ]
        if self.mode == "installed":
            if not self.installed_filter:
                return self.installed_items
            needle = self.installed_filter.lower()
            return [
                item
                for item in self.installed_items
                if needle in item.name.lower()
                or needle in item.package_id.lower()
                or needle in item.source.lower()
                or needle in item.repo.lower()
                or needle in item.description.lower()
            ]
        return []

    def selected_item(self) -> PackageItem | None:
        items = self.current_items()
        if not items:
            return None
        self.selected = max(0, min(self.selected, len(items) - 1))
        return items[self.selected]

    def refresh_marked_metadata(self, items: list[PackageItem]) -> None:
        for item in items:
            key = package_key(item)
            if key in self.marked:
                self.marked[key] = item

    def marked_items(self) -> list[PackageItem]:
        return list(self.marked.values())

    def is_marked(self, item: PackageItem) -> bool:
        return package_key(item) in self.marked

    def operation_targets(self) -> list[PackageItem]:
        marked = self.marked_items()
        if marked:
            return marked
        item = self.selected_item()
        return [item] if item else []

    def toggle_mark_selected(self) -> None:
        item = self.selected_item()
        if not item:
            self.status = "No package selected."
            return
        key = package_key(item)
        if key in self.marked:
            del self.marked[key]
            self.status = f"Unselected {item.title()}."
        else:
            self.marked[key] = item
            self.status = f"Selected {item.title()}. {len(self.marked)} total."

    def mark_current_items(self) -> None:
        items = self.current_items()
        if not items:
            self.status = "No packages shown to select."
            return
        added = 0
        for item in items:
            key = package_key(item)
            if key not in self.marked:
                self.marked[key] = item
                added += 1
        self.status = f"Selected {added} shown packages. {len(self.marked)} total."

    def clear_marked(self) -> None:
        count = len(self.marked)
        self.marked.clear()
        self.status = f"Cleared {count} selected packages."

    def download_job(self, job_id: int) -> DownloadJob | None:
        for job in self.download_jobs:
            if job.id == job_id:
                return job
        return None

    def active_download_jobs(self) -> list[DownloadJob]:
        return [
            job for job in self.download_jobs if job.status in {"queued", "running"}
        ]

    def apply_download_line(self, job: DownloadJob, raw_line: str) -> None:
        line = strip_ansi(raw_line).strip()
        if not line:
            return
        job.last_line = line
        job.lines.append(line)
        job.lines = job.lines[-80:]
        percent = constants.PERCENT_RE.findall(line)
        if percent:
            job.progress = percent[-1] + "%"
        speed = constants.SPEED_RE.findall(line)
        if speed:
            job.speed = speed[-1]
        eta = constants.ETA_RE.findall(line)
        if eta and ("eta" in line.lower() or job.speed):
            job.eta = eta[-1]
        self.log(f"[download:{job.id}] {line}")

    def command_uses_sudo(self, cmd: list[str]) -> bool:
        return bool(cmd and Path(cmd[0]).name == "sudo")

    def command_uses_doas(self, cmd: list[str]) -> bool:
        return bool(cmd and Path(cmd[0]).name == "doas")

    def command_tool_name(self, cmd: list[str]) -> str:
        if not cmd:
            return ""
        index = 1 if self.command_uses_sudo(cmd) or self.command_uses_doas(cmd) else 0
        if index >= len(cmd):
            return ""
        return Path(cmd[index]).name

    def command_uses_helper_sudo(self, cmd: list[str]) -> bool:
        return self.command_tool_name(cmd) in {"yay", "paru"}

    def command_needs_sudo_password(self, cmd: list[str]) -> bool:
        return self.command_uses_sudo(cmd) or self.command_uses_helper_sudo(cmd)

    def package_summary(self, items: list[PackageItem]) -> str:
        if not items:
            return "no packages"
        if len(items) == 1:
            return items[0].title()
        names = ", ".join(item.title() for item in items[:4])
        if len(items) > 4:
            names += f", +{len(items) - 4} more"
        return f"{len(items)} packages: {names}"

    def package_command_pairs(
        self,
        items: list[PackageItem],
        action: str,
    ) -> tuple[list[tuple[PackageItem, list[str]]], list[PackageItem]]:
        pairs: list[tuple[PackageItem, list[str]]] = []
        skipped: list[PackageItem] = []
        for item in items:
            if action == "install":
                cmd = item.install_command(self.tools)
            else:
                if not item.installed and item.source != "appimage":
                    skipped.append(item)
                    continue
                cmd = item.remove_command(self.tools)
            if cmd:
                pairs.append((item, cmd))
            else:
                skipped.append(item)
        return pairs, skipped

    def can_batch_package_command(self, item: PackageItem) -> bool:
        return item.source in {
            "pacman",
            "aur",
            "aur/local",
            "flatpak",
            "apt",
            "dnf",
            "zypper",
            "apk",
            "xbps",
            "eopkg",
            "brew",
            "nix",
            "npm",
            "pip",
            "opkg",
            "pkg",
            "guix",
        }

    def collapse_package_commands(
        self,
        pairs: list[tuple[PackageItem, list[str]]],
    ) -> list[tuple[list[PackageItem], list[str]]]:
        grouped: dict[tuple[str, ...], tuple[list[PackageItem], list[str]]] = {}
        for item, cmd in pairs:
            if not cmd:
                continue
            if not self.can_batch_package_command(item):
                grouped[("__single__", *cmd, *package_key(item))] = ([item], list(cmd))
                continue
            prefix = tuple(cmd[:-1])
            package_arg = cmd[-1]
            if prefix not in grouped:
                grouped[prefix] = ([], list(prefix))
            grouped[prefix][0].append(item)
            grouped[prefix][1].append(package_arg)
        return list(grouped.values())

    def prompt(self, label: str, secret: bool = False) -> str:
        h, w = self.stdscr.getmaxyx()
        prompt_text = f"{label}: "
        self.clear_line(h - 1)
        self.safe_addstr(h - 1, 0, prompt_text[: max(0, w - 1)], curses.color_pair(3))
        self.set_cursor(True)
        if secret:
            curses.noecho()
        else:
            curses.echo()
        self.stdscr.timeout(-1)
        try:
            raw = self.stdscr.getstr(
                h - 1,
                min(len(prompt_text), max(0, w - 1)),
                max(1, w - len(prompt_text) - 1),
            )
        except curses.error:
            raw = b""
        finally:
            curses.noecho()
            self.set_cursor(False)
            self.stdscr.timeout(120)
        value = raw.decode(errors="replace")
        return value if secret else value.strip()

    def prompt_secret(self, label: str) -> str:
        return self.prompt(label, secret=True)

    def confirm(self, question: str) -> bool:
        self.status = f"{question} [Y/n]"
        self.draw()
        self.stdscr.timeout(-1)
        try:
            ch = self.stdscr.getch()
        finally:
            self.stdscr.timeout(120)
        if ch in (ord("n"), ord("N"), ord("q"), ord("Q"), 27):
            return False
        return ch in (ord("y"), ord("Y"), ord("\n"), curses.KEY_ENTER, 10, 13)

    def terminal_confirm(self, question: str) -> bool:
        try:
            answer = input(f"{question} [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return True
        return answer not in {"n", "no", "q", "quit"}

    def wait_for_return(self) -> None:
        try:
            input(f"Press Enter to return to {constants.APP_NAME}...")
        except (EOFError, KeyboardInterrupt):
            print()

    def run_interactive(self, title: str, cmd: list[str]) -> int:
        codes = self.run_interactive_commands(title, [(title, cmd)])
        return codes[-1] if codes else 1

    def run_interactive_commands(
        self, title: str, commands: list[tuple[str, list[str]]]
    ) -> list[int]:
        if not commands:
            return []
        command_count = len(commands)
        self.log(f"Running {command_count} command(s): {title}")
        self.status = f"Running {command_count} command(s); password prompts and downloads are below."
        self.draw()
        curses.def_prog_mode()
        curses.endwin()
        codes: list[int] = []
        try:
            print()
            print(f"{constants.APP_NAME}: {title}")
            print(
                f"{command_count} command(s) queued. Password prompts and download progress stay native."
            )
            print()
            for index, (label, cmd) in enumerate(commands, start=1):
                command_text = shlex.join(cmd)
                print(f"[{index}/{command_count}] {label}")
                print(f"$ {command_text}")
                print()
                try:
                    code = subprocess.call(cmd)
                except FileNotFoundError as exc:
                    print(f"{constants.APP_NAME}: command not found: {exc}")
                    code = 127
                except KeyboardInterrupt:
                    print()
                    print(f"{constants.APP_NAME}: interrupted")
                    code = 130
                codes.append(code)
                self.log(f"Command exited {code}: {command_text}")
                print()
                print(f"{constants.APP_NAME}: command exited with status {code}")
                print()
                if code != 0 and index < command_count:
                    if not self.terminal_confirm("Continue with remaining commands?"):
                        break
            failures = sum(1 for code in codes if code != 0)
            print(
                f"{constants.APP_NAME}: finished {len(codes)}/{command_count} command(s), {failures} failed."
            )
            self.wait_for_return()
        finally:
            curses.reset_prog_mode()
            self.stdscr.keypad(True)
            self.stdscr.timeout(120)
            self.set_cursor(False)
        failures = sum(1 for code in codes if code != 0)
        self.status = (
            f"Finished {len(codes)}/{command_count} command(s), {failures} failed."
        )
        self.refresh_installed(background=True)
        return codes

    def prepare_background_command(self, cmd: list[str], action: str) -> list[str]:
        prepared = list(cmd)
        real_index = (
            1
            if self.command_uses_sudo(prepared) or self.command_uses_doas(prepared)
            else 0
        )
        if real_index >= len(prepared):
            return prepared
        tool = Path(prepared[real_index]).name

        def insert_after_tool(option: str) -> None:
            if option not in prepared[real_index + 1 :]:
                prepared.insert(real_index + 1, option)

        def insert_pair_after_tool(option: str, value: str) -> None:
            if option not in prepared[real_index + 1 :]:
                prepared[real_index + 1 : real_index + 1] = [option, value]

        def insert_after_subcommand(option: str) -> None:
            if option not in prepared[real_index + 1 :]:
                prepared.insert(min(real_index + 2, len(prepared)), option)

        if tool in {"pacman", "yay", "paru"} and "--noconfirm" not in prepared:
            if any(
                arg.startswith("-S") or arg.startswith("-R")
                for arg in prepared[real_index + 1 :]
            ):
                insert_after_tool("--noconfirm")
        if tool in {"yay", "paru"}:
            insert_pair_after_tool("--sudoflags", f"-S -p {constants.SUDO_PROMPT}")
            if tool == "yay":
                for option, value in (
                    ("--answerclean", "none"),
                    ("--answerdiff", "none"),
                    ("--answeredit", "none"),
                    ("--answerupgrade", "none"),
                ):
                    insert_pair_after_tool(option, value)
                insert_after_tool("--noremovemake")
            else:
                insert_after_tool("--skipreview")
                insert_after_tool("--noremovemake")
        elif tool == "flatpak" and action in {"install", "remove", "update"}:
            insert_after_subcommand("-y")
        elif tool in {"apt", "apt-get"}:
            if any(
                arg in {"install", "remove", "upgrade", "full-upgrade"}
                for arg in prepared
            ):
                insert_after_subcommand("-y")
        elif tool == "pip" and "uninstall" in prepared:
            insert_after_subcommand("-y")
        elif tool == "dnf":
            insert_after_tool("-y")
        elif tool == "zypper":
            insert_after_tool("--non-interactive")
        elif tool in {"xbps-install", "xbps-remove", "pkg"}:
            insert_after_tool("-y")
        return prepared

    def command_with_sudo_stdin(self, cmd: list[str]) -> list[str]:
        if not self.command_uses_sudo(cmd):
            return cmd
        if len(cmd) > 1 and cmd[1] == "-S":
            return cmd
        return [cmd[0], "-S", "-p", "", *cmd[1:]]

    def ensure_sudo_password(self, commands: list[tuple[str, list[str]]]) -> str | None:
        sudo_commands = [
            cmd for _, cmd in commands if self.command_needs_sudo_password(cmd)
        ]
        doas_commands = [cmd for _, cmd in commands if self.command_uses_doas(cmd)]
        if doas_commands:
            self.status = "Background password entry currently supports sudo, not doas."
            return None
        if not sudo_commands:
            return ""
        sudo = self.tools.sudo
        if not sudo:
            self.status = "sudo is required for background helper password entry."
            return None
        try:
            cached = subprocess.run(
                [sudo, "-n", "true"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            cached = subprocess.CompletedProcess([sudo, "-n", "true"], 1)
        if cached.returncode == 0:
            return ""
        for _ in range(3):
            password = self.prompt_secret("sudo password")
            if not password:
                self.status = "Password entry cancelled."
                return None
            try:
                check = subprocess.run(
                    [sudo, "-S", "-p", "", "-v"],
                    input=password + "\n",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=20,
                )
            except subprocess.TimeoutExpired:
                self.status = "sudo password check timed out."
                return None
            if check.returncode == 0:
                return password
            self.status = "sudo rejected that password."
            self.draw()
        self.status = "sudo password failed."
        return None

    def start_background_commands(
        self,
        title: str,
        commands: list[tuple[str, list[str]]],
        action: str,
    ) -> None:
        if not commands:
            return
        if self.download_thread_active:
            self.status = "Download queue is already running."
            return
        prepared = [
            (label, self.prepare_background_command(cmd, action))
            for label, cmd in commands
        ]
        password = self.ensure_sudo_password(prepared)
        if password is None:
            return
        jobs: list[DownloadJob] = []
        for label, cmd in prepared:
            job = DownloadJob(self.next_download_id, label, cmd)
            self.next_download_id += 1
            self.download_jobs.append(job)
            jobs.append(job)
        self.download_jobs = self.download_jobs[-80:]
        self.download_thread_active = True
        self.status = f"Queued {len(jobs)} background command(s): {title}"
        self.log(self.status)

        thread_jobs = [(job.id, job.cmd) for job in jobs]
        threading.Thread(
            target=self.run_download_queue,
            args=(thread_jobs, password),
            daemon=True,
        ).start()

    def run_download_queue(
        self, jobs: list[tuple[int, list[str]]], password: str
    ) -> None:
        try:
            for job_id, cmd in jobs:
                self.events.put(("download_started", job_id))
                try:
                    code = self.run_download_process(job_id, cmd, password)
                except Exception as exc:  # noqa: BLE001 - keep the TUI alive and surface the failure.
                    self.events.put(
                        ("download_line", (job_id, f"runner failed: {exc}"))
                    )
                    code = 1
                self.events.put(("download_done", (job_id, code)))
        finally:
            self.events.put(("download_queue_done", None))

    def run_download_process(self, job_id: int, cmd: list[str], password: str) -> int:
        run_cmd = self.command_with_sudo_stdin(cmd)
        use_password_stdin = self.command_needs_sudo_password(cmd)
        master_fd = -1
        slave_fd = -1
        try:
            master_fd, slave_fd = pty.openpty()
            proc = subprocess.Popen(
                run_cmd,
                stdin=subprocess.PIPE if use_password_stdin else subprocess.DEVNULL,
                stdout=slave_fd,
                stderr=slave_fd,
                text=False,
                bufsize=0,
                env={**os.environ, "LC_ALL": "C"},
            )
        except FileNotFoundError as exc:
            if master_fd >= 0:
                os.close(master_fd)
            self.events.put(("download_line", (job_id, str(exc))))
            return 127
        finally:
            if slave_fd >= 0:
                os.close(slave_fd)

        if proc.stdin:
            try:
                if use_password_stdin and password:
                    proc.stdin.write((password + "\n").encode())
                    proc.stdin.flush()
            except BrokenPipeError:
                pass
            finally:
                proc.stdin.close()

        buffer = ""
        try:
            while True:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                for char in chunk.decode(errors="replace"):
                    buffer += char
                    if char in "\r\n":
                        line = buffer.strip("\r\n")
                        if line:
                            self.events.put(("download_line", (job_id, line)))
                        buffer = ""
        finally:
            if master_fd >= 0:
                os.close(master_fd)
        if buffer.strip():
            self.events.put(("download_line", (job_id, buffer.strip())))
        return proc.wait()

    def install_selected(self) -> None:
        targets = self.operation_targets()
        if not targets:
            self.status = "No package selected."
            return
        if len(targets) == 1 and targets[0].source == "appimage" and targets[0].installed:
            self.run_appimage(targets[0])
            return

        already_installed = [
            item for item in targets if item.installed and item.source != "appimage"
        ]
        if already_installed and not self.confirm(
            f"{self.package_summary(already_installed)} already installed. Reinstall anyway?"
        ):
            self.status = "Install cancelled."
            return
        pairs, skipped = self.package_command_pairs(targets, "install")
        if skipped:
            self.log("Skipped install targets: " + self.package_summary(skipped))
        if not pairs:
            self.status = "No usable install command for this package."
            return
        items = [item for item, _ in pairs]
        if not self.confirm(f"Install {self.package_summary(items)}?"):
            self.status = "Install cancelled."
            return
        grouped = self.collapse_package_commands(pairs)
        commands = [
            (self.package_summary(group_items), cmd) for group_items, cmd in grouped
        ]
        self.start_background_commands(
            "installing selected packages", commands, "install"
        )

    def remove_selected(self) -> None:
        targets = self.operation_targets()
        if not targets:
            self.status = "No installed package selected."
            return

        pairs, skipped = self.package_command_pairs(targets, "remove")
        if skipped:
            self.log("Skipped remove targets: " + self.package_summary(skipped))
        if not pairs:
            self.status = "No usable remove command for this package."
            return
        items = [item for item, _ in pairs]
        if not self.confirm(f"Remove {self.package_summary(items)}?"):
            self.status = "Remove cancelled."
            return
        grouped = self.collapse_package_commands(pairs)
        commands = [
            (self.package_summary(group_items), cmd) for group_items, cmd in grouped
        ]
        self.start_background_commands("removing selected packages", commands, "remove")

    def update_system(self) -> None:
        commands = system_update_commands(self.tools)
        if not commands:
            self.status = "No update-capable package tool found."
            return
        if not self.confirm("Run full package update?"):
            self.status = "Update cancelled."
            return
        self.start_background_commands("updating packages", commands, "update")

    def version_cache_manager(self, item: PackageItem) -> str:
        if item.source in {"pacman", "aur", "aur/local"} or item.manager in {
            "pacman",
            "yay",
            "paru",
        }:
            return "downgrade"
        return item.manager or item.source

    def show_versions(self) -> None:
        item = self.selected_item()
        if not item:
            self.status = "No package selected."
            return
        manager = self.version_cache_manager(item)
        self.version_pending_manager = manager
        self.version_pending_package = item.package_id
        self.version_target_key = package_key(item)
        self.version_shelf_open = True
        self.version_focus = True
        self.version_cursor = 0
        self.version_scroll = 0
        self.scroll = max(0, self.selected - 2)
        cached = self.cache.load_versions(manager, item.package_id)
        if cached:
            self.version_rows = cached
            self.status = f"Loaded {len(cached)} cached versions; refreshing."
            self.log(format_versions(item.package_id, cached))
        else:
            self.version_rows = []
            self.status = f"Loading versions for {item.package_id}."

        def job() -> list[PackageVersion]:
            return package_versions(self.tools, item)

        self.spawn_job(f"loading versions for {item.package_id}", job)

    def show_info(self) -> None:
        item = self.selected_item()
        if not item:
            self.status = "No package selected."
            return
        if item.source == "appimage":
            self.log_appimage_info(item)
            return
        cmd = item.info_command(self.tools, self.mode == "installed")
        if not cmd:
            self.status = "No info command for this package."
            return

        def job() -> list[PackageItem]:
            code, output = run_capture(cmd, timeout=60)
            self.log("$ " + shlex.join(cmd))
            if output.strip():
                self.log(output.rstrip())
            self.log(f"info command exited {code}")
            return []

        self.spawn_job(f"loading info for {item.package_id}", job)

    def run_appimage(self, item: PackageItem | None = None) -> None:
        item = item or self.selected_item()
        if not item or item.source != "appimage" or not item.installed:
            self.status = "Select an installed AppImage to run."
            return
        value = getattr(item, "local_path", "")
        if not value and item.package_id.startswith("/"):
            value = item.package_id
        path = Path(value).expanduser() if value else None
        if path is None or not path.is_file():
            self.status = f"AppImage file not found for {item.title()}."
            return
        try:
            mode = path.stat().st_mode
            if not mode & 0o111:
                path.chmod(stat.S_IMODE(mode) | 0o111)
            subprocess.Popen(
                [str(path)],
                cwd=str(path.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self.status = f"Could not run {item.title()}: {exc}"
            return
        self.status = f"Launched {item.title()}."

    def log_appimage_info(self, item: PackageItem) -> None:
        self.log(f"AppImage: {item.name}")
        path_value = item.local_path or (
            item.package_id if item.package_id.startswith("/") else ""
        )
        if path_value:
            path = Path(path_value).expanduser()
            self.log(f"path: {path}")
            try:
                file_stat = path.stat()
                self.log(f"size: {human_size(file_stat.st_size)}")
                self.log(f"mode: {oct(file_stat.st_mode & 0o777)}")
                self.log(
                    "modified: "
                    + time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(file_stat.st_mtime)
                    )
                )
                self.log(f"executable: {'yes' if os.access(path, os.X_OK) else 'no'}")
            except OSError as exc:
                self.log(f"stat failed: {exc}")
        else:
            self.log(f"download: {item.origin or 'not available'}")
            if item.description:
                self.log(item.description)
        self.mode = "log"
        self.selected = len(self.log_lines) - 1
        self.scroll = 0
        self.status = "AppImage info loaded in log view."

    def launch_pacseek_search(self, query: str = "") -> None:
        if not self.tools.pacseek:
            self.status = "pacseek is not installed."
            return
        cmd = [self.tools.pacseek]
        if query:
            cmd.append(query)
        self.run_interactive("launching pacseek", cmd)

    def filter_installed(self) -> None:
        value = self.prompt("Filter installed packages")
        self.installed_filter = value
        self.mode = "installed"
        self.selected = 0
        self.scroll = 0
        if value:
            self.status = f"Installed filter: {value}"
        else:
            self.status = "Installed filter cleared."

    def handle_key(self, ch: int) -> None:
        if ch == -1:
            return

        if self.version_shelf_open:
            if ch == ord("q"):
                self.version_shelf_open = False
                self.version_focus = False
                self.status = "Closed version shelf."
                return
            if ch in (ord("j"), curses.KEY_DOWN):
                self.move_version_selection(1)
                return
            if ch in (ord("k"), curses.KEY_UP):
                self.move_version_selection(-1)
                return
            if ch == curses.KEY_NPAGE:
                self.move_version_selection(5)
                return
            if ch == curses.KEY_PPAGE:
                self.move_version_selection(-5)
                return
            if ch in (ord("\n"), curses.KEY_ENTER, 10, 13):
                self.install_selected_version(pin=False)
                return
            if ch == ord("p"):
                self.install_selected_version(pin=True)
                return

            self.status = "Version shelf active. Use j/k, Enter, p, or q."
            return

        if ch in (ord("q"), 27):
            self.running = False
            return
        if ch in (curses.KEY_RESIZE,):
            return
        if ch in (ord("j"), curses.KEY_DOWN):
            self.move_selection(1)
            return
        if ch in (ord("k"), curses.KEY_UP):
            self.move_selection(-1)
            return
        if ch == curses.KEY_NPAGE:
            self.move_selection(10)
            return
        if ch == curses.KEY_PPAGE:
            self.move_selection(-10)
            return
        if ch == curses.KEY_HOME:
            self.selected = 0
            return
        if ch == curses.KEY_END:
            if self.mode == "log":
                self.selected = len(self.log_lines) - 1
            else:
                self.selected = len(self.current_items()) - 1
            return
        if ch == ord("/"):
            if self.mode == "installed":
                self.filter_installed()
            else:
                self.search()
            return
        if ch == ord("s"):
            self.mode = "search"
            self.selected = 0
            self.scroll = 0
            self.search()
            return
        if ch == ord("i"):
            self.mode = "installed"
            self.selected = 0
            self.scroll = 0
            if not self.installed_items or time.time() - self.last_installed_load > 300:
                self.refresh_installed(background=False)
            else:
                self.status = "Installed packages view."
            return
        if ch == ord("l"):
            self.mode = "log"
            self.selected = max(0, len(self.log_lines) - 1)
            self.scroll = 0
            self.status = "Log view."
            return
        if ch == ord("r"):
            if self.mode == "installed":
                self.refresh_installed(background=False)
            elif self.mode == "search" and self.query:
                self.spawn_job(
                    "searching", lambda: self.search_packages(self.query, "all")
                )
            else:
                self.status = "Nothing to refresh."
            return
        if ch == ord("u"):
            self.update_system()
            return
        if ch == ord("v"):
            self.show_info()
            return
        if ch == ord("V"):
            self.show_versions()
            return
        if ch == ord("e"):
            self.run_appimage()
            return
        if ch == ord(" "):
            self.toggle_mark_selected()
            return
        if ch == ord("a"):
            self.mark_current_items()
            return
        if ch == ord("c"):
            self.clear_marked()
            return
        if ch in (ord("\n"), curses.KEY_ENTER, 10, 13):
            if self.mode == "search":
                self.install_selected()
            elif self.mode == "installed":
                self.show_info()
            return
        if ch == ord("x"):
            if self.mode == "installed" or self.marked:
                self.remove_selected()
            else:
                self.status = (
                    "Switch to installed view with i before removing packages."
                )
            return
        if ch == ord("?"):
            self.show_help()
            return

    def move_version_selection(self, delta: int) -> None:
        if not self.version_rows:
            self.status = "No versions loaded yet."
            return

        viewport = 5
        total = len(self.version_rows)

        self.version_cursor = max(0, min(total - 1, self.version_cursor + delta))

        # Scroll the 5-row window when cursor moves outside it.
        if self.version_cursor < self.version_scroll:
            self.version_scroll = self.version_cursor
        elif self.version_cursor >= self.version_scroll + viewport:
            self.version_scroll = self.version_cursor - viewport + 1

        max_scroll = max(0, total - viewport)
        self.version_scroll = max(0, min(self.version_scroll, max_scroll))

        version = self.version_rows[self.version_cursor]
        self.status = (
            f"Version {self.version_cursor + 1}/{total}: {version.version} "
            f"(window {self.version_scroll + 1}-{min(self.version_scroll + viewport, total)})"
        )

    def selected_version(self) -> PackageVersion | None:
        if not self.version_rows:
            return None
        self.version_cursor = max(
            0, min(self.version_cursor, len(self.version_rows) - 1)
        )
        return self.version_rows[self.version_cursor]

    def install_selected_version(self, pin: bool = False) -> None:
        item = self.selected_item()
        version = self.selected_version()
        if not item or not version:
            self.status = "No version selected."
            return
        pin_text = " with pin" if pin else ""
        self.status = (
            f"Selected {item.package_id} {version.version} for downgrade{pin_text}."
        )
        self.log(
            f"version selected: {item.package_id} -> {version.version} ({version.origin or version.manager})"
        )

    def show_help(self) -> None:
        help_text = [
            "Keys:",
            "/ search or filter installed packages",
            "i installed packages section",
            "s search results section",
            "Space select or unselect focused package",
            "a select all packages currently shown",
            "c clear selected packages",
            "Enter install focused package or selected packages",
            "e run the focused installed AppImage",
            "x remove focused installed package or selected packages",
            "u update package ecosystems in the background",
            "v show package info in log view",
            "V list available/cached versions",
            "r refresh current section",
            "l log view",
            "q quit",
        ]
        self.log("\n".join(help_text))
        self.mode = "log"
        self.selected = len(self.log_lines) - 1
        self.status = "Help added to log view."

    def move_selection(self, delta: int) -> None:
        if self.mode == "log":
            max_index = max(0, len(self.log_lines) - 1)
        else:
            max_index = max(0, len(self.current_items()) - 1)
        self.selected = max(0, min(max_index, self.selected + delta))

    def ensure_visible(self, view_height: int) -> None:
        if self.selected < self.scroll:
            self.scroll = self.selected
        if self.selected >= self.scroll + view_height:
            self.scroll = max(0, self.selected - view_height + 1)

    def header_height(self, width: int) -> int:
        return 4

    def footer_height(self) -> int:
        return 4

    def download_height(self, available_height: int) -> int:
        if available_height < 12:
            return 0
        return min(7, max(5, available_height // 4))

    def source_tag(self, source: str) -> str:
        return {
            "aur/local": "local",
            "appimage": "appimg",
            "flatpak": "flatpak",
            "pacman": "pacman",
            "cargo": "cargo",
            "npm": "npm",
            "pip": "pip",
            "pipx": "pipx",
            "brew": "brew",
            "aur": "aur",
            "apt": "apt",
            "snap": "snap",
        }.get(source, source)

    def source_attr(self, source: str) -> int:
        return {
            "pacman": curses.color_pair(4),
            "aur": curses.color_pair(6),
            "aur/local": curses.color_pair(6),
            "flatpak": curses.color_pair(3),
            "apt": curses.color_pair(1),
            "snap": curses.color_pair(5),
            "appimage": curses.color_pair(3),
            "cargo": curses.color_pair(4),
            "npm": curses.color_pair(5),
            "pip": curses.color_pair(1),
            "pipx": curses.color_pair(1),
            "brew": curses.color_pair(4),
        }.get(source, curses.A_NORMAL)

    def source_summary(self, items: list[PackageItem]) -> str:
        counts: dict[str, int] = {}
        for item in items:
            tag = self.source_tag(item.source)
            counts[tag] = counts.get(tag, 0) + 1
        if not counts:
            return "sources: none"
        preferred = (
            "pacman",
            "aur",
            "local",
            "flatpak",
            "apt",
            "snap",
            "appimg",
            "cargo",
            "npm",
            "pip",
            "pipx",
            "brew",
        )
        parts = [f"{key}:{counts[key]}" for key in preferred if key in counts]
        parts.extend(
            f"{key}:{value}"
            for key, value in sorted(counts.items())
            if key not in preferred
        )
        return "sources: " + " ".join(parts)

    def draw_box(
        self,
        y: int,
        x: int,
        height: int,
        width: int,
        title: str = "",
        active: bool = False,
    ) -> None:
        if height <= 1 or width <= 2:
            return
        attr = curses.color_pair(1) | curses.A_BOLD if active else curses.A_DIM
        top = "+" + "-" * max(0, width - 2) + "+"
        if title and width > 8:
            title_text = f" {title} "
            insert = min(3, max(1, width - 4))
            available = max(0, width - insert - 2)
            title_text = clip(title_text, available)
            top = top[:insert] + title_text + top[insert + len(title_text) :]
        bottom = "+" + "-" * max(0, width - 2) + "+"
        self.safe_addstr(y, x, top, attr)
        for row in range(1, height - 1):
            self.safe_addstr(y + row, x, "|", attr)
            self.safe_addstr(y + row, x + width - 1, "|", attr)
        self.safe_addstr(y + height - 1, x, bottom, attr)

    def draw(self) -> None:
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        if h < 14 or w < 56:
            self.safe_addstr(0, 0, f"Terminal is too small for {constants.APP_NAME}.")
            self.stdscr.refresh()
            return

        self.draw_header(h, w)
        if self.mode == "log":
            self.draw_log(h, w)
        else:
            self.draw_packages(h, w)
        self.draw_status(h, w)
        self.spinner_index += 1
        self.stdscr.refresh()

    def draw_header(self, h: int, w: int) -> None:
        header_h = self.header_height(w)
        self.draw_box(0, 0, header_h, w, " PACKAGE MANAGER ", active=True)
        title = f"{constants.APP_NAME} {constants.VERSION}"
        self.safe_addstr(
            1,
            max(1, (w - len(title)) // 2),
            clip(title, w - 4),
            curses.color_pair(1) | curses.A_BOLD,
        )

        tabs = [
            ("s", "Search", self.mode == "search"),
            ("i", "Installed", self.mode == "installed"),
            ("l", "Log", self.mode == "log"),
        ]
        x = 2
        y = header_h - 2
        for key, label, active in tabs:
            text = f"[{key.upper()}:{label.upper()}]"
            attr = (
                curses.color_pair(2) | curses.A_BOLD if active else curses.color_pair(1)
            )
            self.safe_addstr(y, x, text[: max(0, w - x - 2)], attr)
            x += len(text) + 1

    def draw_packages(self, h: int, w: int) -> None:
        top = self.header_height(w)
        total_height = max(1, h - top - self.footer_height())
        monitor_h = self.download_height(total_height)
        height = max(1, total_height - monitor_h)
        items = self.current_items()
        wide = w >= 96
        list_w = w if not wide else min(max(56, int(w * 0.62)), w - 34)
        detail_x = list_w
        detail_w = w - detail_x
        rows_available = max(1, height - 4)
        self.ensure_visible(rows_available)
        visible = items[
            self.scroll : self.scroll + rows_available
        ]  # what is this for??

        if self.mode == "search":
            title = f" SEARCH :: {len(items)} RESULTS "
        else:
            title = f" INSTALLED :: {len(items)} PACKAGES "
        self.draw_box(top, 0, height, list_w, title, active=True)
        inner_w = max(1, list_w - 2)

        row_start = top + 2
        source_line = self.source_summary(items)
        if self.marked:
            source_line = f"{source_line}  |  selected:{len(self.marked)}"
        self.safe_addstr(top + 1, 1, clip(source_line, inner_w), curses.A_DIM)
        if not items:
            if self.mode == "search":
                empty = "Press / to search."
            else:
                empty = "No installed packages loaded."
            if self.busy:
                empty = f"{self.busy_label}..."
            self.safe_addstr(
                row_start, 2, clip(empty, max(1, inner_w - 2)), curses.A_DIM
            )
        row_y = row_start
        index = self.scroll
        bottom_y = top + height - 1

        while index < len(items) and row_y < bottom_y:
            item = items[index]
            selected = index == self.selected
            attr = curses.color_pair(2) if selected else curses.A_NORMAL
            mark = "*" if self.is_marked(item) else " "
            cursor = ">" if selected else " "

            self.safe_addstr(row_y, 1, " " * inner_w, attr)
            line = f"{cursor}{mark} {item.name}"
            self.safe_addstr(row_y, 1, clip(line, inner_w), attr)
            row_y += 1

            if (
                self.version_shelf_open
                and self.version_target_key == package_key(item)
                and row_y < bottom_y
            ):
                row_y = self.draw_version_shelf(row_y, 1, inner_w, bottom_y)

            index += 1

        if wide:
            self.draw_detail(top, detail_x, height, detail_w)
        if monitor_h:
            self.draw_downloads(top + height, 0, monitor_h, w)

    def draw_version_shelf(self, y: int, x: int, width: int, bottom_y: int) -> int:
        total = len(self.version_rows)
        viewport = 5

        # Header + 5 version rows + footer, unless terminal space is smaller.
        max_rows = max(1, bottom_y - y - 2)
        shelf_h = min(viewport, max_rows)

        if total:
            if self.version_cursor < self.version_scroll:
                self.version_scroll = self.version_cursor
            elif self.version_cursor >= self.version_scroll + shelf_h:
                self.version_scroll = self.version_cursor - shelf_h + 1

            max_scroll = max(0, total - shelf_h)
            self.version_scroll = max(0, min(self.version_scroll, max_scroll))

        start = self.version_scroll
        end = min(start + shelf_h, total)

        up = "^" if start > 0 else " "
        down = "v" if end < total else " "
        current = self.version_cursor + 1 if total else 0

        header = f"  ├─ versions {current}/{total} {up}{down}"
        self.safe_addstr(
            y, x, clip(header, width), curses.color_pair(1) | curses.A_BOLD
        )
        y += 1

        if not self.version_rows:
            msg = (
                "  │  loading versions..."
                if self.busy_label.startswith("loading versions")
                else "  │  no versions found"
            )
            self.safe_addstr(y, x, clip(msg, width), curses.A_DIM)
            y += 1
        else:
            visible_versions = self.version_rows[start:end]

            for offset, version in enumerate(visible_versions):
                version_index = start + offset
                focused = version_index == self.version_cursor
                attr = curses.color_pair(2) if focused else curses.A_NORMAL
                marker = ">" if focused else " "
                state = (
                    "installed"
                    if version.installed
                    else (version.origin or version.manager or "remote")
                )

                line = f"  │  {marker} {version.version:<16} {state}"
                self.safe_addstr(y, x, clip(line, width), attr)
                y += 1

        if y < bottom_y:
            footer = "  └─ j/k scroll | Enter select | p pin | Esc/q close"
            self.safe_addstr(y, x, clip(footer, width), curses.A_DIM)
            y += 1

        return y

    def draw_detail(self, y: int, x: int, height: int, width: int) -> None:
        self.draw_box(y, x, height, width, " DETAILS ", active=False)
        inner_x = x + 1
        inner_y = y + 1
        inner_w = max(1, width - 2)
        inner_h = max(1, height - 2)
        item = self.selected_item()
        if not item:
            self.safe_addstr(inner_y, inner_x, "No package selected.", curses.A_DIM)
            return

        lines = [
            item.title(),
            f"source: {item.source}",
            f"manager: {item.manager}",
            f"version: {item.version or 'unknown'}",
            f"selected: {'yes' if self.is_marked(item) else 'no'}",
        ]
        if item.repo:
            lines.append(f"repo/remote: {item.repo}")
        if item.installed:
            lines.append("state: installed")
        if item.description:
            lines.append("")
            lines.extend(textwrap.wrap(item.description, width=max(10, width - 2)))
        if self.version_target_key == package_key(item):
            lines.append("")
            if self.version_rows:
                lines.append(f"Versions ({len(self.version_rows)}):")
                for version in self.version_rows[:6]:
                    installed = " *" if version.installed else ""
                    origin = f" [{version.origin}]" if version.origin else ""
                    lines.append(
                        f"{version.version}{installed} - {version.manager}{origin}"
                    )
                if len(self.version_rows) > 6:
                    lines.append(f"+{len(self.version_rows) - 6} more in log")
            elif self.busy_label.startswith("loading versions"):
                lines.append("Versions: loading...")
        lines.append("")
        lines.append("Actions:")
        lines.append("Space select/unselect")
        if item.source == "appimage":
            lines.append("Enter run installed / install catalog entry")
            lines.append("e run installed AppImage")
            lines.append("v file info")
            lines.append("x remove file in installed view")
        else:
            lines.append("Enter install or info")
            lines.append("v package info")
            lines.append("V versions")
            lines.append("x remove installed/selected")

        for offset, line in enumerate(lines[:inner_h]):
            attr = curses.A_BOLD if offset == 0 else curses.A_NORMAL
            if line.startswith("source:"):
                attr = self.source_attr(item.source)
            self.safe_addstr(inner_y + offset, inner_x, clip(line, inner_w), attr)

    def draw_downloads(self, y: int, x: int, height: int, width: int) -> None:
        self.draw_box(y, x, height, width, " OPERATIONS ", active=False)
        inner_x = x + 1
        inner_y = y + 1
        inner_w = max(1, width - 2)
        inner_h = max(1, height - 2)
        jobs = self.download_jobs[-max(1, inner_h // 2) :]
        if not jobs:
            self.safe_addstr(inner_y, inner_x, "idle", curses.A_DIM)
            self.safe_addstr(
                inner_y + 1, inner_x, "background installs appear here", curses.A_DIM
            )
            return

        row = 0
        for job in jobs:
            if row >= inner_h:
                break
            symbol = {
                "queued": ".",
                "running": constants.SPINNER[
                    self.spinner_index % len(constants.SPINNER)
                ],
                "done": "+",
                "failed": "!",
            }.get(job.status, "?")
            attr = curses.color_pair(4) if job.status == "done" else curses.A_NORMAL
            if job.status == "failed":
                attr = curses.color_pair(5) | curses.A_BOLD
            elif job.status == "running":
                attr = curses.color_pair(3) | curses.A_BOLD
            progress = job.progress or "--"
            speed = job.speed or "--/s"
            eta = job.eta or "--"
            line = f"{symbol} {job.label} [{job.status}] {progress} {speed} eta {eta}"
            self.safe_addstr(inner_y + row, inner_x, clip(line, inner_w), attr)
            row += 1
            if row >= inner_h:
                break
            detail = job.last_line or shlex.join(job.cmd)
            self.safe_addstr(
                inner_y + row, inner_x, clip(detail, inner_w), curses.A_DIM
            )
            row += 1

    def draw_log(self, h: int, w: int) -> None:
        top = self.header_height(w)
        height = max(1, h - top - self.footer_height())
        self.draw_box(top, 0, height, w, " ACTIVITY ", active=True)
        rows_available = max(1, height - 3)
        self.ensure_visible(rows_available)
        total = len(self.log_lines)
        self.safe_addstr(
            top + 1,
            1,
            clip(f"{total} lines | r refresh current section | ? help", w - 2),
            curses.color_pair(1) | curses.A_BOLD,
        )
        start = max(0, min(self.scroll, max(0, total - rows_available)))
        lines = self.log_lines[start : start + rows_available]
        for offset, line in enumerate(lines):
            self.safe_addstr(top + 2 + offset, 1, clip(line, w - 2))

    def draw_status(self, h: int, w: int) -> None:
        y = h - self.footer_height()
        self.draw_box(y, 0, self.footer_height(), w, " STATUS ", active=False)
        status = self.status
        if self.busy:
            status = f"{constants.SPINNER[self.spinner_index % len(constants.SPINNER)]} {status}"
        active_downloads = len(self.active_download_jobs())
        if active_downloads and "downloads:" not in status:
            status = f"{status}  | downloads:{active_downloads}"
        if self.marked and "selected:" not in status:
            status = f"{status}  | selected:{len(self.marked)}"
        self.safe_addstr(y + 1, 1, pad(status, w - 2), curses.color_pair(3))
        keys = "/ search  Space select  Enter install  e run AppImage  x remove  V versions  u update  ? help"
        self.safe_addstr(y + 2, 1, pad(keys, w - 2), curses.A_DIM)

    def clear_line(self, y: int) -> None:
        h, w = self.stdscr.getmaxyx()
        if 0 <= y < h:
            self.safe_addstr(y, 0, " " * max(0, w - 1))

    def safe_addstr(self, y: int, x: int, text: str, attr: int = 0) -> None:
        h, w = self.stdscr.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        limit = max(0, w - x)
        if y == h - 1:
            limit = max(0, limit - 1)
        try:
            self.stdscr.addstr(y, x, text[:limit], attr)
        except curses.error:
            pass

    def run(self) -> None:
        self.setup()
        while self.running:
            self.poll_events()
            self.draw()
            self.handle_key(self.stdscr.getch())


def headless_ui(
    tools: Tools | None = None,
    cache: PackageCache | None = None,
) -> PkgUI:
    """Build the search engine without initializing curses."""
    app = PkgUI.__new__(PkgUI)
    app.tools = tools or Tools.detect()
    app.cache = cache or PackageCache()
    app.marked = {}
    app.log_lines = []
    app.installed_items = []
    app.installed_names = set()
    app.installed_apt_names = set()
    app.installed_flatpak_ids = set()
    app.installed_snap_names = set()
    app.installed_extra_names = {}
    app.apply_installed_items(app.cache.load_installed())
    return app


def main(stdscr: curses._CursesWindow, initial_query: str = "") -> None:
    app = PkgUI(stdscr, initial_query)
    app.run()
