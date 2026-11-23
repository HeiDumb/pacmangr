"""Data models for packages, versions and download jobs."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import constants
from .commands import detect_extra_managers, manager_spec_command


@dataclass
class Tools:
    pacman: str | None
    yay: str | None
    paru: str | None
    flatpak: str | None
    pacseek: str | None
    downgrade: str | None
    apt: str | None
    apt_cache: str | None
    dpkg_query: str | None
    snap: str | None
    sudo: str | None
    doas: str | None
    git: str | None
    extra_managers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def detect(cls) -> "Tools":
        return cls(
            pacman=shutil.which("pacman"),
            yay=shutil.which("yay"),
            paru=shutil.which("paru"),
            flatpak=shutil.which("flatpak"),
            pacseek=shutil.which("pacseek"),
            downgrade=shutil.which("downgrade"),
            apt=shutil.which("apt"),
            apt_cache=shutil.which("apt-cache"),
            dpkg_query=shutil.which("dpkg-query"),
            snap=shutil.which("snap"),
            sudo=shutil.which("sudo"),
            doas=shutil.which("doas"),
            git=shutil.which("git"),
            extra_managers=detect_extra_managers(),
        )

    @property
    def privilege(self) -> str | None:
        return self.sudo or self.doas

    @property
    def aur_helper(self) -> tuple[str, str] | None:
        if self.yay:
            return ("yay", self.yay)
        if self.paru:
            return ("paru", self.paru)
        return None

    def enabled_labels(self) -> str:
        labels = []
        for label in ("pacman", "yay", "paru", "flatpak", "apt", "dpkg_query", "snap", "git", "pacseek", "downgrade"):
            if getattr(self, label):
                labels.append("dpkg" if label == "dpkg_query" else label)
        labels.extend(name for name in self.extra_managers if name not in labels)
        return ", ".join(labels) if labels else "none"


@dataclass
class PackageItem:
    source: str
    manager: str
    name: str
    package_id: str
    version: str = ""
    description: str = ""
    repo: str = ""
    installed: bool = False
    origin: str = ""

    def title(self) -> str:
        if self.source == "flatpak" and self.name != self.package_id:
            return f"{self.name} ({self.package_id})"
        if self.source == "appimage":
            return f"{self.name} ({self.package_id})"
        return self.name

    def install_command(self, tools: Tools, install_scope: str = "user") -> list[str] | None:
        if self.source == "git":
            if not tools.git or not self.origin:
                return None
            target = Path(self.package_id)
            if (target / ".git").is_dir():
                return [tools.git, "-C", str(target), "pull", "--ff-only"]
            return [sys.executable, str(constants.CLI_ENTRY_PATH), "_git-fetch", self.origin, str(target)]
        if self.source == "pip" or self.manager == "pip":
            if install_scope not in {"venv", "user", "system"}:
                return None
            helper = [sys.executable, str(constants.CLI_ENTRY_PATH), "_pip-install", install_scope, self.package_id]
            if install_scope == "system":
                return [tools.privilege, *helper] if tools.privilege else None
            return helper
        if self.source == "flatpak":
            if not tools.flatpak:
                return None
            remote = self.origin.split(",")[0].strip() or "flathub"
            return [tools.flatpak, "install", remote, self.package_id]
        if self.source == "apt":
            if tools.apt and tools.privilege:
                return [tools.privilege, tools.apt, "install", self.package_id]
            return None
        if self.source == "snap":
            if tools.snap and tools.privilege:
                return [tools.privilege, tools.snap, "install", self.package_id]
            return None
        if self.source == "appimage":
            return None
        generic = manager_spec_command(self.source, "install", tools, package=self.package_id)
        if generic:
            return generic

        if self.manager == "yay" and tools.yay:
            return [tools.yay, "-S", self.package_id]
        if self.manager == "paru" and tools.paru:
            return [tools.paru, "-S", self.package_id]
        if tools.pacman and tools.privilege:
            return [tools.privilege, tools.pacman, "-S", self.package_id]
        return None

    def remove_command(self, tools: Tools) -> list[str] | None:
        if (self.source == "pip" or self.manager == "pip") and self.origin.startswith("venv:"):
            target = Path(self.origin.removeprefix("venv:"))
            gio = shutil.which("gio")
            return [gio, "trash", str(target)] if gio else None
        if self.source == "git":
            return None
        if self.source == "flatpak":
            if tools.flatpak:
                return [tools.flatpak, "uninstall", self.package_id]
            return None
        if self.source == "apt":
            if tools.apt and tools.privilege:
                return [tools.privilege, tools.apt, "remove", self.package_id]
            return None
        if self.source == "snap":
            if tools.snap and tools.privilege:
                return [tools.privilege, tools.snap, "remove", self.package_id]
            return None
        if self.source == "appimage":
            rm = shutil.which("rm") or "/usr/bin/rm"
            return [rm, "-v", self.package_id]
        generic = manager_spec_command(self.source, "remove", tools, package=self.package_id)
        if generic:
            return generic
        if tools.pacman and tools.privilege:
            return [tools.privilege, tools.pacman, "-Rns", self.package_id]
        return None

    def info_command(self, tools: Tools, installed_view: bool) -> list[str] | None:
        if (self.source == "pip" or self.manager == "pip") and self.origin.startswith("venv:"):
            target = Path(self.origin.removeprefix("venv:"))
            python = target / "bin/python"
            return [str(python), "-m", "pip", "show", self.package_id] if python.is_file() else None
        if self.source == "git":
            if not tools.git:
                return None
            target = Path(self.package_id)
            if (target / ".git").is_dir():
                return [tools.git, "-C", str(target), "log", "-1", "--decorate", "--stat"]
            return [tools.git, "ls-remote", "--symref", self.origin, "HEAD"]
        if self.source == "flatpak":
            if not tools.flatpak:
                return None
            if installed_view or self.installed:
                return [tools.flatpak, "info", self.package_id]
            remote = self.origin.split(",")[0].strip() or "flathub"
            return [tools.flatpak, "remote-info", remote, self.package_id]
        if self.source == "apt":
            if installed_view or self.installed:
                if tools.dpkg_query:
                    return [tools.dpkg_query, "-s", self.package_id]
            if tools.apt:
                return [tools.apt, "show", self.package_id]
            return None
        if self.source == "snap":
            if tools.snap:
                return [tools.snap, "info", self.package_id]
            return None
        if self.source == "appimage":
            return None
        generic = manager_spec_command(self.source, "info", tools, package=self.package_id)
        if generic:
            return generic

        if installed_view or self.installed:
            if tools.pacman:
                return [tools.pacman, "-Qi", self.package_id]
            return None

        if self.manager == "yay" and tools.yay:
            return [tools.yay, "-Si", self.package_id]
        if self.manager == "paru" and tools.paru:
            return [tools.paru, "-Si", self.package_id]
        if tools.pacman:
            return [tools.pacman, "-Si", self.package_id]
        return None


@dataclass
class PackageVersion:
    package: str
    version: str
    manager: str
    origin: str = ""
    location: str = ""
    installed: bool = False


@dataclass
class DownloadJob:
    id: int
    label: str
    cmd: list[str]
    status: str = "queued"
    started: float | None = None
    finished: float | None = None
    code: int | None = None
    progress: str = ""
    speed: str = ""
    eta: str = ""
    last_line: str = ""
    lines: list[str] = field(default_factory=list)


def package_key(item: PackageItem) -> tuple[str, str, str]:
    source = "aur" if item.source == "aur/local" else item.source
    manager = "arch" if source in {"pacman", "aur"} else item.manager
    return (source, manager, item.package_id)


def package_to_dict(item: PackageItem) -> dict[str, object]:
    return {
        "source": item.source,
        "manager": item.manager,
        "name": item.name,
        "package_id": item.package_id,
        "version": item.version,
        "description": item.description,
        "repo": item.repo,
        "installed": item.installed,
        "origin": item.origin,
    }


def package_from_dict(data: dict[str, object]) -> PackageItem:
    return PackageItem(
        source=str(data.get("source") or ""),
        manager=str(data.get("manager") or ""),
        name=str(data.get("name") or ""),
        package_id=str(data.get("package_id") or data.get("name") or ""),
        version=str(data.get("version") or ""),
        description=str(data.get("description") or ""),
        repo=str(data.get("repo") or ""),
        installed=bool(data.get("installed")),
        origin=str(data.get("origin") or ""),
    )


def version_to_dict(item: PackageVersion) -> dict[str, object]:
    return {
        "package": item.package,
        "version": item.version,
        "manager": item.manager,
        "origin": item.origin,
        "location": item.location,
        "installed": item.installed,
    }


def version_from_dict(data: dict[str, object]) -> PackageVersion:
    return PackageVersion(
        package=str(data.get("package") or ""),
        version=str(data.get("version") or ""),
        manager=str(data.get("manager") or ""),
        origin=str(data.get("origin") or ""),
        location=str(data.get("location") or ""),
        installed=bool(data.get("installed")),
    )
