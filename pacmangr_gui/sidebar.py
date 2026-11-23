"""Slim icon-only navigation rail with unobtrusive badges."""

from __future__ import annotations

from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk  # noqa: E402


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str
    description: str = ""


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("browse", "Browse & Install", "system-software-install-symbolic",
            "Search and install software"),
    NavItem("installed", "Installed", "computer-symbolic",
            "Packages already on this system"),
    NavItem("updates", "Updates", "software-update-available-symbolic",
            "Available package upgrades"),
    NavItem("github", "GitHub", "git-branch-symbolic",
            "Search and clone public repositories"),
    NavItem("orphans", "Orphaned Packages", "edit-delete-symbolic",
            "Unused dependencies you can remove"),
)

SETTINGS_ITEM = NavItem("settings", "Settings", "preferences-system-symbolic",
                        "Preferences and diagnostics")


class Sidebar(Gtk.Box):
    """A quiet, always-discoverable icon rail; navigation lives only here."""

    def __init__(self, active: str = "browse", on_activate=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("nav-rail")
        self.set_size_request(58, -1)
        self.set_vexpand(True)
        self.on_activate = on_activate
        self._buttons: dict[str, Gtk.Button] = {}
        self._badges: dict[str, Gtk.Label] = {}

        top_padding = Gtk.Box()
        top_padding.set_size_request(-1, 8)
        self.append(top_padding)

        for item in NAV_ITEMS:
            self._append_item(item)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        self.append(spacer)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.add_css_class("rail-separator")
        separator.set_margin_start(12)
        separator.set_margin_end(12)
        separator.set_margin_top(6)
        separator.set_margin_bottom(6)
        self.append(separator)

        self._append_item(SETTINGS_ITEM)
        self.set_active(active)

    def _append_item(self, item: NavItem) -> None:
        button = Gtk.Button()
        button.add_css_class("flat")
        button.add_css_class("nav-icon")
        button.set_size_request(44, 44)
        tooltip = item.label if not item.description else f"{item.label} — {item.description}"
        button.set_tooltip_text(tooltip)

        overlay = Gtk.Overlay()
        icon = Gtk.Image.new_from_icon_name(item.icon)
        icon.set_pixel_size(22)
        icon.add_css_class("nav-icon-image")
        overlay.set_child(icon)

        badge = Gtk.Label(label="")
        badge.add_css_class("nav-badge")
        badge.set_halign(Gtk.Align.END)
        badge.set_valign(Gtk.Align.START)
        badge.set_margin_top(1)
        badge.set_margin_end(1)
        badge.set_visible(False)
        overlay.add_overlay(badge)

        button.set_child(overlay)
        button.connect("clicked", self._activated, item.key)
        self.append(button)
        self._buttons[item.key] = button
        self._badges[item.key] = badge

    def _activated(self, _button, key: str) -> None:
        if key != "settings":
            self.set_active(key)
        if self.on_activate:
            self.on_activate(key)

    def set_active(self, key: str) -> None:
        for name, button in self._buttons.items():
            if name == key:
                button.add_css_class("active")
            else:
                button.remove_css_class("active")

    def set_badge(self, key: str, count: int) -> None:
        badge = self._badges.get(key)
        if badge is None:
            return
        try:
            value = int(count)
        except (TypeError, ValueError):
            value = 0
        badge.set_label(str(value) if value > 0 else "")
        badge.set_visible(value > 0)
        button = self._buttons.get(key)
        if button:
            if value > 0:
                button.add_css_class("has-badge")
            else:
                button.remove_css_class("has-badge")

    def focus_search_hint(self, key: str) -> str:
        for item in NAV_ITEMS:
            if item.key == key:
                return item.label
        return ""
