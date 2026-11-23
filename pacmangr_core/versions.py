"""Version discovery, comparison and formatting helpers."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .models import PackageItem, PackageVersion, Tools
from .parsers import parse_key_value_block
from .utils import run_capture, strip_ansi


def parse_package_file_version(package: str, path: Path, arch: str = "") -> str:
    name = path.name
    if not name.startswith(f"{package}-"):
        return ""
    name = re.sub(r"\.(git)?pkg(\.tar)?\.[A-Za-z0-9]+$", "", name)
    version_arch = name[len(package) + 1 :]
    if not re.match(r"^\d", version_arch):
        return ""
    parts = version_arch.rsplit("-", 1)
    if len(parts) != 2:
        return version_arch
    version, file_arch = parts
    known_arches = {arch, "any", "x86_64", "aarch64", "armv7h", "i686"}
    return version if file_arch in known_arches else version_arch


def version_sort_key(version: str) -> list[tuple[int, object]]:
    parts: list[tuple[int, object]] = []
    for part in re.split(r"([0-9]+)", version.lower()):
        if not part:
            continue
        parts.append((0, int(part)) if part.isdigit() else (1, part))
    return parts


def dedupe_versions(versions: list[PackageVersion]) -> list[PackageVersion]:
    merged: dict[str, PackageVersion] = {}
    for item in versions:
        if not item.version:
            continue
        existing = merged.get(item.version)
        if not existing:
            merged[item.version] = item
            continue
        existing.installed = existing.installed or item.installed
        managers = existing.manager.split("/")
        if item.manager and item.manager not in managers:
            existing.manager = f"{existing.manager}/{item.manager}" if existing.manager else item.manager
        origins = [origin.strip() for origin in existing.origin.split(",") if origin.strip()]
        if item.origin and item.origin not in origins:
            existing.origin = ", ".join([*origins, item.origin])
        if not existing.location and item.location:
            existing.location = item.location
    deduped = list(merged.values())
    return sorted(
        deduped,
        key=lambda item: (item.installed, version_sort_key(item.version), item.origin),
        reverse=True,
    )


def pacman_architecture() -> str:
    pacman_conf = shutil.which("pacman-conf")
    if not pacman_conf:
        return ""
    code, output = run_capture([pacman_conf, "Architecture"], timeout=10)
    if code == 0:
        return output.splitlines()[0].strip()
    return ""


def pacman_cache_dirs() -> list[Path]:
    paths: list[Path] = []
    pacman_conf = shutil.which("pacman-conf")
    if pacman_conf:
        code, output = run_capture([pacman_conf, "CacheDir"], timeout=10)
        if code == 0:
            paths.extend(Path(line.strip()) for line in output.splitlines() if line.strip())
    paths.append(Path("/var/cache/pacman/pkg"))
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    paths.extend([cache_home / "yay", cache_home / "paru" / "clone"])
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def package_files_for(package: str, roots: list[Path], max_depth: int = 4) -> list[Path]:
    matches: list[Path] = []
    for root in roots:
        try:
            root_depth = len(root.parts)
            for dirpath, dirnames, filenames in os.walk(root):
                path = Path(dirpath)
                if len(path.parts) - root_depth >= max_depth:
                    dirnames[:] = []
                for filename in filenames:
                    if filename.endswith(".sig"):
                        continue
                    if filename.startswith(f"{package}-") and ".pkg" in filename:
                        matches.append(path / filename)
        except OSError:
            continue
    return matches


def pacman_log_versions(package: str) -> list[PackageVersion]:
    path = Path("/var/log/pacman.log")
    versions: list[PackageVersion] = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return versions
    escaped = re.escape(package)
    pattern = re.compile(
        rf"\[ALPM\] (?:installed|upgraded|downgraded) {escaped} \((?:(?P<old>[^)]*?) -> )?(?P<new>[^)]*)\)"
    )
    for line in lines:
        match = pattern.search(line)
        if not match:
            continue
        for group in ("old", "new"):
            version = (match.group(group) or "").strip()
            if version:
                versions.append(PackageVersion(package, version, "pacman", "pacman.log", str(path)))
    return versions


def downgrade_remote_versions(tools: Tools, package: str) -> list[PackageVersion]:
    if not tools.downgrade:
        return []

    base = [tools.downgrade]
    if tools.sudo:
        # Use an already-unlocked sudo timestamp. Do not prompt inside capture.
        base = [tools.sudo, "-n", tools.downgrade]

    commands = [
        [*base, "--ala-only", "--latest", "200", package],
        [*base, "--latest", "200", package],
        [*base, package],
    ]

    versions: list[PackageVersion] = []
    arch = pacman_architecture()

    for cmd in commands:
        code, output = run_capture(cmd, timeout=12)

        # downgrade may wait for interactive selection. run_capture returns timeout output,
        # and that output can still contain the version list, so parse code 124 too.
        if code not in (0, 1, 124):
            continue

        for raw in output.splitlines():
            line = strip_ansi(raw).strip()
            if not line:
                continue

            lowered = line.lower()
            if any(skip in lowered for skip in (
                "select a package",
                "warning:",
                "loading",
                "available packages",
                "add packages",
                "there is nothing",
                "unable to",
                "error:",
            )):
                continue

            # Remove common menu prefixes: "1)", "1.", "[1]"
            line = re.sub(r"^\s*(?:\[\d+\]|\d+\)|\d+\.)\s*", "", line)

            found = ""

            # Case: /path/hyprland-0.55.3-1-x86_64.pkg.tar.zst
            for token in re.split(r"\s+", line):
                cleaned = token.strip("[](){}<>,;:")
                if package in cleaned and ".pkg" in cleaned:
                    parsed = parse_package_file_version(package, Path(cleaned), arch)
                    if parsed:
                        found = parsed
                        break

            # Case: hyprland-0.55.3-1-x86_64 or hyprland-0.55.3-1-any
            if not found:
                pattern = re.compile(
                    rf"{re.escape(package)}-([0-9][A-Za-z0-9_.:+~\-]*?)(?:-(?:{re.escape(arch)}|x86_64|aarch64|armv7h|i686|any))?(?:\s|$|\)|\])"
                )
                match = pattern.search(line)
                if match:
                    found = match.group(1).strip()

            # Case: "0.55.3-1 remote" after menu number was stripped
            if not found:
                parts = line.split()
                if parts and re.match(r"^[0-9][A-Za-z0-9_.:+~\-]*$", parts[0]):
                    found = parts[0].strip()

            if found:
                versions.append(PackageVersion(package, found, "downgrade", "ALA remote"))

        if versions:
            break

    return versions


def arch_versions_for(tools: Tools, item: PackageItem) -> list[PackageVersion]:
    package = item.package_id
    versions: list[PackageVersion] = []
    if item.version:
        versions.append(PackageVersion(package, item.version, item.manager, "shown result", installed=item.installed))
    if tools.pacman:
        code, output = run_capture([tools.pacman, "-Qi", package], timeout=20)
        if code == 0:
            data = parse_key_value_block(output)
            version = data.get("version", "")
            if version:
                versions.append(PackageVersion(package, version, "pacman", "installed", installed=True))
        code, output = run_capture([tools.pacman, "-Si", package], timeout=30)
        if code == 0:
            data = parse_key_value_block(output)
            version = data.get("version", "")
            repo = data.get("repository", "repo")
            if version:
                versions.append(PackageVersion(package, version, "pacman", repo))
    helper_path = tools.yay if item.manager == "yay" else tools.paru if item.manager == "paru" else None
    if helper_path:
        code, output = run_capture([helper_path, "-Si", package], timeout=40)
        if code == 0:
            data = parse_key_value_block(output)
            version = data.get("version", "")
            if version:
                versions.append(PackageVersion(package, version, item.manager, "aur"))
    arch = pacman_architecture()
    for path in package_files_for(package, pacman_cache_dirs()):
        version = parse_package_file_version(package, path, arch)
        if version:
            versions.append(PackageVersion(package, version, "downgrade", "local cache", str(path)))
    versions.extend(pacman_log_versions(package))
    versions.extend(downgrade_remote_versions(tools, package))
    return dedupe_versions(versions)


def apt_versions_for(tools: Tools, item: PackageItem) -> list[PackageVersion]:
    if not tools.apt_cache:
        return dedupe_versions([
            PackageVersion(item.package_id, item.version, item.manager, "shown result", installed=item.installed)
        ])
    versions = [
        PackageVersion(item.package_id, item.version, item.manager, "shown result", installed=item.installed)
    ] if item.version else []
    code, output = run_capture([tools.apt_cache, "policy", item.package_id], timeout=30)
    if code == 0:
        for line in output.splitlines():
            stripped = line.strip().lstrip("*").strip()
            if re.match(r"^[0-9][^\s]*\s+\d+", stripped):
                version = stripped.split()[0]
                versions.append(PackageVersion(item.package_id, version, "apt", "apt policy"))
    return dedupe_versions(versions)


def package_versions(tools: Tools, item: PackageItem) -> list[PackageVersion]:
    if item.source in {"pacman", "aur", "aur/local"} or item.manager in {"pacman", "yay", "paru"}:
        return arch_versions_for(tools, item)
    if item.source == "apt":
        return apt_versions_for(tools, item)
    versions = []
    if item.version:
        versions.append(PackageVersion(item.package_id, item.version, item.manager, "shown result", installed=item.installed))
    return dedupe_versions(versions)


def format_versions(package: str, versions: list[PackageVersion]) -> str:
    if not versions:
        return f"No versions found for {package}."
    rows = [f"Versions for {package} ({len(versions)}):"]
    for index, item in enumerate(versions, start=1):
        marker = " installed" if item.installed else ""
        origin = f" [{item.origin}]" if item.origin else ""
        rows.append(f"{index:>2}. {item.version}{marker} - {item.manager}{origin}")
    return "\n".join(rows)
