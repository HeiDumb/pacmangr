"""SQLite-backed cache for search results and installed package metadata."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from . import constants
from .models import (
    PackageItem,
    PackageVersion,
    package_from_dict,
    package_to_dict,
    version_from_dict,
    version_to_dict,
)


class PackageCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else constants.CACHE_DB_PATH

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=2)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        self.ensure_schema(conn)
        return conn

    def ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_cache (
                manager TEXT NOT NULL,
                query TEXT NOT NULL,
                result_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (manager, query)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS installed_packages (
                source TEXT NOT NULL,
                manager TEXT NOT NULL,
                name TEXT NOT NULL,
                package_id TEXT NOT NULL,
                version TEXT,
                description TEXT,
                repo TEXT,
                origin TEXT,
                updated_at REAL NOT NULL,
                PRIMARY KEY (source, manager, package_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS version_cache (
                manager TEXT NOT NULL,
                package_id TEXT NOT NULL,
                versions_json TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (manager, package_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_search_cache_query ON search_cache(query)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_installed_name ON installed_packages(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_version_cache_package ON version_cache(package_id)")
        conn.commit()

    def cleanup(self) -> None:
        cutoff = time.time() - constants.CACHE_MAX_AGE_SECONDS
        try:
            with self.connect() as conn:
                conn.execute("DELETE FROM search_cache WHERE updated_at < ?", (cutoff,))
                conn.execute("DELETE FROM installed_packages WHERE updated_at < ?", (cutoff,))
                conn.execute("DELETE FROM version_cache WHERE updated_at < ?", (cutoff,))
        except sqlite3.Error:
            return

    def ttl_for(self, manager: str) -> int:
        return constants.CACHE_TTL_SECONDS.get(manager, constants.CACHE_MAX_AGE_SECONDS)

    def load_search(self, query: str, managers: set[str] | None = None) -> list[PackageItem]:
        normalized = query.strip().lower()
        if not normalized:
            return []
        now = time.time()
        items: list[PackageItem] = []
        try:
            with self.connect() as conn:
                rows = conn.execute(
                    "SELECT manager, result_json, updated_at FROM search_cache WHERE query = ?",
                    (normalized,),
                ).fetchall()
        except sqlite3.Error:
            return []
        for manager, result_json, updated_at in rows:
            if managers and manager not in managers:
                continue
            if now - float(updated_at) > self.ttl_for(str(manager)):
                continue
            try:
                data = json.loads(str(result_json))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, list):
                continue
            for entry in data:
                if isinstance(entry, dict):
                    item = package_from_dict(entry)
                    if item.package_id:
                        items.append(item)
        return items

    def save_search(self, manager: str, query: str, items: list[PackageItem]) -> None:
        normalized = query.strip().lower()
        if not normalized:
            return
        payload = json.dumps([package_to_dict(item) for item in items], separators=(",", ":"))
        try:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO search_cache(manager, query, result_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(manager, query) DO UPDATE SET
                        result_json = excluded.result_json,
                        updated_at = excluded.updated_at
                    """,
                    (manager, normalized, payload, time.time()),
                )
        except sqlite3.Error:
            return

    def invalidate_search(self, query: str) -> None:
        """Discard cached search results after package state changes."""
        normalized = query.strip().lower()
        if not normalized:
            return
        try:
            with self.connect() as conn:
                conn.execute("DELETE FROM search_cache WHERE query = ?", (normalized,))
        except sqlite3.Error:
            return

    def load_versions(self, manager: str, package_id: str) -> list[PackageVersion]:
        package_id = package_id.strip()
        if not package_id:
            return []
        now = time.time()
        try:
            with self.connect() as conn:
                row = conn.execute(
                    """
                    SELECT versions_json, updated_at FROM version_cache
                    WHERE manager = ? AND package_id = ?
                    """,
                    (manager, package_id),
                ).fetchone()
        except sqlite3.Error:
            return []
        if not row:
            return []
        versions_json, updated_at = row
        if now - float(updated_at) > self.ttl_for(manager):
            return []
        try:
            data = json.loads(str(versions_json))
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        versions: list[PackageVersion] = []
        for entry in data:
            if isinstance(entry, dict):
                version = version_from_dict(entry)
                if version.version:
                    versions.append(version)
        return versions

    def save_versions(self, manager: str, package_id: str, versions: list[PackageVersion]) -> None:
        package_id = package_id.strip()
        if not package_id:
            return
        payload = json.dumps([version_to_dict(item) for item in versions], separators=(",", ":"))
        try:
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO version_cache(manager, package_id, versions_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(manager, package_id) DO UPDATE SET
                        versions_json = excluded.versions_json,
                        updated_at = excluded.updated_at
                    """,
                    (manager, package_id, payload, time.time()),
                )
        except sqlite3.Error:
            return

    def load_installed(self) -> list[PackageItem]:
        cutoff = time.time() - constants.CACHE_MAX_AGE_SECONDS
        try:
            with self.connect() as conn:
                rows = conn.execute(
                    """
                    SELECT source, manager, name, package_id, version, description, repo, origin
                    FROM installed_packages
                    WHERE updated_at >= ?
                    ORDER BY source, name
                    """,
                    (cutoff,),
                ).fetchall()
        except sqlite3.Error:
            return []
        return [
            PackageItem(
                source=source,
                manager=manager,
                name=name,
                package_id=package_id,
                version=version or "",
                description=description or "",
                repo=repo or "",
                origin=origin or "",
                installed=True,
            )
            for source, manager, name, package_id, version, description, repo, origin in rows
        ]

    def save_installed(self, items: list[PackageItem]) -> None:
        now = time.time()
        rows = [
            (
                item.source,
                item.manager,
                item.name,
                item.package_id,
                item.version,
                item.description,
                item.repo,
                item.origin,
                now,
            )
            for item in items
            if item.package_id
        ]
        try:
            with self.connect() as conn:
                conn.execute("DELETE FROM installed_packages")
                conn.executemany(
                    """
                    INSERT INTO installed_packages(
                        source, manager, name, package_id, version, description, repo, origin, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        except sqlite3.Error:
            return
