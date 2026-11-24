"""Parsers for the textual output of supported package managers."""

from __future__ import annotations

import json
import re

from . import constants
from .constants import (
    CARGO_SEARCH_RE,
    MAX_RESULTS,
    PACMAN_INFO_RE,
    PIP_INDEX_RE,
    PKG_HEADER_RE,
)
from .models import PackageItem


def parse_key_value_block(output: str) -> dict[str, str]:
    data: dict[str, str] = {}
    current = ""
    for raw in output.splitlines():
        if not raw.strip():
            current = ""
            continue
        match = PACMAN_INFO_RE.match(raw)
        if match:
            current = match.group(1).strip().lower()
            data[current] = match.group(2).strip()
        elif current:
            data[current] = f"{data[current]} {raw.strip()}".strip()
    return data


def parse_arch_search(
    output: str,
    manager: str,
    installed_names: set[str],
    source_override: str | None = None,
) -> list[PackageItem]:
    items: list[PackageItem] = []
    current: PackageItem | None = None

    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue

        match = PKG_HEADER_RE.match(line)
        if match:
            repo, name, version, rest = match.groups()
            source = source_override or ("aur" if repo == "aur" else "pacman")
            installed = name in installed_names or "installed" in rest.lower()
            current = PackageItem(
                source=source,
                manager=manager,
                repo=repo,
                name=name,
                package_id=name,
                version=version,
                installed=installed,
            )
            items.append(current)
            continue

        if current and line.startswith(" "):
            desc = line.strip()
            if desc:
                current.description = desc

    return items


def parse_pacman_installed(output: str, foreign_names: set[str]) -> list[PackageItem]:
    items: list[PackageItem] = []
    for line in output.splitlines():
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        name = parts[0]
        version = parts[1] if len(parts) > 1 else ""
        source = "aur/local" if name in foreign_names else "pacman"
        items.append(
            PackageItem(
                source=source,
                manager="pacman",
                name=name,
                package_id=name,
                version=version,
                installed=True,
            )
        )
    return items


def parse_flatpak_search(output: str, installed_ids: set[str]) -> list[PackageItem]:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []

    items: list[PackageItem] = []
    for entry in data:
        package_id = entry.get("application_id") or entry.get("ref") or ""
        if not package_id:
            continue
        items.append(
            PackageItem(
                source="flatpak",
                manager="flatpak",
                repo="flatpak",
                name=entry.get("name") or package_id,
                package_id=package_id,
                version=entry.get("version") or "",
                description=entry.get("description") or "",
                installed=package_id in installed_ids,
                origin=entry.get("remotes") or "flathub",
            )
        )
    return items


def parse_flatpak_installed(output: str) -> list[PackageItem]:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []

    items: list[PackageItem] = []
    for entry in data:
        package_id = entry.get("application_id") or entry.get("ref") or ""
        if not package_id:
            continue
        items.append(
            PackageItem(
                source="flatpak",
                manager="flatpak",
                repo=entry.get("origin") or "flatpak",
                name=entry.get("name") or package_id,
                package_id=package_id,
                version=entry.get("version") or "",
                installed=True,
                origin=entry.get("origin") or "flathub",
                description=f"installation: {entry.get('installation') or 'unknown'}",
            )
        )
    return items


def parse_apt_search(output: str, installed_names: set[str]) -> list[PackageItem]:
    items: list[PackageItem] = []
    for line in output.splitlines():
        if " - " not in line:
            continue
        name, description = line.split(" - ", 1)
        name = name.strip()
        if not name or " " in name:
            continue
        items.append(
            PackageItem(
                source="apt",
                manager="apt",
                repo="apt",
                name=name,
                package_id=name,
                description=description.strip(),
                installed=name in installed_names,
            )
        )
    return items


def parse_apt_installed(output: str) -> list[PackageItem]:
    items: list[PackageItem] = []
    for line in output.splitlines():
        parts = line.split("\t", 3)
        if len(parts) < 3:
            continue
        name, version, status = parts[:3]
        if not status.startswith("ii"):
            continue
        description = parts[3].strip() if len(parts) > 3 else ""
        items.append(
            PackageItem(
                source="apt",
                manager="apt",
                repo="dpkg",
                name=name,
                package_id=name,
                version=version,
                description=description,
                installed=True,
            )
        )
    return items


def parse_snap_search(output: str, installed_names: set[str]) -> list[PackageItem]:
    items: list[PackageItem] = []
    for index, line in enumerate(output.splitlines()):
        if index == 0 and line.lower().startswith("name"):
            continue
        parts = line.split(None, 4)
        if len(parts) < 2:
            continue
        name = parts[0]
        version = parts[1]
        description = parts[4] if len(parts) > 4 else ""
        items.append(
            PackageItem(
                source="snap",
                manager="snap",
                repo="snap",
                name=name,
                package_id=name,
                version=version,
                description=description,
                installed=name in installed_names,
            )
        )
    return items


def parse_snap_installed(output: str) -> list[PackageItem]:
    items: list[PackageItem] = []
    for index, line in enumerate(output.splitlines()):
        if index == 0 and line.lower().startswith("name"):
            continue
        parts = line.split(None, 5)
        if len(parts) < 2:
            continue
        name = parts[0]
        version = parts[1]
        publisher = parts[4] if len(parts) > 4 else ""
        notes = parts[5] if len(parts) > 5 else ""
        description = " ".join(part for part in (publisher, notes) if part)
        items.append(
            PackageItem(
                source="snap",
                manager="snap",
                repo="snap",
                name=name,
                package_id=name,
                version=version,
                description=description,
                installed=True,
            )
        )
    return items


def parse_cargo_search(output: str, installed_names: set[str]) -> list[PackageItem]:
    items: list[PackageItem] = []
    for line in output.splitlines():
        match = CARGO_SEARCH_RE.match(line.strip())
        if not match:
            continue
        name, version, description = match.groups()
        items.append(
            PackageItem(
                source="cargo",
                manager="cargo",
                repo="crates.io",
                name=name,
                package_id=name,
                version=version,
                description=description or "",
                installed=name in installed_names,
            )
        )
    return items


def parse_cargo_installed(output: str) -> list[PackageItem]:
    items: list[PackageItem] = []
    for line in output.splitlines():
        if not line or line.startswith(" "):
            continue
        parts = line.split()
        if not parts:
            continue
        name = parts[0]
        version = parts[1].rstrip(":") if len(parts) > 1 else ""
        items.append(
            PackageItem(
                source="cargo",
                manager="cargo",
                repo="cargo install",
                name=name,
                package_id=name,
                version=version,
                installed=True,
            )
        )
    return items


def parse_npm_search(output: str, installed_names: set[str]) -> list[PackageItem]:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    items: list[PackageItem] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("sanitized_name") or ""
        if not name:
            continue
        items.append(
            PackageItem(
                source="npm",
                manager="npm",
                repo="npm registry",
                name=name,
                package_id=name,
                version=entry.get("version") or "",
                description=entry.get("description") or "",
                installed=name in installed_names,
            )
        )
    return items


def parse_npm_installed(output: str) -> list[PackageItem]:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []
    dependencies = data.get("dependencies", {}) if isinstance(data, dict) else {}
    items: list[PackageItem] = []
    for name, meta in dependencies.items():
        if not isinstance(meta, dict):
            meta = {}
        items.append(
            PackageItem(
                source="npm",
                manager="npm",
                repo="global npm",
                name=name,
                package_id=name,
                version=meta.get("version") or "",
                installed=True,
            )
        )
    return items


def parse_pip_search(output: str, installed_names: set[str]) -> list[PackageItem]:
    match = PIP_INDEX_RE.search(output)
    if not match:
        return []
    name, version = match.groups()
    installed = name.lower() in {item.lower() for item in installed_names}
    return [
        PackageItem(
            source="pip",
            manager="pip",
            repo="PyPI",
            name=name,
            package_id=name,
            version=version,
            installed=installed,
        )
    ]


def parse_pip_installed(output: str) -> list[PackageItem]:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []
    items: list[PackageItem] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or ""
        if not name:
            continue
        items.append(
            PackageItem(
                source="pip",
                manager="pip",
                repo="pip",
                name=name,
                package_id=name,
                version=entry.get("version") or "",
                installed=True,
            )
        )
    return items


def parse_pipx_installed(output: str) -> list[PackageItem]:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return []
    venvs = data.get("venvs", {}) if isinstance(data, dict) else {}
    items: list[PackageItem] = []
    for name, meta in venvs.items():
        package = (
            meta.get("metadata", {}).get("main_package", {})
            if isinstance(meta, dict)
            else {}
        )
        items.append(
            PackageItem(
                source="pipx",
                manager="pipx",
                repo="pipx",
                name=name,
                package_id=name,
                version=package.get("package_version") or "",
                installed=True,
            )
        )
    return items


def parse_generic_search(
    manager: str, output: str, installed_names: set[str]
) -> list[PackageItem]:
    items: list[PackageItem] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(
            ("Loaded ", "Available ", "Last metadata", "Name ", "====")
        ):
            continue
        name = ""
        version = ""
        description = ""
        if " - " in line:
            left, description = line.split(" - ", 1)
            name = left.split()[0]
        elif " : " in line:
            left, description = line.split(" : ", 1)
            name = left.split()[0].split(".")[0]
        elif "/" in line and manager == "zypper":
            parts = [part.strip() for part in line.split("|")]
            if len(parts) >= 3 and parts[1] and parts[1] != "Name":
                name = parts[1]
                version = parts[3] if len(parts) > 3 else ""
        else:
            parts = line.split()
            if parts:
                name = parts[0].lstrip("[-*>=~")
                if len(parts) > 1 and re.match(r"^[0-9][A-Za-z0-9_.:+~-]*$", parts[1]):
                    version = parts[1]
        name = name.strip("|,;:")
        if not name or name.lower() in {"name", "package", "installed", "available"}:
            continue
        items.append(
            PackageItem(
                source=manager,
                manager=manager,
                repo=manager,
                name=name,
                package_id=name,
                version=version,
                description=description.strip(),
                installed=name in installed_names,
            )
        )
    return items[:MAX_RESULTS]


def parse_generic_installed(manager: str, output: str) -> list[PackageItem]:
    items: list[PackageItem] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("Name ", "Installed", "Listing", "====")):
            continue
        if "|" in line and manager == "zypper":
            parts = [part.strip() for part in line.split("|")]
            if len(parts) >= 3 and parts[1] and parts[1] != "Name":
                items.append(
                    PackageItem(
                        source=manager,
                        manager=manager,
                        repo=manager,
                        name=parts[1],
                        package_id=parts[1],
                        version=parts[3] if len(parts) > 3 else "",
                        installed=True,
                    )
                )
            continue
        parts = line.split()
        if not parts:
            continue
        name = parts[0].lstrip("[-*>=~")
        version = ""
        if len(parts) > 1 and re.match(r"^[0-9][A-Za-z0-9_.:+~-]*$", parts[1]):
            version = parts[1].rstrip(":")
        if not name or name.lower() in {"name", "package"}:
            continue
        items.append(
            PackageItem(
                source=manager,
                manager=manager,
                repo=manager,
                name=name,
                package_id=name,
                version=version,
                installed=True,
            )
        )
    return items


def parse_manager_search(
    manager: str, output: str, installed_names: set[str]
) -> list[PackageItem]:
    parser = constants.MANAGER_SPECS.get(manager, {}).get("parser")
    if parser == "cargo":
        return parse_cargo_search(output, installed_names)
    if parser == "npm":
        return parse_npm_search(output, installed_names)
    if parser == "pip":
        return parse_pip_search(output, installed_names)
    return parse_generic_search(manager, output, installed_names)


def parse_manager_installed(manager: str, output: str) -> list[PackageItem]:
    parser = constants.MANAGER_SPECS.get(manager, {}).get("parser")
    if parser == "cargo":
        return parse_cargo_installed(output)
    if parser == "npm":
        return parse_npm_installed(output)
    if parser == "pip":
        return parse_pip_installed(output)
    if parser == "pipx":
        return parse_pipx_installed(output)
    return parse_generic_installed(manager, output)
