"""Runtime helpers for making and launching AppImages without extra launchers."""

from __future__ import annotations

import ctypes.util
import os
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
