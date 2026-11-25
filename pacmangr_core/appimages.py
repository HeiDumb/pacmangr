"""Runtime helpers for making and launching AppImages without extra launchers."""

from __future__ import annotations

import ctypes.util
import hashlib
import os
import re
import stat
from pathlib import Path


def make_executable(path: str | Path) -> Path:
    """Ensure the current user can execute an AppImage, preserving other modes."""
    appimage = Path(path).expanduser()
    if not appimage.is_file():
        raise FileNotFoundError(f"AppImage file not found: {appimage}")
    if os.access(appimage, os.R_OK | os.X_OK):
        return appimage

    mode = stat.S_IMODE(appimage.stat().st_mode)
    appimage.chmod(mode | stat.S_IRUSR | stat.S_IXUSR)
    if not os.access(appimage, os.R_OK | os.X_OK):
        raise PermissionError(f"AppImage is not executable: {appimage}")
    return appimage


def launch_arguments(path: str | Path) -> list[str]:
    """Use AppImage's extract-and-run mode when FUSE cannot be used."""
    appimage = str(path)
    fuse_available = ctypes.util.find_library("fuse") and os.access(
        "/dev/fuse", os.R_OK | os.W_OK
    )
    if not fuse_available:
        return [appimage, "--appimage-extract-and-run"]
    return [appimage]


def launch_environment() -> dict[str, str]:
    """Prevent AppImageLauncher from replacing Pacmangr's run action with a prompt."""
    environment = os.environ.copy()
    environment["APPIMAGELAUNCHER_DISABLE"] = "1"
    return environment


def _integration_id(path: Path) -> str:
    resolved = str(path.resolve())
    slug = re.sub(r"[^a-z0-9]+", "-", path.stem.casefold()).strip("-") or "appimage"
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:10]
    return f"{slug[:48]}-{digest}"


def _desktop_quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("%", "%%")
    )
    return f'"{escaped}"'


def integrate_appimage(path: str | Path, name: str) -> Path:
    """Add a user desktop launcher for an AppImage without AppImageLauncher."""
    appimage = make_executable(path).resolve()
    desktop_id = _integration_id(appimage)
    desktop_dir = Path.home() / ".local" / "share" / "applications"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = desktop_dir / f"pacmangr-appimage-{desktop_id}.desktop"
    safe_name = " ".join(
        name.replace("\\", "\\\\").replace("\n", " ").replace("\r", " ").split()
    )
    if not safe_name:
        safe_name = appimage.stem
    command = ["env", "APPIMAGELAUNCHER_DISABLE=1", *launch_arguments(appimage), "%U"]
    exec_line = " ".join(
        value if value in {"env", "APPIMAGELAUNCHER_DISABLE=1", "%U"} else _desktop_quote(value)
        for value in command
    )
    contents = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={safe_name}\n"
        f"Exec={exec_line}\n"
        "Icon=application-x-executable\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        "StartupNotify=true\n"
        "X-Pacmangr-AppImage=true\n"
    )
    temporary = desktop_path.with_suffix(".desktop.tmp")
    temporary.write_text(contents, encoding="utf-8")
    temporary.chmod(0o644)
    temporary.replace(desktop_path)
    return desktop_path


def remove_appimage_integration(path: str | Path) -> None:
    appimage = Path(path).expanduser().resolve()
    desktop_id = _integration_id(appimage)
    desktop_path = (
        Path.home()
        / ".local"
        / "share"
        / "applications"
        / f"pacmangr-appimage-{desktop_id}.desktop"
    )
    desktop_path.unlink(missing_ok=True)
