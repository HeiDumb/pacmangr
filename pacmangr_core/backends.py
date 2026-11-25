"""Discovery backends for repositories, venvs, AppImages and installed packages."""

from __future__ import annotations

import json
import os
import platform
import re
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

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


APPIMAGE_FEED_URL = "https://appimage.github.io/feed.json"
APPIMAGE_REGISTRY_PATH = constants.APPIMAGE_REGISTRY_PATH
_appimage_feed_lock = threading.Lock()
_appimage_feed_cache: tuple[float, list[dict]] = (float("-inf"), [])


def _curated_appimage_items(query: str, installed: dict) -> list[PackageItem]:
    """Return official AppImages that are missing from the community feed."""
    machine = platform.machine().casefold()
    beeper_arch = {
        "x86_64": "x64",
        "amd64": "x64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    entries = [
        {
            "name": "Beeper",
            "description": "Beeper messaging app — official Linux AppImage.",
            "categories": "Communication",
            "aliases": "beeper desktop automattic",
            "download": (
                "https://api.beeper.com/desktop/download/linux/"
                f"{beeper_arch}/stable/com.automattic.beeper.desktop"
                if beeper_arch
                else ""
            ),
            "project": "https://www.beeper.com/download/linux",
            "icon": "https://www.beeper.com/favicon.ico",
            "architectures": {"x86_64", "amd64", "aarch64", "arm64"},
        },
        {
            "name": "CurseForge",
            "description": "CurseForge app for managing game mods and addons.",
            "categories": "Games",
            "aliases": "curse forge curseforge app",
            "download": "https://curseforge.overwolf.com/downloads/curseforge-latest-linux.AppImage",
            "project": "https://www.curseforge.com/download/app",
            "icon": "https://curseforge.overwolf.com/favicon.ico",
            "architectures": {"x86_64", "amd64"},
        },
    ]
    results: list[PackageItem] = []
    for entry in entries:
        name = entry["name"]
        if machine not in entry["architectures"]:
            continue
        search_text = " ".join(
            (
                name,
                entry["description"],
                entry["categories"],
                entry["aliases"],
            )
        ).casefold()
        if query not in search_text or not entry["download"]:
            continue
        key = _appimage_key(name)
        record = installed.get(key) if isinstance(installed, dict) else None
        local_path = str(record.get("path") or "") if isinstance(record, dict) else ""
        is_installed = bool(local_path and Path(local_path).is_file())
        results.append(
            PackageItem(
                source="appimage",
                manager="appimage",
                name=name,
                package_id=f"appimage:{key}",
                version="Latest AppImage",
                description=entry["description"],
                repo=f"Official AppImage · {entry['categories']}",
                installed=is_installed,
                origin=entry["download"],
                local_path=local_path if is_installed else "",
                catalog_key=key,
                icon_url=entry["icon"],
                project_url=entry["project"],
            )
        )
    return results


def _appimage_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "appimage"


def _appimage_registry() -> dict:
    try:
        data = json.loads(APPIMAGE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_appimage_feed() -> list[dict]:
    global _appimage_feed_cache
    now = time.monotonic()
    with _appimage_feed_lock:
        if now - _appimage_feed_cache[0] < constants.CACHE_TTL_SECONDS["appimage"]:
            return _appimage_feed_cache[1]
        request = urllib.request.Request(
            APPIMAGE_FEED_URL,
            headers={
                "Accept": "application/feed+json, application/json",
                "User-Agent": "Pacmangr",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        entries = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(entries, list):
            raise ValueError("The AppImage catalog returned an invalid feed.")
        _appimage_feed_cache = (
            now,
            [entry for entry in entries if isinstance(entry, dict)],
        )
        return _appimage_feed_cache[1]


def search_appimage_catalog(query: str) -> list[PackageItem]:
    """Search the community catalog and known official AppImage sources."""
    needle = query.casefold().strip()
    if not needle:
        return []
    installed = _appimage_registry()
    curated = _curated_appimage_items(needle, installed)
    # These exact popular app searches should not wait on a remote catalog fetch.
    if curated:
        return curated
    entries = _load_appimage_feed()
    results: list[PackageItem] = []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        description = str(entry.get("description") or "")
        categories = entry.get("categories") or []
        category_text = " ".join(str(category) for category in categories)
        if needle not in f"{name} {description} {category_text}".casefold():
            continue
        links = entry.get("links") if isinstance(entry.get("links"), list) else []
        download_url = ""
        project_url = ""
        for link in links:
            if not isinstance(link, dict):
                continue
            url = str(link.get("url") or "").strip()
            link_type = str(link.get("type") or "").casefold()
            if link_type == "download" and not download_url:
                download_url = (
                    url
                    if url.startswith("https://")
                    else f"https://{url}"
                    if url.startswith("github.com/")
                    else ""
                )
            elif (
                link_type in {"github", "gitlab", "codeberg", "source"}
                and not project_url
            ):
                if url.startswith("https://"):
                    project_url = url
                elif link_type == "gitlab":
                    project_url = f"https://gitlab.com/{url}"
                elif link_type == "codeberg":
                    project_url = f"https://codeberg.org/{url}"
                elif link_type == "github":
                    project_url = f"https://github.com/{url}"
        if not download_url:
            download_url = project_url
        if not download_url.startswith("https://"):
            continue
        key = _appimage_key(name)
        record = installed.get(key) if isinstance(installed, dict) else None
        local_path = (
            str(record.get("path") or "") if isinstance(record, dict) else ""
        )
        is_installed = bool(local_path and Path(local_path).is_file())
        item = PackageItem(
            source="appimage",
            manager="appimage",
            name=name,
            package_id=f"appimage:{key}",
            version="AppImage catalog",
            description=description or "Community catalog AppImage",
            repo=f"AppImage catalog · {category_text}".strip(" ·"),
            installed=is_installed,
            origin=download_url,
            local_path=local_path if is_installed else "",
            catalog_key=key,
            project_url=project_url,
        )
        icons = entry.get("icons")
        if isinstance(icons, list) and icons and isinstance(icons[0], str):
            icon_path = urllib.parse.quote(icons[0].lstrip("/"), safe="/")
            item.icon_url = f"https://appimage.github.io/database/{icon_path}"
        results.append(item)
    return sorted(results, key=lambda item: (item.name.casefold(), item.package_id))


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
    parts = [
        re.sub(r"[^A-Za-z0-9_.+-]+", "-", part) for part in path.split("/") if part
    ]
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
        code, output = run_capture(
            [tools.git, "-C", str(target), "remote", "get-url", "origin"], timeout=5
        )
        url = output.strip() if code == 0 else ""
        item = git_package(url) if url else None
        if item is None:
            item = PackageItem(
                "git",
                "git",
                target.name,
                str(target),
                installed=True,
                repo="managed Git checkout",
            )
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
        items.append(
            PackageItem(
                source="pip",
                manager="pip",
                name=package,
                package_id=package,
                repo="isolated venv",
                installed=True,
                origin=f"venv:{target}",
                description=f"Isolated Python environment: {target}",
            )
        )
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
                        local_path=str(path),
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
        foreign_names = {
            line.strip() for line in foreign_output.splitlines() if line.strip()
        }
        code, output = run_capture([tools.pacman, "-Q"], timeout=30)
        if code == 0:
            items.extend(parse_pacman_installed(output, foreign_names))
        else:
            report(f"pacman installed list exited {code}:\n{output.strip()}")

    if tools.flatpak:
        code, output = run_capture(
            [tools.flatpak, "list", "--app", "--json"], timeout=30
        )
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
