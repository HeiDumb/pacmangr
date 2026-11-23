"""Discovery backends for repositories, venvs, AppImages and installed packages."""

from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path
from typing import Callable

from . import constants
from .commands import manager_spec_command
from .models import PackageItem, Tools
from .parsers import (
    parse_apt_installed,
    parse_flatpak_installed,
    parse_manager_installed,
    parse_pacman_installed,
    parse_snap_installed,
)
from .utils import human_size, run_capture


def is_git_url(value: str) -> bool:
    candidate = value.strip()
    if candidate.startswith(("https://", "http://", "ssh://", "git://", "file://")):
        return "/" in urllib.parse.urlparse(candidate).path
    return bool(re.match(r"^[\w.-]+@[\w.-]+:[\w./-]+(?:\.git)?$", candidate))


def git_checkout_slug(url: str) -> str:
    candidate = url.strip().rstrip("/")
    if re.match(r"^[\w.-]+@[\w.-]+:", candidate):
        path = candidate.split(":", 1)[1]
    else:
        path = urllib.parse.urlparse(candidate).path.lstrip("/")
    path = re.sub(r"\.git$", "", path)
    parts = [re.sub(r"[^A-Za-z0-9_.+-]+", "-", part) for part in path.split("/") if part]
    slug = "--".join(parts[-2:]) if parts else "repository"
    return slug.strip("-.") or "repository"


def git_package(url: str) -> PackageItem | None:
    if not is_git_url(url):
        return None
    clean_url = url.strip()
    slug = git_checkout_slug(clean_url)
    target = constants.GIT_SOURCE_ROOT / slug
    name = slug.split("--")[-1]
    return PackageItem(
        source="git",
        manager="git",
        name=name,
        package_id=str(target),
        repo="managed Git checkout",
        installed=(target / ".git").is_dir(),
        origin=clean_url,
        description=f"Fetch {clean_url} into {target}. Pacmangr will not execute repository build scripts automatically.",
    )


def managed_git_checkouts(tools: Tools) -> list[PackageItem]:
    if not tools.git or not constants.GIT_SOURCE_ROOT.is_dir():
        return []
    items: list[PackageItem] = []
    for target in sorted(constants.GIT_SOURCE_ROOT.iterdir()):
        if not (target / ".git").is_dir():
            continue
        code, output = run_capture([tools.git, "-C", str(target), "remote", "get-url", "origin"], timeout=5)
        url = output.strip() if code == 0 else ""
        item = git_package(url) if url else None
        if item is None:
            item = PackageItem("git", "git", target.name, str(target), installed=True, repo="managed Git checkout")
        item.package_id = str(target)
        item.installed = True
        items.append(item)
    return items


def managed_pip_venvs() -> list[PackageItem]:
    if not constants.PIP_VENV_ROOT.is_dir():
        return []
    items: list[PackageItem] = []
    for target in sorted(constants.PIP_VENV_ROOT.iterdir()):
        metadata = target / ".pacmangr-package"
        if not (target / "bin/python").is_file() or not metadata.is_file():
            continue
        try:
            package = metadata.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not package:
            continue
        items.append(PackageItem(
            source="pip",
            manager="pip",
            name=package,
            package_id=package,
            repo="isolated venv",
            installed=True,
            origin=f"venv:{target}",
            description=f"Isolated Python environment: {target}",
        ))
    return items


def appimage_roots() -> list[Path]:
    home = Path.home()
    return [
        home / "Applications",
        home / "Downloads",
        home / ".local" / "bin",
        home / ".local" / "share" / "AppImages",
        home / ".local" / "share" / "appimagekit",
        home / ".local" / "share" / "applications",
        Path("/opt"),
    ]


def find_appimages(query: str = "") -> list[PackageItem]:
    needle = query.lower().strip()
    seen: set[Path] = set()
    items: list[PackageItem] = []
    for root in appimage_roots():
        if not root.exists():
            continue
        root = root.resolve()
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            current = Path(dirpath)
            try:
                depth = len(current.relative_to(root).parts)
            except ValueError:
                depth = 0
            if depth >= constants.APPIMAGE_SCAN_DEPTH:
                dirnames[:] = []
            for filename in filenames:
                if not filename.lower().endswith(".appimage"):
                    continue
                path = current / filename
                try:
                    resolved = path.resolve()
                except OSError:
                    resolved = path
                if resolved in seen:
                    continue
                haystack = f"{filename} {path}".lower()
                if needle and needle not in haystack:
                    continue
                seen.add(resolved)
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                items.append(
                    PackageItem(
                        source="appimage",
                        manager="appimage",
                        repo="local file",
                        name=path.stem,
                        package_id=str(path),
                        version=human_size(size),
                        description=f"Local AppImage: {path}",
                        installed=True,
                    )
                )
    return sorted(items, key=lambda item: item.name.lower())




def collect_installed_packages(
    tools: Tools,
    log: Callable[[str], None] | None = None,
) -> list[PackageItem]:
    report = log or (lambda _message: None)
    items: list[PackageItem] = []
    if tools.pacman:
        _, foreign_output = run_capture([tools.pacman, "-Qqm"], timeout=20)
        foreign_names = {line.strip() for line in foreign_output.splitlines() if line.strip()}
        code, output = run_capture([tools.pacman, "-Q"], timeout=30)
        if code == 0:
            items.extend(parse_pacman_installed(output, foreign_names))
        else:
            report(f"pacman installed list exited {code}:\n{output.strip()}")

    if tools.flatpak:
        code, output = run_capture([tools.flatpak, "list", "--app", "--json"], timeout=30)
        if code == 0:
            items.extend(parse_flatpak_installed(output))
        else:
            report(f"flatpak installed list exited {code}:\n{output.strip()}")

    if tools.dpkg_query:
        code, output = run_capture(
            [
                tools.dpkg_query,
                "-W",
                "-f=${binary:Package}\\t${Version}\\t${db:Status-Abbrev}\\t${binary:Summary}\\n",
            ],
            timeout=40,
        )
        if code == 0:
            items.extend(parse_apt_installed(output))
        else:
            report(f"dpkg installed list exited {code}:\n{output.strip()}")

    if tools.snap:
        code, output = run_capture([tools.snap, "list"], timeout=30)
        if code == 0:
            items.extend(parse_snap_installed(output))
        else:
            report(f"snap installed list exited {code}:\n{output.strip()}")

    for manager in tools.extra_managers:
        spec = constants.MANAGER_SPECS.get(manager, {})
        if "installed" not in spec:
            continue
        cmd = manager_spec_command(manager, "installed", tools)
        if not cmd:
            continue
        code, output = run_capture(cmd, timeout=45)
        if code == 0:
            items.extend(parse_manager_installed(manager, output))
        else:
            report(f"{manager} installed list exited {code}:\n{output.strip()}")

    items.extend(managed_git_checkouts(tools))
    items.extend(managed_pip_venvs())
    items.extend(find_appimages())
    return sorted(items, key=lambda item: (item.source, item.name.lower()))
