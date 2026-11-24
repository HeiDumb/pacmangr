"""Command preparation, streaming runners and package-operation helpers."""

# ruff: noqa: E402

from __future__ import annotations

import fcntl
import html
import json
import math
import os
import pty
import re
import select
import shlex
import shutil
import signal
import struct
import subprocess
import termios
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import GLib, Gtk

from .core_loader import CORE
from .settings import SETTINGS
from .theme import hex_rgb, pacman_frame

# Set by prepare_single_auth_update() when sudo's cached timestamp is missing.
SINGLE_AUTH_NEEDS_PASSWORD = False


def prepare_gui_operation(
    command: list[str],
    tools,
    action: str,
    pkexec: str | None,
) -> list[str]:
    """Make a package command non-interactive and GUI-authenticated."""
    if not command:
        raise RuntimeError("The package manager returned an empty command.")

    argv = list(command)
    privilege_tools = {path for path in (tools.sudo, tools.doas) if path}
    if argv[0] in privilege_tools:
        if not pkexec:
            raise RuntimeError("Graphical authentication needs polkit (pkexec).")
        argv = [pkexec, *argv[1:]]

    executable_index = 1 if pkexec and argv[0] == pkexec else 0
    executable = Path(argv[executable_index]).name
    operation_index = executable_index + 1
    operation = argv[operation_index] if len(argv) > operation_index else ""

    if executable in {"yay", "paru"}:
        if not pkexec:
            raise RuntimeError("AUR installation needs polkit (pkexec).")
        argv[executable_index + 1 : executable_index + 1] = ["--sudo", pkexec]

    flags: list[str] = []
    if executable in {"pacman", "yay", "paru"}:
        flags = ["--noconfirm"]
        if action == "install":
            flags.append("--needed")
    elif executable == "flatpak":
        flags = ["--noninteractive", "-y"]
    elif executable == "apt":
        flags = ["-y"]
    elif executable in {"dnf", "xbps-install", "xbps-remove", "eopkg"}:
        flags = ["-y"]
    elif executable == "zypper":
        flags = ["--non-interactive"]

    if flags:
        operation_index = argv.index(operation, executable_index + 1)
        argv[operation_index + 1 : operation_index + 1] = [
            flag for flag in flags if flag not in argv
        ]
    return argv


def ensure_graphical_auth_agent() -> bool:
    """Start an installed desktop polkit agent when the session has none."""
    agent_names = (
        "polkit-gnome-authentication-agent-1",
        "polkit-kde-authentication-agent-1",
        "lxqt-policykit-agent",
        "hyprpolkitagent",
    )
    for name in agent_names:
        result = subprocess.run(
            ["pgrep", "-f", f"(^|/){name}( |$)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return True

    candidates = (
        "/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1",
        "/usr/lib/polkit-kde-authentication-agent-1",
        "/usr/lib/lxqt-policykit-agent",
        "/usr/lib/hyprpolkitagent/hyprpolkitagent",
    )
    for candidate in candidates:
        if not Path(candidate).is_file():
            continue
        try:
            subprocess.Popen(
                [candidate],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            continue
        return True
    return False


def parse_operation_progress(raw_line: str) -> tuple[str, int | None, str, str]:
    """Extract displayable progress from native package-manager output."""
    line = CORE.strip_ansi(raw_line).replace("\b", "").strip()
    if not line:
        return "", None, "", ""
    percentages = CORE.PERCENT_RE.findall(line)
    speeds = CORE.SPEED_RE.findall(line)
    etas = CORE.ETA_RE.findall(line)
    percent = int(percentages[-1]) if percentages else None
    speed = speeds[-1] if speeds else ""
    eta = etas[-1] if etas and ("eta" in line.lower() or speed) else ""
    return line, percent, speed, eta


def format_eta(seconds: float) -> str:
    """Format an estimated duration compactly for the progress bar."""
    remaining = max(0, int(round(seconds)))
    hours, remainder = divmod(remaining, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def run_streamed_operation(
    argv: list[str],
    env: dict[str, str],
    on_line,
    timeout: float = 1800,
    cancel_event: threading.Event | None = None,
) -> tuple[int, str]:
    """Run against a pseudo-terminal so native progress bars remain visible."""
    master_fd, slave_fd = pty.openpty()
    try:
        # Native package managers hide their download meters when stdout is not
        # a terminal. A stable width keeps percentage, speed, and ETA together.
        fcntl.ioctl(
            slave_fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", 24, 120, 0, 0),
        )
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=slave_fd,
            stderr=slave_fd,
            text=False,
            bufsize=0,
            env=env,
            start_new_session=True,
        )
    except Exception:
        os.close(master_fd)
        os.close(slave_fd)
        raise
    else:
        os.close(slave_fd)

    started = time.monotonic()
    buffer = ""
    lines: list[str] = []
    timed_out = False
    cancelled = False
    cancel_started = 0.0
    cancel_signal_stage = 0

    def signal_group(signal_number: int) -> None:
        try:
            os.killpg(process.pid, signal_number)
        except OSError:
            try:
                process.send_signal(signal_number)
            except OSError:
                pass

    try:
        while True:
            if cancel_event and cancel_event.is_set() and not cancelled:
                cancelled = True
                cancel_started = time.monotonic()
                signal_group(signal.SIGINT)
                cancel_signal_stage = 1
            if cancelled and process.poll() is None:
                elapsed = time.monotonic() - cancel_started
                if elapsed >= 3.0 and cancel_signal_stage == 1:
                    signal_group(signal.SIGTERM)
                    cancel_signal_stage = 2
                if elapsed >= 5.0 and cancel_signal_stage == 2:
                    signal_group(signal.SIGKILL)
                    cancel_signal_stage = 3
            if time.monotonic() - started >= timeout:
                timed_out = True
                signal_group(signal.SIGKILL)
                break

            ready, _, _ = select.select([master_fd], [], [], 0.20)
            if not ready:
                if process.poll() is not None:
                    break
                continue

            try:
                chunk = os.read(master_fd, 4096)
            except OSError:
                break
            if not chunk:
                if process.poll() is not None:
                    break
                time.sleep(0.20)
                continue

            for character in chunk.decode(errors="replace"):
                if character in "\r\n":
                    line = buffer.strip("\r\n")
                    buffer = ""
                    if not line:
                        continue
                    lines.append(line)
                    lines = lines[-2000:]
                    on_line(line)
                else:
                    buffer += character
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass

    if buffer.strip():
        lines.append(buffer.strip())
        on_line(buffer.strip())
    code = process.wait()
    if timed_out:
        timeout_line = "Operation timed out after 30 minutes."
        lines.append(timeout_line)
        on_line(timeout_line)
        code = 124
    if cancelled:
        cancel_line = "Operation cancelled by user."
        lines.append(cancel_line)
        on_line(cancel_line)
        code = 130
    return code, "\n".join(lines)


def operation_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.update({"DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C"})
    env.setdefault("TERM", "xterm-256color")
    return env


# ---------------------------------------------------------------------------
# Single-authentication update flow
# ---------------------------------------------------------------------------
def _privilege_paths(tools) -> set[str]:
    return {
        path
        for path in (getattr(tools, "sudo", None), getattr(tools, "doas", None))
        if path
    }


def _strip_privilege(command: list[str], tools) -> list[str]:
    argv = list(command)
    privileged = _privilege_paths(tools)
    pkexec = shutil.which("pkexec")
    while argv and (argv[0] in privileged or argv[0] == pkexec):
        argv = argv[1:]
    return argv


def _strip_aur_delegation(argv: list[str]) -> list[str]:
    """Remove ``--sudo <pkexec>`` pairs injected for per-command AUR installs."""
    result: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] == "--sudo" and index + 1 < len(argv):
            index += 2
            continue
        result.append(argv[index])
        index += 1
    return result


def _prepare_root_command(command: list[str], tools) -> list[str] | None:
    """Add native non-interactive flags without adding a second privilege layer."""
    argv = _strip_aur_delegation(_strip_privilege(command, tools))
    if not argv:
        return None
    fake_tools = SimpleNamespace(sudo=None, doas=None)
    try:
        return prepare_gui_operation(argv, fake_tools, "update", None)
    except RuntimeError:
        # AUR helpers require --sudo <privilege> for isolated installs, but we
        # are already inside one privileged shell for update-all.
        executable = Path(argv[0]).name
        if executable in {"yay", "paru"} and "--noconfirm" not in argv:
            argv.insert(1, "--noconfirm")
        return argv


def _sudo_timestamp_valid(sudo: str) -> bool:
    try:
        return (
            subprocess.run(
                [sudo, "-n", "-v"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def prepare_single_auth_update(
    commands: list[tuple[str, list[str]]], tools
) -> list[str] | None:
    """Build ONE privileged invocation that runs every update command.

    ``pkexec`` is preferred because it provides a graphical prompt.  With sudo
    we use ``sudo -n`` so the caller can prime the timestamp once with a
    Gtk.PasswordEntry dialog; either way there is a single authentication.
    """
    global SINGLE_AUTH_NEEDS_PASSWORD
    SINGLE_AUTH_NEEDS_PASSWORD = False
    if not commands:
        return None

    prepared = [
        argv
        for argv in (
            _prepare_root_command(command, tools) for _label, command in commands
        )
        if argv
    ]
    if not prepared:
        return None
    script = " && ".join(shlex.join(argv) for argv in prepared)

    pkexec = shutil.which("pkexec")
    if pkexec:
        return [pkexec, "sh", "-c", script]

    sudo = (
        shutil.which("sudo")
        or getattr(tools, "sudo", None)
        or getattr(tools, "doas", None)
    )
    if sudo:
        SINGLE_AUTH_NEEDS_PASSWORD = not _sudo_timestamp_valid(sudo)
        return [sudo, "-n", "sh", "-c", script]
    return None


def prime_sudo_timestamp(parent=None, sudo: str | None = None) -> bool:
    """Ask for the sudo password exactly once using a Gtk.PasswordEntry."""
    sudo = sudo or shutil.which("sudo") or ""
    if not sudo:
        return False
    if _sudo_timestamp_valid(sudo):
        return True

    from gi.repository import GLib as _GLib

    dialog = Gtk.Window(
        title="Authenticate once",
        modal=True,
        transient_for=parent if isinstance(parent, Gtk.Window) else None,
    )
    dialog.set_default_size(360, 160)
    loop = _GLib.MainLoop()
    result: dict[str, str] = {}

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(18)
    box.set_margin_end(18)
    label = Gtk.Label(
        label="Password for sudo (one prompt updates everything):", xalign=0
    )
    label.set_wrap(True)
    entry = Gtk.PasswordEntry()
    buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    buttons.set_halign(Gtk.Align.END)
    cancel = Gtk.Button(label="Cancel")
    confirm = Gtk.Button(label="Authenticate")
    confirm.add_css_class("suggested-action")
    buttons.append(cancel)
    buttons.append(confirm)
    box.append(label)
    box.append(entry)
    box.append(buttons)
    dialog.set_child(box)

    def quit() -> None:
        dialog.close()
        if loop.is_running():
            loop.quit()

    def on_confirm(_button) -> None:
        result["password"] = entry.get_text()
        quit()

    cancel.connect("clicked", lambda *_: quit())
    confirm.connect("clicked", on_confirm)
    dialog.connect("close-request", lambda *_: quit())
    entry.connect("activate", on_confirm)
    dialog.present()
    loop.run()

    password = result.get("password", "")
    if not password:
        return False
    try:
        process = subprocess.run(
            [sudo, "-S", "-v"],
            input=password + "\n",
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        return process.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        result.clear()


def run_single_auth_update(
    commands: list[tuple[str, list[str]]],
    tools,
    on_line,
    timeout: float = 1800,
) -> tuple[int, str]:
    """Prepare and execute the combined update command."""
    argv = prepare_single_auth_update(commands, tools)
    if not argv:
        return 126, "No graphical authentication (pkexec) or sudo is available."
    return run_streamed_operation(
        argv, operation_environment(), on_line, timeout=timeout
    )


# ---------------------------------------------------------------------------
# Orphans and update counts
# ---------------------------------------------------------------------------
def collect_installed_metadata(
    pacman: str | None = None,
) -> tuple[set[str], set[str], set[str]]:
    """Return (explicit, dependencies, orphans) name sets from pacman."""
    explicit: set[str] = set()
    deps: set[str] = set()
    orphans: set[str] = set()
    pacman = pacman or shutil.which("pacman")
    if not pacman:
        return explicit, deps, orphans
    queries = (
        (["-Qeq"], explicit),
        (["-Qdq"], deps),
        (["-Qtdq"], orphans),
    )
    for args, target in queries:
        try:
            output = subprocess.check_output(
                [pacman, *args],
                text=True,
                timeout=25,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        target.update(line.strip() for line in output.splitlines() if line.strip())
    return explicit, deps, orphans


def orphan_remove_command(orphans, tools) -> list[str]:
    """One pacman command, so orphan cleanup needs only one authentication."""
    names = sorted(set(orphans))
    pacman = (
        getattr(tools, "pacman", None) or shutil.which("pacman") or "/usr/bin/pacman"
    )
    privilege = getattr(tools, "sudo", None) or "/usr/bin/sudo"
    return [privilege, pacman, "-Rns", *names]


def available_update_lines(timeout: float = 25) -> list[str]:
    """Read pending Arch updates without synchronising or changing package state."""
    binary = shutil.which("checkupdates")
    pacman = shutil.which("pacman")
    command = [binary] if binary else ([pacman, "-Qu"] if pacman else [])
    if not command:
        return []
    try:
        output = subprocess.check_output(
            command,
            text=True,
            timeout=timeout,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


# ----------------------------------------------------------------------
# GitHub repository details (README.md instead of native package commands)
# ----------------------------------------------------------------------


def github_repo_slug(source) -> str:
    """Return ``owner/repo`` for a GitHub item, URL, or bare ``owner/repo``."""
    if isinstance(source, str):
        candidates = (source,)
    else:
        candidates = (
            getattr(source, "github_full_name", "") or "",
            getattr(source, "github_html_url", "") or "",
            getattr(source, "origin", "") or "",
            getattr(source, "package_id", "") or "",
        )
    for candidate in candidates:
        text = str(candidate).strip()
        if not text:
            continue
        if text.startswith("git@"):
            match = re.match(r"git@[^:]+:(.+?)(?:\.git)?/?$", text)
            if match and "github" in text.lower():
                text = f"https://github.com/{match.group(1)}"
            else:
                continue
        parsed = urllib.parse.urlparse(text)
        if parsed.scheme and parsed.netloc:
            host = parsed.netloc.lower().split("@")[-1].split(":")[0]
            if host not in {
                "github.com",
                "www.github.com",
                "raw.githubusercontent.com",
            }:
                continue
            parts = [part for part in parsed.path.split("/") if part][:2]
            if len(parts) < 2:
                continue
            text = f"{parts[0]}/{parts[1]}"
        match = re.fullmatch(r"([\w.-]+)/([\w.-]+)", text)
        if match:
            owner, repo = match.groups()
            repo = repo[:-4] if repo.endswith(".git") else repo
            if owner and repo:
                return f"{owner}/{repo}"
    return ""


def resolve_github_default_branch(source, timeout: float = 15) -> str:
    """Best-effort default branch lookup for a GitHub repository."""
    slug = github_repo_slug(source)
    if not slug:
        return ""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{slug}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Pacmangr-GUI"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
        branch = payload.get("default_branch") if isinstance(payload, dict) else ""
        return str(branch).strip() if branch else ""
    except Exception:
        return ""


MAX_GITHUB_README_BYTES = 2 * 1024 * 1024


def _read_github_readme_response(response) -> str:
    data = response.read(MAX_GITHUB_README_BYTES + 1)
    truncated = len(data) > MAX_GITHUB_README_BYTES
    text = data[:MAX_GITHUB_README_BYTES].decode("utf-8", "replace")
    if truncated:
        text += "\n\n> README preview truncated at 2 MiB."
    return text


def _format_readme_markdown(text: str) -> str:
    """Render common Markdown structure as readable text for the detail pane."""
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.DOTALL)
    output: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            if in_code:
                output.append("")
            in_code = not in_code
            continue
        if in_code:
            output.append(f"    {line}")
            continue

        line = re.sub(r"<((?:https?://)[^>]+)>", r"\1", line)
        line = re.sub(r"<br\s*/?>", " ", line, flags=re.IGNORECASE)
        line = re.sub(
            r"</(?:p|div|summary|li|tr|h[1-6])\s*>", " ", line, flags=re.IGNORECASE
        )

        def image_label(match: re.Match) -> str:
            alt = re.search(
                r"\balt\s*=\s*(['\"])(.*?)\1", match.group(0), re.IGNORECASE
            )
            return f"[image: {alt.group(2)}]" if alt and alt.group(2).strip() else ""

        line = re.sub(r"<img\b[^>]*>", image_label, line, flags=re.IGNORECASE)
        line = re.sub(
            r"</?(?:details|summary|p|div|span|sub|sup|kbd|strong|em|table|thead|tbody|tr|th|td)\b[^>]*>",
            "",
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(r"<[^>]+>", "", line)
        line = html.unescape(line)

        heading = re.match(r"^\s{0,3}#{1,6}\s+(.*)$", line)
        if heading:
            title = re.sub(r"[*_`]", "", heading.group(1)).strip()
            output.extend(("", title, "─" * min(max(len(title), 8), 64), ""))
            continue

        table_cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(table_cells) > 1:
            if all(
                re.fullmatch(r":?-{3,}:?", cell.replace(" ", ""))
                for cell in table_cells
            ):
                continue
            line = "  │  ".join(table_cells)

        cleaned = re.sub(
            r"!\[([^]]*)\]\([^)]*\)",
            lambda m: f"[image: {m.group(1)}]" if m.group(1) else "",
            line,
        )
        cleaned = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"(\*\*|__)(.+?)\1", r"\2", cleaned)
        cleaned = re.sub(r"[`*_~]", "", cleaned)
        if re.match(r"^\s{0,3}(?:[-*_]\s*){3,}$", cleaned):
            output.extend(("", "─" * 40, ""))
            continue
        bullet = re.match(r"^(\s*)[-*+]\s+(.*)$", cleaned)
        if bullet:
            content = re.sub(
                r"^\[([ xX])\]\s+",
                lambda match: "☑  " if match.group(1).strip() else "☐  ",
                bullet.group(2),
            )
            cleaned = f"{bullet.group(1)}•  {content}"
        ordered = re.match(r"^(\s*)(\d+[.)])\s+(.*)$", cleaned)
        if ordered:
            cleaned = f"{ordered.group(1)}{ordered.group(2)}  {ordered.group(3)}"
        quote = re.match(r"^\s*>\s?(.*)$", cleaned)
        if quote:
            cleaned = f"   {quote.group(1)}"
        output.append(cleaned.rstrip())
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(output))
    return html.unescape(result).strip() or "README.md is empty."


def fetch_github_readme(item, timeout: float = 15) -> tuple[str, str]:
    """Fetch and format README.md for a GitHub item; never runs a package command."""
    slug = github_repo_slug(item)
    if not slug:
        return "", "Could not load README.md: not a GitHub repository"

    branches = []
    configured = str(getattr(item, "github_default_branch", "") or "").strip()
    if configured:
        branches.append(configured)
    branches.extend(branch for branch in ("main", "master") if branch not in branches)

    last_error = "no README.md found"
    for branch in branches:
        url = f"https://raw.githubusercontent.com/{slug}/{urllib.parse.quote(branch)}/README.md"
        request = urllib.request.Request(url, headers={"User-Agent": "Pacmangr-GUI"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = _read_github_readme_response(response)
            return _format_readme_markdown(raw), ""
        except urllib.error.HTTPError as exc:
            if exc.code in {403, 429}:
                return (
                    "",
                    f"Could not load README.md: GitHub rate limit reached (HTTP {exc.code})",
                )
            last_error = f"HTTP {exc.code}"
        except urllib.error.URLError as exc:
            last_error = f"network error: {getattr(exc, 'reason', exc)}"
        except Exception as exc:  # noqa: BLE001 - keep detail loading graceful.
            last_error = str(exc)

    request = urllib.request.Request(
        f"https://api.github.com/repos/{slug}/readme",
        headers={
            "Accept": "application/vnd.github.raw+json",
            "User-Agent": "Pacmangr-GUI",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = _read_github_readme_response(response)
        return _format_readme_markdown(raw), ""
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 429}:
            return (
                "",
                f"Could not load README.md: GitHub rate limit reached (HTTP {exc.code})",
            )
        last_error = f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        last_error = f"network error: {getattr(exc, 'reason', exc)}"
    except Exception as exc:  # noqa: BLE001
        last_error = str(exc)
    if last_error == "HTTP 404":
        return "", "This repository does not have a README file on its default branch."
    return "", f"Could not load README.md: {last_error}"


def fetch_github_files(item, timeout: float = 15, limit: int = 2000) -> tuple[str, str]:
    """Fetch a repository's file paths through GitHub's recursive tree API."""
    slug = github_repo_slug(item)
    if not slug:
        return "", "Could not list files: not a GitHub repository."

    branch = str(getattr(item, "github_default_branch", "") or "").strip()
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Pacmangr-GUI"}
    if not branch:
        request = urllib.request.Request(
            f"https://api.github.com/repos/{slug}", headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
            branch = str(payload.get("default_branch", "")).strip()
        except Exception as exc:
            return "", f"Could not find the repository's default branch: {exc}"
    if not branch:
        return "", "Could not list files: GitHub did not report a default branch."

    ref = urllib.parse.quote(branch, safe="")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{slug}/git/trees/{ref}?recursive=1",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 429}:
            return "", "GitHub's API rate limit was reached. Try again later."
        if exc.code == 404:
            return (
                "",
                "Could not list files: the repository or its default branch is unavailable.",
            )
        return "", f"Could not list files: GitHub returned HTTP {exc.code}."
    except urllib.error.URLError as exc:
        return "", f"Could not reach GitHub: {getattr(exc, 'reason', exc)}"
    except (ValueError, TypeError) as exc:
        return "", f"GitHub returned an unreadable file list: {exc}"

    tree = payload.get("tree", []) if isinstance(payload, dict) else []
    paths = sorted(
        str(entry.get("path", ""))
        for entry in tree
        if isinstance(entry, dict) and entry.get("type") == "blob" and entry.get("path")
    )
    if not paths:
        return f"{slug} · {branch}\n\nThis repository contains no files.", ""
    visible = paths[:limit]
    lines = [f"{slug} · {branch} · {len(paths):,} files", "", *visible]
    if len(paths) > len(visible):
        lines.extend(("", f"Showing the first {len(visible):,} files."))
    if isinstance(payload, dict) and payload.get("truncated"):
        lines.extend(("", "GitHub truncated this very large repository tree."))
    return "\n".join(lines), ""


class PacmanActivity(Gtk.DrawingArea):
    """Small, themed Pac-Man activity indicator for package operations."""

    def __init__(self, colours: dict[str, str]) -> None:
        super().__init__()
        self._phase = 0.0
        self._active = False
        self._mode = "install"
        self._source_id = 0
        self._body = hex_rgb(colours["primary"])
        self._eye = hex_rgb(colours["on_primary"])
        self._pellet = hex_rgb(colours["success"])
        self._remove_pellet = hex_rgb(colours["error"])
        self.set_content_width(148)
        self.set_content_height(30)
        self.set_size_request(148, 30)
        self.set_draw_func(self._draw)
        self.set_visible(False)

    def start(self, mode: str = "install") -> None:
        self._mode = mode
        self._active = True
        self.set_visible(True)
        action = {
            "install": "Installing package",
            "remove": "Removing package",
            "update": "Updating packages",
        }.get(mode, "Package operation")
        self.set_tooltip_text(f"{action} in the background")
        self.queue_draw()

        settings = Gtk.Settings.get_default()
        animations_enabled = settings is None or settings.get_property(
            "gtk-enable-animations"
        )
        if (
            animations_enabled
            and not self._source_id
            and SETTINGS.get("pacman_animation", True)
        ):
            self._source_id = GLib.timeout_add(50, self._tick)

    def stop(self) -> None:
        self._active = False
        if self._source_id:
            GLib.source_remove(self._source_id)
            self._source_id = 0
        self.set_visible(False)

    def _tick(self) -> bool:
        if not self._active:
            self._source_id = 0
            return GLib.SOURCE_REMOVE
        self._phase = (self._phase + 1.0) % 3600
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _draw(self, _area, context, width: int, height: int) -> None:
        if not self._active:
            return

        center_x = 15.0
        center_y = height / 2
        radius = min(10.0, max(6.0, center_y - 3))
        mouth, pellets = pacman_frame(self._phase, width)

        context.set_source_rgb(*self._body)
        context.move_to(center_x, center_y)
        context.arc(center_x, center_y, radius, mouth, math.tau - mouth)
        context.close_path()
        context.fill()

        context.set_source_rgb(*self._eye)
        context.arc(center_x + 1.5, center_y - radius * 0.48, 1.35, 0, math.tau)
        context.fill()

        pellet_colour = self._remove_pellet if self._mode == "remove" else self._pellet
        mouth_edge = center_x + radius + 2
        for pellet_x in pellets:
            if pellet_x <= mouth_edge:
                continue
            fade = min(1.0, (pellet_x - mouth_edge) / 8)
            context.set_source_rgba(*pellet_colour, 0.90 * fade)
            context.arc(pellet_x, center_y, 2.35, 0, math.tau)
            context.fill()
