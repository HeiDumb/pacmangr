"""Backend loading and shared constants for the pacmangr GTK front-end.

The CLI/headless backend deliberately stays a single executable.  This module
loads it from the directory next to the GUI package and keeps the exported
``CORE`` module untouched so callers may still mutate backend attributes.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path


def _backend_path() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        here.parent.parent / "pacmangr",
        here.parent / "pacmangr",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def load_core():
    """Load the sibling ``pacmangr`` executable as a Python module."""
    script = _backend_path()
    loader = importlib.machinery.SourceFileLoader("pacmangr_gui_core", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"Could not load pacmangr backend from {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


# The real backend module is exported directly (not proxied): tests and callers
# assign to attributes such as ``CORE.GIT_SOURCE_ROOT``.
CORE = load_core()

APP_ID = "io.github.hei.pacmangr"
MAX_GUI_RESULTS = 250
SORT_CHOICES = (
    ("Relevance", "relevance"),
    ("Name", "name"),
    ("Source", "source"),
    ("Installed first", "installed"),
)


def source_choices(tools) -> list[tuple[str, str]]:
    """Return available search scopes in a predictable desktop-friendly order."""
    choices = [("All sources", "all")]
    known = (
        ("System packages", "pacman", tools.pacman),
        ("AUR · yay", "yay", tools.yay),
        ("AUR · paru", "paru", tools.paru),
        ("Flatpak", "flatpak", tools.flatpak),
        ("APT", "apt", tools.apt_cache),
        ("Snap", "snap", tools.snap),
        ("Git repository", "git", getattr(tools, "git", None)),
        ("GitHub", "github", True),
    )
    choices.extend((label, key) for label, key, path in known if path)
    for manager in tools.extra_managers:
        if "search" in CORE.MANAGER_SPECS.get(manager, {}):
            choices.append((manager.replace("-", " ").title(), manager))
    choices.append(("AppImages", "appimage"))
    return choices
