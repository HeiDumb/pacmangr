"""Small helpers shared across the pacmangr core."""

from __future__ import annotations

import os
import subprocess

from .constants import ANSI_RE


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def run_capture(cmd: list[str], timeout: int = 40) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
    except FileNotFoundError as exc:
        return (127, str(exc))
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return (124, f"Timed out after {timeout}s\n{output}")
    return (proc.returncode, strip_ansi(proc.stdout))


def human_size(size: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024


def clip(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + ">"


def pad(text: str, width: int) -> str:
    if width <= 0:
        return ""
    return clip(text, width - 1).ljust(max(0, width - 1))
