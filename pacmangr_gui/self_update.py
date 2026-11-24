"""Check and apply Pacmangr updates published on GitHub."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath

OWNER = "HeiDumb"
REPOSITORY = "pacmangr"
BRANCH = "main"
API_ROOT = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}"
MAX_ARCHIVE_SIZE = 32 * 1024 * 1024
MAX_SOURCE_FILE_SIZE = 8 * 1024 * 1024


@dataclass(frozen=True)
class UpdateResult:
    status: str
    commit: str = ""
    detail: str = ""


def _request(url: str, timeout: float = 20) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Pacmangr-GUI updater",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_ARCHIVE_SIZE + 1)


def _managed_source_path(path: str) -> bool:
    if path in {"pacmangr", "pacmangr-gui"}:
        return True
    return path.endswith(".py") and (
        path.startswith("pacmangr_core/") or path.startswith("pacmangr_gui/")
    )


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _local_source_is_outdated(root: Path, remote_files: dict[str, str]) -> bool:
    for relative, expected_sha in remote_files.items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            return True
        try:
            if _git_blob_sha(path.read_bytes()) != expected_sha:
                return True
        except OSError:
            return True

    for package in ("pacmangr_core", "pacmangr_gui"):
        directory = root / package
        if directory.is_dir():
            for path in directory.rglob("*.py"):
                if path.is_symlink():
                    return True
                if path.relative_to(root).as_posix() not in remote_files:
                    return True
    return False


def _managed_root() -> tuple[Path | None, str]:
    module_path = Path(__file__).resolve()
    root = module_path.parent.parent.resolve()
    home = Path.home().resolve()
    try:
        root.relative_to(home)
    except ValueError:
        return None, "This installation is managed outside your home directory."

    if not (root / "pacmangr-gui").is_file():
        return None, "Could not locate the Pacmangr launcher for this installation."
    if not (root / "pacmangr_gui").is_dir() or not (root / "pacmangr_core").is_dir():
        return None, "Could not locate the installed Pacmangr modules."
    return root, ""


def _update_source_checkout(root: Path, commit: str) -> UpdateResult:
    remote = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    remote_url = remote.stdout.strip().rstrip("/").removesuffix(".git").lower()
    if remote.returncode or remote_url not in {
        f"https://github.com/{OWNER}/{REPOSITORY}".lower(),
        f"git@github.com:{OWNER}/{REPOSITORY}".lower(),
        f"ssh://git@github.com/{OWNER}/{REPOSITORY}".lower(),
    }:
        return UpdateResult(
            "unsupported",
            commit,
            "This source checkout is not linked to the official GitHub repository.",
        )

    state = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if state.returncode:
        return UpdateResult(
            "error",
            commit,
            state.stderr.strip() or "Could not inspect this source checkout.",
        )
    if state.stdout.strip():
        return UpdateResult(
            "local_changes",
            commit,
            "Local source changes are present, so Pacmangr left this checkout untouched.",
        )

    current = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if current.returncode == 0 and current.stdout.strip() == commit:
        return UpdateResult("current", commit)

    pulled = subprocess.run(
        ["git", "-C", str(root), "pull", "--ff-only", "origin", BRANCH],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if pulled.returncode:
        return UpdateResult(
            "error",
            commit,
            pulled.stderr.strip() or "Git could not fast-forward the checkout.",
        )
    return UpdateResult("updated", commit)


def _extract_managed_files(
    archive: bytes, destination: Path, expected: set[str]
) -> None:
    if len(archive) > MAX_ARCHIVE_SIZE:
        raise ValueError("GitHub's update archive is unexpectedly large.")
    with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as bundle:
        for member in bundle.getmembers():
            parts = PurePosixPath(member.name).parts
            if (
                len(parts) < 2
                or member.issym()
                or member.islnk()
                or not member.isfile()
            ):
                continue
            relative = PurePosixPath(*parts[1:]).as_posix()
            if relative not in expected or not _managed_source_path(relative):
                continue
            if member.size > MAX_SOURCE_FILE_SIZE:
                raise ValueError(f"Update file is too large: {relative}")
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError(f"Could not read update file: {relative}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755 if relative in {"pacmangr", "pacmangr-gui"} else 0o644)

    missing = expected.difference(
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    )
    if missing:
        raise ValueError(
            f"GitHub's archive is missing {len(missing)} application files."
        )


def _replace_installation(root: Path, staged: Path) -> None:
    names = ("pacmangr_core", "pacmangr_gui", "pacmangr", "pacmangr-gui")
    for name in names:
        target = root / name
        if target.is_symlink():
            raise ValueError(f"Refusing to replace linked installation path: {name}")

    backup = staged / "backup"
    backup.mkdir()
    backed_up: list[str] = []
    installed: list[str] = []
    try:
        for name in names:
            target = root / name
            old = backup / name
            if target.exists():
                os.replace(target, old)
                backed_up.append(name)
            os.replace(staged / name, target)
            installed.append(name)
    except Exception:
        for name in reversed(names):
            target = root / name
            old = backup / name
            if name in installed and target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            if name in backed_up and old.exists():
                os.replace(old, target)
        raise


def check_and_apply_update() -> UpdateResult:
    """Fast-forward an official source checkout or update a user-local install.

    The GUI polls this on launch and every six hours when auto-update is enabled.
    """
    root, error = _managed_root()
    if root is None:
        return UpdateResult("unsupported", detail=error)

    try:
        commit_payload = _request(f"{API_ROOT}/commits/{BRANCH}")
        commit_data = json.loads(commit_payload.decode("utf-8"))
        commit = str(commit_data.get("sha", ""))
        if not commit:
            return UpdateResult(
                "error", detail="GitHub did not return the latest commit ID."
            )

        if (root / ".git").exists():
            return _update_source_checkout(root, commit)

        tree_payload = _request(
            f"{API_ROOT}/git/trees/{urllib.parse.quote(commit, safe='')}?recursive=1"
        )
        tree_data = json.loads(tree_payload.decode("utf-8"))
        remote_files = {
            str(entry["path"]): str(entry["sha"])
            for entry in tree_data.get("tree", [])
            if isinstance(entry, dict)
            and entry.get("type") == "blob"
            and _managed_source_path(str(entry.get("path", "")))
        }
        expected = set(remote_files)
        if not expected or "pacmangr_gui/self_update.py" not in expected:
            return UpdateResult(
                "error",
                commit,
                "GitHub's source tree did not contain the Pacmangr application files.",
            )
        if not _local_source_is_outdated(root, remote_files):
            return UpdateResult("current", commit)

        archive = _request(
            f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/tarball/{commit}"
        )
        if len(archive) > MAX_ARCHIVE_SIZE:
            return UpdateResult(
                "error", commit, "GitHub's update archive is unexpectedly large."
            )

        with tempfile.TemporaryDirectory(
            prefix=".pacmangr-update-", dir=root
        ) as temp_name:
            temporary = Path(temp_name)
            staged = temporary / "staged"
            staged.mkdir()
            _extract_managed_files(archive, staged, expected)
            _replace_installation(root, staged)
        return UpdateResult("updated", commit)
    except urllib.error.HTTPError as exc:
        if exc.code in {403, 429}:
            return UpdateResult(
                "error", detail="GitHub's API rate limit was reached. Try again later."
            )
        return UpdateResult(
            "error",
            detail=f"GitHub returned HTTP {exc.code} while checking for updates.",
        )
    except urllib.error.URLError as exc:
        return UpdateResult(
            "error", detail=f"Could not reach GitHub: {getattr(exc, 'reason', exc)}"
        )
    except (
        OSError,
        ValueError,
        TypeError,
        tarfile.TarError,
        subprocess.SubprocessError,
    ) as exc:
        return UpdateResult("error", detail=str(exc))
