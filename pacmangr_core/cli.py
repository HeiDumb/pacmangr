"""Headless command-line interface and command dispatch for pacmangr."""

from __future__ import annotations

import curses
import json
import os
import platform
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import sysconfig
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import constants
from .appimages import integrate_appimage, remove_appimage_integration
from .backends import (
    _appimage_key,
    _appimage_registry,
    appimage_roots,
    collect_installed_packages,
    git_package,
    is_git_url,
)
from .cache import PackageCache
from .commands import noninteractive_command, system_update_commands
from .models import PackageItem, Tools
from .tui import headless_ui
from .tui import main as tui_main
from .utils import run_capture
from .versions import format_versions, package_versions


def print_packages(items: list[PackageItem]) -> None:
    for item in items:
        state = "installed" if item.installed else "available"
        fields = (
            item.source,
            item.package_id,
            item.version or "-",
            state,
            item.description,
        )
        print(
            "\t".join(field.replace("\t", " ").replace("\n", " ") for field in fields)
        )


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


def parse_cli_operation(
    argv: list[str], *, needs_package: bool = True
) -> tuple[str, str, str, bool, bool]:
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


def resolve_cli_package(
    package: str, source: str, action: str, tools: Tools
) -> PackageItem | None:
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
        items = [
            item
            for item in items
            if item.source in accepted or item.manager in accepted
        ]
    exact = [
        item for item in items if item.package_id == package or item.name == package
    ]
    return (exact or items or [None])[0]


def run_cli_command(
    label: str, command: list[str], *, assume_yes: bool, dry_run: bool
) -> int:
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
    if (
        item is None
        or target.parent != root
        or target != Path(item.package_id).resolve()
    ):
        print(
            "refusing Git checkout outside Pacmangr's managed source directory",
            file=sys.stderr,
        )
        return 2
    root.mkdir(parents=True, exist_ok=True)
    if target.exists():
        print(f"checkout already exists: {target}", file=sys.stderr)
        return 1
    return subprocess.run(
        [git, "clone", "--filter=blob:none", url, str(target)], check=False
    ).returncode


def run_pip_install(scope: str, package: str) -> int:
    safe_name = re.sub(r"[^A-Za-z0-9_.+-]+", "-", package).strip("-.") or "package"
    if scope == "venv":
        target = constants.PIP_VENV_ROOT / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target / "bin/python").is_file():
            code = subprocess.run(
                [sys.executable, "-m", "venv", str(target)], check=False
            ).returncode
            if code != 0:
                return code
        print(f"venv: {target}")
        code = subprocess.run(
            [str(target / "bin/python"), "-m", "pip", "install", "--upgrade", package],
            check=False,
        ).returncode
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


def _appimage_release_asset(source_url: str) -> tuple[str, str]:
    """Resolve an upstream release page to a Linux AppImage asset URL."""
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("AppImage downloads must use HTTPS.")
    path = parsed.path.rstrip("/")
    if path.casefold().endswith(".appimage"):
        return source_url, Path(urllib.parse.unquote(path)).name

    host = parsed.hostname.casefold()
    if host == "api.beeper.com" and re.fullmatch(
        r"/desktop/download/linux/(?:x64|arm64)/stable/com\.automattic\.beeper\.desktop",
        path,
    ):
        return source_url, "Beeper.AppImage"

    parts = [part for part in path.split("/") if part]
    api_url = ""
    if host == "github.com" and len(parts) >= 2:
        api_url = (
            f"https://api.github.com/repos/{parts[0]}/{parts[1]}/releases/latest"
        )
    elif host == "codeberg.org" and len(parts) >= 2:
        api_url = (
            f"https://codeberg.org/api/v1/repos/{parts[0]}/{parts[1]}/releases/latest"
        )
    elif host in {"gitlab.com", "www.gitlab.com"}:
        project_parts = parts[: parts.index("-")] if "-" in parts else parts[:2]
        if len(project_parts) >= 2:
            project = urllib.parse.quote("/".join(project_parts), safe="")
            api_url = f"https://gitlab.com/api/v4/projects/{project}/releases/permalink/latest"
    if not api_url:
        raise ValueError(
            "This catalog entry has no direct AppImage URL or supported release page. "
            "Open its website to download it manually."
        )

    request = urllib.request.Request(
        api_url,
        headers={"Accept": "application/json", "User-Agent": "Pacmangr"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        release = json.loads(response.read().decode("utf-8"))

    assets: list[tuple[str, str]] = []
    if isinstance(release, dict):
        release_assets = release.get("assets", [])
        for asset in release_assets if isinstance(release_assets, list) else []:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "")
            url = str(
                asset.get("browser_download_url")
                or asset.get("direct_asset_url")
                or asset.get("url")
                or ""
            )
            if name.casefold().endswith(".appimage") and url.startswith("https://"):
                assets.append((name, url))
        links = (
            release_assets.get("links", [])
            if isinstance(release_assets, dict)
            else []
        )
        if isinstance(links, list):
            for asset in links:
                if not isinstance(asset, dict):
                    continue
                name = str(asset.get("name") or asset.get("direct_asset_url") or "")
                url = str(asset.get("direct_asset_url") or asset.get("url") or "")
                if name.casefold().endswith(".appimage") and url.startswith("https://"):
                    assets.append((name, url))
    if not assets:
        raise ValueError("No AppImage file was found in the latest upstream release.")

    machine = platform.machine().casefold()
    arch_terms = {
        "x86_64": ("x86_64", "amd64", "x64"),
        "amd64": ("x86_64", "amd64", "x64"),
        "aarch64": ("aarch64", "arm64"),
        "arm64": ("aarch64", "arm64"),
    }.get(machine, (machine,))

    def score(asset: tuple[str, str]) -> int:
        filename = asset[0].casefold()
        other_arches = ("aarch64", "arm64", "armv7", "i686", "i386", "riscv")
        if any(arch in filename for arch in other_arches if arch not in arch_terms):
            return -1
        return 10 if any(arch in filename for arch in arch_terms) else 1

    assets.sort(key=lambda asset: (score(asset), asset[0].casefold()), reverse=True)
    if score(assets[0]) < 0:
        raise ValueError(f"No AppImage release asset matches {machine}.")
    return assets[0][1], assets[0][0]


def run_appimage_install(key: str, name: str, source_url: str) -> int:
    """Download an AppImage into ~/Applications and register it for Pacmangr."""
    if key != _appimage_key(name):
        print("refusing invalid AppImage catalog key", file=sys.stderr)
        return 2
    try:
        download_url, filename = _appimage_release_asset(source_url)
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"could not find the latest AppImage release: {exc}", file=sys.stderr)
        return 1
    safe_name = re.sub(r"[^A-Za-z0-9_.+-]+", "-", name).strip("-.") or "AppImage"
    target_dir = constants.APPIMAGE_ROOT
    registry = _appimage_registry()
    existing = registry.get(key) if isinstance(registry, dict) else None
    installed_path = (
        str(existing.get("path") or "") if isinstance(existing, dict) else ""
    )
    target = (
        Path(installed_path).expanduser()
        if installed_path
        else target_dir / f"{safe_name}.AppImage"
    )
    temporary: Path | None = None
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if target.resolve().parent != target_dir.resolve():
            raise ValueError("registered AppImage path is outside ~/Applications")
        temporary = target.with_name(f".{target.name}.download-{os.getpid()}")
        request = urllib.request.Request(
            download_url, headers={"User-Agent": "Pacmangr AppImage installer"}
        )
        downloaded = 0
        with urllib.request.urlopen(request, timeout=60) as response:
            final_url = urllib.parse.urlsplit(response.geturl())
            if final_url.scheme != "https":
                raise ValueError("The AppImage download redirected away from HTTPS.")
            total = int(response.headers.get("Content-Length") or 0)
            if total > 4 * 1024**3:
                raise ValueError("The AppImage download exceeds the 4 GiB safety limit.")
            with temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    downloaded += len(chunk)
                    if downloaded > 4 * 1024**3:
                        raise ValueError(
                            "The AppImage download exceeds the 4 GiB safety limit."
                        )
                    output.write(chunk)
                    if total:
                        percent = min(100, int(downloaded * 100 / total))
                        print(f"Downloading AppImage: {percent}%", flush=True)
        with temporary.open("rb") as source:
            if source.read(4) != b"\x7fELF":
                raise ValueError("The downloaded file is not a Linux executable.")
        temporary.chmod(0o755)
        temporary.replace(target)
        registry[key] = {
            "name": name,
            "path": str(target),
            "source": source_url,
        }
        constants.APPIMAGE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        registry_temp = constants.APPIMAGE_REGISTRY_PATH.with_suffix(".tmp")
        registry_temp.write_text(json.dumps(registry, indent=2), encoding="utf-8")
        registry_temp.replace(constants.APPIMAGE_REGISTRY_PATH)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        print(f"AppImage installation failed: {exc}", file=sys.stderr)
        return 1
    try:
        integrate_appimage(target, name)
    except OSError as exc:
        print(f"Warning: could not add {name} to the app menu: {exc}", file=sys.stderr)
    print(f"Installed {name} from {filename}: {target}", flush=True)
    return 0


def run_appimage_remove(path_value: str) -> int:
    """Remove an AppImage and its Pacmangr desktop integration."""
    path = Path(path_value).expanduser()
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or resolved.suffix.casefold() != ".appimage":
            raise ValueError("The selected file is not an AppImage.")
        if not any(
            resolved.is_relative_to(root.expanduser().resolve())
            for root in appimage_roots()
            if root.exists()
        ):
            raise ValueError("Refusing to remove an AppImage outside known locations.")
        resolved.unlink()
    except (OSError, ValueError) as exc:
        print(f"AppImage removal failed: {exc}", file=sys.stderr)
        return 1

    try:
        remove_appimage_integration(resolved)
    except OSError as exc:
        print(f"Warning: could not remove the app-menu entry: {exc}", file=sys.stderr)
    try:
        registry = _appimage_registry()
        changed = False
        for key, record in list(registry.items()):
            if not isinstance(record, dict):
                continue
            registered_path = str(record.get("path") or "")
            if registered_path and Path(registered_path).expanduser().resolve() == resolved:
                del registry[key]
                changed = True
        if changed:
            constants.APPIMAGE_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = constants.APPIMAGE_REGISTRY_PATH.with_suffix(".tmp")
            temporary.write_text(json.dumps(registry, indent=2), encoding="utf-8")
            temporary.replace(constants.APPIMAGE_REGISTRY_PATH)
    except OSError as exc:
        print(f"Warning: could not update the AppImage registry: {exc}", file=sys.stderr)
    print(f"Removed AppImage: {resolved}", flush=True)
    return 0


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
            if argv[1] == "_appimage-install":
                if len(argv) != 5:
                    raise SystemExit(2)
                raise SystemExit(run_appimage_install(argv[2], argv[3], argv[4]))
            if argv[1] == "_appimage-remove":
                if len(argv) != 3:
                    raise SystemExit(2)
                raise SystemExit(run_appimage_remove(argv[2]))
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
                    package, source, scope, assume_yes, dry_run = parse_cli_operation(
                        argv[2:]
                    )
                except ValueError as exc:
                    print(
                        f"usage: pacmangr {action} <package> [--source NAME] [--scope venv|user|system] [-y] [--dry-run]",
                        file=sys.stderr,
                    )
                    print(exc, file=sys.stderr)
                    raise SystemExit(2)
                tools = Tools.detect()
                item = resolve_cli_package(package, source, action, tools)
                if item is None:
                    print(f"{package!r} was not found in {source}", file=sys.stderr)
                    raise SystemExit(1)
                command = (
                    item.install_command(tools, install_scope=scope)
                    if action == "install"
                    else item.remove_command(tools)
                )
                if not command:
                    print(
                        f"no {action} command is available for {item.title()} ({item.source})",
                        file=sys.stderr,
                    )
                    raise SystemExit(1)
                raise SystemExit(
                    run_cli_command(
                        f"{action} {item.source}",
                        command,
                        assume_yes=assume_yes,
                        dry_run=dry_run,
                    )
                )
            if argv[1] == "update":
                try:
                    _package, source, _scope, assume_yes, dry_run = parse_cli_operation(
                        argv[2:], needs_package=False
                    )
                except ValueError as exc:
                    print(
                        "usage: pacmangr update [source] [-y] [--dry-run]",
                        file=sys.stderr,
                    )
                    print(exc, file=sys.stderr)
                    raise SystemExit(2)
                commands = system_update_commands(Tools.detect(), source)
                if not commands:
                    print(
                        f"no update command is available for {source}", file=sys.stderr
                    )
                    raise SystemExit(1)
                result = 0
                for label, command in commands:
                    code = run_cli_command(
                        label, command, assume_yes=assume_yes, dry_run=dry_run
                    )
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
                        item
                        for item in items
                        if needle in item.name.lower()
                        or needle in item.package_id.lower()
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
                    (
                        item
                        for item in PackageCache().load_installed()
                        if item.package_id == package
                    ),
                    None,
                )
                item = installed or PackageItem("pacman", "pacman", package, package)
                command = item.info_command(tools, installed_view=installed is not None)
                if not command:
                    print(
                        f"no information command is available for {package}",
                        file=sys.stderr,
                    )
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
                    print(
                        "pacmangr needs to run in an interactive terminal.",
                        file=sys.stderr,
                    )
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
                print(
                    f"terminal: {'yes' if sys.stdin.isatty() and sys.stdout.isatty() else 'no'}"
                )
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
        print(
            "\n \033[31m You quit via Ctrl+C, That is a bad idea, use esc to quit next time \033[0m"
        )
