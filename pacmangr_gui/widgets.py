"""Reusable GTK widgets and informational dialogs."""

from __future__ import annotations

import hashlib
from pathlib import Path
import threading
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .core_loader import CORE  # noqa: E402


SOURCE_PACKAGE_ICON = "package-x-generic-symbolic"
ICON_CACHE = Path.home() / ".cache/pacmangr/icons"


def package_icon_name(item) -> str:
    """Prefer an installed app icon for this package, with a safe fallback."""
    try:
        display = Gdk.Display.get_default()
        if display:
            theme = Gtk.IconTheme.get_for_display(display)
            candidates = (
                getattr(item, "icon", ""),
                getattr(item, "package_id", ""),
                getattr(item, "name", ""),
            )
            for candidate in candidates:
                candidate = str(candidate or "").strip()
                if candidate and "/" not in candidate and theme.has_icon(candidate):
                    return candidate
    except (AttributeError, TypeError, RuntimeError):
        pass
    return SOURCE_PACKAGE_ICON


def load_source_icon(image: Gtk.Image, item) -> None:
    """Load a source-provided icon without blocking the GTK event loop."""
    url = str(
        getattr(item, "icon_url", "")
        or getattr(item, "github_avatar_url", "")
        or ""
    ).strip()
    if not url.startswith("https://"):
        return

    cache_path = ICON_CACHE / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.img"

    def apply_icon(path: Path) -> bool:
        try:
            texture = Gdk.Texture.new_from_filename(str(path))
            image.set_from_paintable(texture)
        except (GLib.Error, OSError, TypeError):
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_REMOVE

    if cache_path.is_file():
        GLib.idle_add(apply_icon, cache_path)
        return

    def worker() -> None:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Pacmangr-GUI"})
            with urllib.request.urlopen(request, timeout=8) as response:
                content_type = response.headers.get_content_type()
                data = response.read(1_000_001)
            if not content_type.startswith("image/") or not data or len(data) > 1_000_000:
                return
            ICON_CACHE.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(cache_path)
            GLib.idle_add(apply_icon, cache_path)
        except Exception:
            return

    threading.Thread(target=worker, daemon=True).start()


def cache_summary(cache) -> str:
    if not cache.path.exists():
        return f"Cache is empty.\n\n{cache.path}"
    lines = [f"Location\n{cache.path}", f"Size\n{CORE.human_size(cache.path.stat().st_size)}"]
    try:
        with cache.connect() as conn:
            labels = (
                ("search_cache", "Search results"),
                ("installed_packages", "Installed packages"),
                ("version_cache", "Package versions"),
            )
            for table, label in labels:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                lines.append(f"{label}\n{count}")
    except Exception as exc:  # noqa: BLE001 - diagnostics must stay usable with a bad cache.
        lines.append(f"Database status\nUnreadable: {exc}")
    return "\n\n".join(lines)


class PackageRow(Gtk.ListBoxRow):
    def __init__(self, item, *, compact: bool = False) -> None:
        super().__init__()
        self.item = item
        self.add_css_class("package-row")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.add_css_class("package-row-box")
        if compact:
            box.add_css_class("compact")

        icon = Gtk.Image.new_from_icon_name(package_icon_name(item))
        icon.set_pixel_size(21 if compact else 26)
        icon.set_size_request(34 if compact else 40, 34 if compact else 40)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_valign(Gtk.Align.CENTER)
        icon.add_css_class("package-icon")
        load_source_icon(icon, item)
        box.append(icon)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2 if compact else 4)
        content.set_hexpand(True)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name = Gtk.Label(label=item.title(), xalign=0)
        name.set_hexpand(True)
        name.set_ellipsize(3)
        name.add_css_class("package-name")
        top.append(name)

        source = Gtk.Label(label=item.source)
        source.add_css_class("pill")
        top.append(source)

        if getattr(item, "is_orphan", False):
            orphan_pill = Gtk.Label(label="orphan")
            orphan_pill.add_css_class("pill")
            orphan_pill.add_css_class("orphan-pill")
            top.append(orphan_pill)
        elif getattr(item, "install_reason", "") == "explicit":
            exp_pill = Gtk.Label(label="explicit")
            exp_pill.add_css_class("pill")
            exp_pill.add_css_class("explicit-pill")
            top.append(exp_pill)

        if item.installed and not compact:
            installed = Gtk.Label(label="installed")
            installed.add_css_class("pill")
            installed.add_css_class("installed-pill")
            top.append(installed)
        content.append(top)

        meta_text = item.version or "version unknown"
        if item.repo:
            meta_text += f"  ·  {item.repo}"
        meta = Gtk.Label(label=meta_text, xalign=0)
        meta.set_ellipsize(3)
        meta.add_css_class("muted")
        content.append(meta)

        if item.description and not compact:
            desc = Gtk.Label(label=item.description, xalign=0)
            desc.set_ellipsize(3)
            desc.add_css_class("muted")
            content.append(desc)

        box.append(content)
        self.set_child(box)


class EmptyState(Gtk.Box):
    """Friendly placeholder used by empty lists and unavailable views."""

    def __init__(self, title: str, detail: str = "", icon: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("empty-state")
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)
        if icon:
            image = Gtk.Image.new_from_icon_name(icon)
            image.set_pixel_size(48)
            self.append(image)
        heading = Gtk.Label(label=title, xalign=0.5)
        heading.add_css_class("empty-state-title")
        heading.set_wrap(True)
        self.append(heading)
        if detail:
            body = Gtk.Label(label=detail, xalign=0.5)
            body.add_css_class("muted")
            body.set_wrap(True)
            self.append(body)


def show_text_dialog(parent, title: str, detail: str) -> None:
    if not isinstance(parent, Gtk.Window):
        return
    dialog = Gtk.AlertDialog()
    dialog.set_message(title)
    dialog.set_detail(detail)
    dialog.set_buttons(["Close"])
    dialog.set_default_button(0)
    dialog.set_cancel_button(0)
    dialog.choose(parent, None, lambda alert, result: alert.choose_finish(result))


def ask_confirmation(
    parent,
    title: str,
    detail: str,
    accept_label: str = "Continue",
    on_accept=None,
    danger: bool = False,
) -> None:
    """Show a consistent two-button confirmation dialog."""
    if not isinstance(parent, Gtk.Window):
        return
    dialog = Gtk.AlertDialog()
    dialog.set_message(title)
    dialog.set_detail(detail)
    dialog.set_buttons(["Cancel", accept_label])
    dialog.set_cancel_button(0)
    dialog.set_default_button(1)
    if danger:
        try:
            dialog.set_property("destructive-button", 1)
        except Exception:
            pass

    def finished(alert: Gtk.AlertDialog, result) -> None:
        try:
            response = alert.choose_finish(result)
        except GLib.Error:
            return
        if response == 1 and on_accept:
            on_accept()

    dialog.choose(parent, None, finished)


def show_manager_status(tools, sources: list[tuple[str, str]]) -> str:
    lines = []
    for label, key in sources[1:]:
        if key == "appimage":
            lines.append(f"{label}\nLocal files in Applications folders")
            continue
        if key == "github":
            lines.append(f"{label}\nGitHub repository search (internet required)")
            continue
        path = None
        if key in {"pacman", "yay", "paru", "flatpak", "apt", "snap", "git"}:
            attr = "apt_cache" if key == "apt" else key
            path = getattr(tools, attr, None)
        else:
            path = getattr(tools, "extra_managers", {}).get(key)
        lines.append(f"{label}\n{path or 'not detected'}")
    lines.append(
        "\nNix note\nProfile and nix-env packages are managed when their CLI is detected; "
        "declarative system or Home Manager files are never rewritten behind your back."
    )
    return "\n\n".join(lines)


def clear_cache_files(cache) -> bool:
    removed = False
    paths = (Path(cache.path), Path(f"{cache.path}-wal"), Path(f"{cache.path}-shm"))
    for path in paths:
        try:
            path.unlink()
            removed = True
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return removed
