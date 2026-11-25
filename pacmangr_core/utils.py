"""Small helpers shared across the pacmangr core."""

from __future__ import annotations

import html
import os
import subprocess
from html.parser import HTMLParser

from .constants import ANSI_RE


class _HTMLTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "ol",
        "p",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")
            if tag == "li":
                self.parts.append("• ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text_html(value: object) -> str:
    """Convert HTML markup to readable text while preserving block breaks."""
    parser = _HTMLTextParser()
    parser.feed(html.unescape(str(value or "")))
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


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
