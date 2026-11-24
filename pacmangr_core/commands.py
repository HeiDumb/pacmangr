"""Command-building helpers shared by models and discovery backends."""

from __future__ import annotations

import shutil
from pathlib import Path

from . import constants
from .models import Tools


def detect_extra_managers() -> dict[str, str]:
    managers: dict[str, str] = {}
    for name, spec in constants.MANAGER_SPECS.items():
        if name in constants.CORE_MANAGER_NAMES:
            continue
        commands = tuple(spec.get("commands", ()))
        paths = [shutil.which(str(command)) for command in commands]
        if commands and all(paths):
            managers[name] = str(paths[0])
    return managers


def manager_spec_command(
    manager: str,
    action: str,
    tools: Tools,
    package: str = "",
    query: str = "",
) -> list[str] | None:
    spec = constants.MANAGER_SPECS.get(manager)
    if not spec or action not in spec:
        return None
    template = spec[action]
    if not isinstance(template, tuple):
        return None
    cmd = [str(part).format(package=package, query=query) for part in template]
    if not cmd:
        return None
    resolved = shutil.which(cmd[0])
    if not resolved:
        return None
    cmd[0] = resolved
    if action in {"install", "remove", "update"} and spec.get("privileged"):
        if not tools.privilege:
            return None
        cmd = [tools.privilege] + cmd
    return cmd


def system_update_commands(
    tools: Tools, source: str = "all"
) -> list[tuple[str, list[str]]]:
    """Return native update commands without executing or merging package ecosystems."""
    from .backends import managed_git_checkouts

    commands: list[tuple[str, list[str]]] = []
    if source in {"all", "pacman", "aur"}:
        helper = tools.aur_helper
        if helper:
            name, path = helper
            commands.append((name, [path, "-Syu"]))
        elif tools.pacman and tools.privilege:
            commands.append(("pacman", [tools.privilege, tools.pacman, "-Syu"]))
    if source in {"all", "flatpak"} and tools.flatpak:
        commands.append(("flatpak", [tools.flatpak, "update"]))
    if source in {"all", "apt"} and tools.apt and tools.privilege:
        commands.extend(
            [
                ("apt metadata", [tools.privilege, tools.apt, "update"]),
                ("apt packages", [tools.privilege, tools.apt, "upgrade"]),
            ]
        )
    if source in {"all", "snap"} and tools.snap and tools.privilege:
        commands.append(("snap", [tools.privilege, tools.snap, "refresh"]))
    if source in {"all", "git"} and tools.git:
        for item in managed_git_checkouts(tools):
            commands.append(
                (
                    f"git · {item.name}",
                    [tools.git, "-C", item.package_id, "pull", "--ff-only"],
                )
            )
    for manager in tools.extra_managers:
        if source not in {"all", manager}:
            continue
        cmd = manager_spec_command(manager, "update", tools)
        if cmd:
            commands.append((manager, cmd))
    return commands


def noninteractive_command(command: list[str]) -> list[str]:
    """Add the native assume-yes switch used by scriptable CLI operations."""
    prepared = list(command)
    real_index = 1 if prepared and Path(prepared[0]).name in {"sudo", "doas"} else 0
    if real_index >= len(prepared):
        return prepared
    tool = Path(prepared[real_index]).name
    tail = prepared[real_index + 1 :]
    if tool in {"pacman", "yay", "paru"} and "--noconfirm" not in tail:
        prepared.insert(real_index + 1, "--noconfirm")
    elif tool == "flatpak" and "-y" not in tail:
        prepared.append("-y")
    elif tool in {
        "apt",
        "apt-get",
        "dnf",
        "zypper",
        "xbps-install",
        "xbps-remove",
        "pkg",
    }:
        if "-y" not in tail and "--non-interactive" not in tail:
            prepared.append("--non-interactive" if tool == "zypper" else "-y")
    elif tool == "pip" and "uninstall" in tail and "-y" not in tail:
        prepared.append("-y")
    return prepared
