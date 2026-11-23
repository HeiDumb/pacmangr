"""Headless command-line interface and command dispatch for pacmangr."""

from __future__ import annotations

import curses
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import sysconfig
from pathlib import Path

from . import constants
from .backends import collect_installed_packages, git_package, is_git_url
from .cache import PackageCache
from .commands import noninteractive_command, system_update_commands
from .models import PackageItem, Tools
from .tui import PkgUI, headless_ui, main as tui_main
from .utils import run_capture
from .versions import format_versions, package_versions


def print_packages(items: list[PackageItem]) -> None:
    for item in items:
        state = "installed" if item.installed else "available"
        fields = (item.source, item.package_id, item.version or "-", state, item.description)
        print("\t".join(field.replace("\t", " ").replace("\n", " ") for field in fields))


def print_cache_status(cache: PackageCache) -> None:
    if not cache.path.exists():
        print(f"path: {cache.path}")
        print("state: empty")
        return
    print(f"path: {cache.path}")
    print(f"size: {cache.path.stat().st_size} bytes")
    try:
        with cache.connect() as conn:
            for table in ("search_cache", "installed_packages", "version_cache"):
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"{table}: {count}")
    except sqlite3.Error as exc:
        print(f"state: unreadable ({exc})")


def clear_cache(cache: PackageCache) -> None:
    removed = False
    for path in (cache.path, Path(f"{cache.path}-wal"), Path(f"{cache.path}-shm")):
        try:
            path.unlink()
            removed = True
        except FileNotFoundError:
            pass
    print("cache cleared" if removed else "cache already empty")


def parse_cli_operation(argv: list[str], *, needs_package: bool = True) -> tuple[str, str, str, bool, bool]:
    """Parse the deliberately small, stable CLI operation option set."""
    source = "all"
    scope = "user"
    assume_yes = False
    dry_run = False
    positional: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in {"-y", "--yes"}:
            assume_yes = True
        elif arg == "--dry-run":
            dry_run = True
        elif arg == "--source":
            index += 1
            if index >= len(argv):
                raise ValueError("--source needs a manager name")
            source = argv[index].lower()
        elif arg.startswith("--source="):
            source = arg.split("=", 1)[1].lower()
        elif arg == "--scope":
            index += 1
            if index >= len(argv):
                raise ValueError("--scope needs venv, user, or system")
            scope = argv[index].lower()
        elif arg.startswith("--scope="):
            scope = arg.split("=", 1)[1].lower()
        elif arg.startswith("-"):
            raise ValueError(f"unknown option: {arg}")
        else:
            positional.append(arg)
        index += 1
    if needs_package and len(positional) != 1:
        raise ValueError("exactly one package name is required")
    if not needs_package and len(positional) > 1:
        raise ValueError("update accepts at most one source")
    if not needs_package and positional:
        source = positional[0].lower()
    if scope not in {"venv", "user", "system"}:
        raise ValueError("--scope must be venv, user, or system")
    return (positional[0] if positional else "", source, scope, assume_yes, dry_run)


def resolve_cli_package(package: str, source: str, action: str, tools: Tools) -> PackageItem | None:
    if source in {"all", "git"} and action == "install" and is_git_url(package):
        return git_package(package)
    if action == "remove":
        items = collect_installed_packages(tools)
    else:
        backend = source
        if source == "aur":
            helper = tools.aur_helper
            backend = helper[0] if helper else "all"
        app = headless_ui()
        items = app.search_packages(package, backend)
    if source != "all":
        aliases = {"aur": {"aur", "aur/local", "yay", "paru"}, "pacman": {"pacman"}}
        accepted = aliases.get(source, {source})
        items = [item for item in items if item.source in accepted or item.manager in accepted]
    exact = [item for item in items if item.package_id == package or item.name == package]
    return (exact or items or [None])[0]


def run_cli_command(label: str, command: list[str], *, assume_yes: bool, dry_run: bool) -> int:
    argv = noninteractive_command(command) if assume_yes else command
    print(f"[{label}] {shlex.join(argv)}")
    if dry_run:
        return 0
    try:
        return subprocess.run(argv, check=False).returncode
    except FileNotFoundError as exc:
        print(f"could not start {exc.filename}: command not found", file=sys.stderr)
        return 127


def run_git_fetch(url: str, target_value: str) -> int:
    git = shutil.which("git")
    if not git:
        print("git is not installed", file=sys.stderr)
        return 127
    item = git_package(url)
    target = Path(target_value).expanduser().resolve()
    root = constants.GIT_SOURCE_ROOT.resolve()
    if item is None or target.parent != root or target != Path(item.package_id).resolve():
        print("refusing Git checkout outside Pacmangr's managed source directory", file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    if target.exists():
        print(f"checkout already exists: {target}", file=sys.stderr)
        return 1
    return subprocess.run([git, "clone", "--filter=blob:none", url, str(target)], check=False).returncode


def run_pip_install(scope: str, package: str) -> int:
    safe_name = re.sub(r"[^A-Za-z0-9_.+-]+", "-", package).strip("-.") or "package"
    if scope == "venv":
        target = constants.PIP_VENV_ROOT / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target / "bin/python").is_file():
            code = subprocess.run([sys.executable, "-m", "venv", str(target)], check=False).returncode
            if code != 0:
                return code
        print(f"venv: {target}")
        code = subprocess.run([str(target / "bin/python"), "-m", "pip", "install", "--upgrade", package], check=False).returncode
        if code == 0:
            (target / ".pacmangr-package").write_text(package + "\n", encoding="utf-8")
        return code
    command = [sys.executable, "-m", "pip", "install"]
    externally_managed = Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED"
    if externally_managed.is_file():
        command.append("--break-system-packages")
    if scope == "user":
        command.append("--user")
    command.append(package)
    return subprocess.run(command, check=False).returncode


def usage() -> str:
    return "\n".join(
        (
            f"{constants.APP_NAME} {constants.VERSION}",
            "usage: pacmangr [command]",
            "",
            "commands:",
            "  search <query>       open the TUI and run a search",
            "  find <query>         print unified search results",
            "  install <pkg>        install a package (--source, --scope, -y, --dry-run)",
            "  remove <pkg>         remove a package (--source NAME, -y, --dry-run)",
            "  update [source]       update all or one package source (-y, --dry-run)",
            "  installed [filter]   print installed packages",
            "  info <package>       print native package information",
            "  versions <package>   print available package versions",
            "  managers             print detected package managers",
            "  cache status|clear   inspect or clear the local cache",
            "  doctor               check manager and cache availability",
            "  --version            print the version",
            "",
            "Run without a command to open the TUI.",
        )
    )


def run_cli(argv: list[str] | None = None) -> None:
    """Dispatch headless commands, falling back to the curses interface."""
    argv = sys.argv if argv is None else argv
    try:
        if len(argv) > 1:
            if argv[1] == "_git-fetch":
                if len(argv) != 4:
                    raise SystemExit(2)
                raise SystemExit(run_git_fetch(argv[2], argv[3]))
            if argv[1] == "_pip-install":
                if len(argv) != 4 or argv[2] not in {"venv", "user", "system"}:
                    raise SystemExit(2)
                raise SystemExit(run_pip_install(argv[2], argv[3]))
            if argv[1] in {"-V", "--version"}:
                print(f"{constants.APP_NAME} {constants.VERSION}")
                raise SystemExit(0)
            if argv[1] in {"--list-managers", "managers"}:
                tools = Tools.detect()
                print(tools.enabled_labels())
                raise SystemExit(0)
            if argv[1] == "find":
                if len(argv) < 3:
                    print("usage: pacmangr find <query>", file=sys.stderr)
                    raise SystemExit(2)
                app = headless_ui()
                print_packages(app.search_packages(" ".join(argv[2:]), "all"))
                raise SystemExit(0)
            if argv[1] in {"install", "remove"}:
                action = argv[1]
                try:
                    package, source, scope, assume_yes, dry_run = parse_cli_operation(argv[2:])
                except ValueError as exc:
                    print(f"usage: pacmangr {action} <package> [--source NAME] [--scope venv|user|system] [-y] [--dry-run]", file=sys.stderr)
                    print(exc, file=sys.stderr)
                    raise SystemExit(2)
                tools = Tools.detect()
                item = resolve_cli_package(package, source, action, tools)
                if item is None:
                    print(f"{package!r} was not found in {source}", file=sys.stderr)
                    raise SystemExit(1)
                command = item.install_command(tools, install_scope=scope) if action == "install" else item.remove_command(tools)
                if not command:
                    print(f"no {action} command is available for {item.title()} ({item.source})", file=sys.stderr)
                    raise SystemExit(1)
                raise SystemExit(run_cli_command(f"{action} {item.source}", command, assume_yes=assume_yes, dry_run=dry_run))
            if argv[1] == "update":
                try:
                    _package, source, _scope, assume_yes, dry_run = parse_cli_operation(argv[2:], needs_package=False)
                except ValueError as exc:
                    print("usage: pacmangr update [source] [-y] [--dry-run]", file=sys.stderr)
                    print(exc, file=sys.stderr)
                    raise SystemExit(2)
                commands = system_update_commands(Tools.detect(), source)
                if not commands:
                    print(f"no update command is available for {source}", file=sys.stderr)
                    raise SystemExit(1)
                result = 0
                for label, command in commands:
                    code = run_cli_command(label, command, assume_yes=assume_yes, dry_run=dry_run)
                    result = result or code
                    if code != 0:
                        break
                raise SystemExit(result)
            if argv[1] == "installed":
                needle = " ".join(argv[2:]).strip().lower()
                cache = PackageCache()
                items = collect_installed_packages(Tools.detect())
                cache.save_installed(items)
                if needle:
                    items = [
                        item for item in items
                        if needle in item.name.lower() or needle in item.package_id.lower()
                    ]
                print_packages(items)
                raise SystemExit(0)
            if argv[1] == "info":
                if len(argv) != 3:
                    print("usage: pacmangr info <package>", file=sys.stderr)
                    raise SystemExit(2)
                package = argv[2]
                tools = Tools.detect()
                installed = next(
                    (item for item in PackageCache().load_installed() if item.package_id == package),
                    None,
                )
                item = installed or PackageItem("pacman", "pacman", package, package)
                command = item.info_command(tools, installed_view=installed is not None)
                if not command:
                    print(f"no information command is available for {package}", file=sys.stderr)
                    raise SystemExit(1)
                code, output = run_capture(command, timeout=30)
                print(output.rstrip())
                raise SystemExit(code)
            if argv[1] == "versions":
                if len(argv) < 3:
                    print("usage: pacmangr versions <package>", file=sys.stderr)
                    raise SystemExit(2)
                package = argv[2]
                tools = Tools.detect()
                cache = PackageCache()
                item = PackageItem("pacman", "pacman", package, package)
                versions = package_versions(tools, item)
                if versions:
                    cache.save_versions("downgrade", package, versions)
                else:
                    versions = cache.load_versions("downgrade", package)
                print(format_versions(package, versions))
                raise SystemExit(0)
            if argv[1] == "search":
                if len(argv) < 3:
                    print("usage: pacmangr search <query>", file=sys.stderr)
                    raise SystemExit(2)
                if not sys.stdin.isatty() or not sys.stdout.isatty():
                    print("pacmangr needs to run in an interactive terminal.", file=sys.stderr)
                    raise SystemExit(2)
                curses.wrapper(tui_main, " ".join(argv[2:]))
                raise SystemExit(0)
            if argv[1] == "cache":
                if len(argv) != 3 or argv[2] not in {"status", "clear"}:
                    print("usage: pacmangr cache status|clear", file=sys.stderr)
                    raise SystemExit(2)
                cache = PackageCache()
                if argv[2] == "status":
                    print_cache_status(cache)
                else:
                    clear_cache(cache)
                raise SystemExit(0)
            if argv[1] == "doctor":
                tools = Tools.detect()
                print(f"managers: {tools.enabled_labels()}")
                print(f"cache: {constants.CACHE_DB_PATH}")
                print(f"terminal: {'yes' if sys.stdin.isatty() and sys.stdout.isatty() else 'no'}")
                raise SystemExit(0 if tools.enabled_labels() != "none" else 1)
            if argv[1] in {"-h", "--help"}:
                print(usage())
                raise SystemExit(0)
            print(f"unknown command: {argv[1]}", file=sys.stderr)
            print("run 'pacmangr --help' for usage", file=sys.stderr)
            raise SystemExit(2)
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print("pacmangr needs to run in an interactive terminal.", file=sys.stderr)
            raise SystemExit(2)
        curses.wrapper(tui_main)
    except KeyboardInterrupt:
        print("\n \033[31m You quit via Ctrl+C, That is a bad idea, use esc to quit next time \033[0m")
