"""SQLite persistence for workspace ZIP imports.

Imported learning documents live in SQLite instead of an extracted directory
tree.  Custom Kokoro voice models remain ordinary files because the speech
runtime requires a filesystem path for ``.pt`` voices.
"""

from __future__ import annotations

import json
import mimetypes
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator


VOICE_SUFFIXES = {".pt"}


class ContentStore:
    """Small, thread-safe-by-connection SQLite repository for imported content."""

    def __init__(self, database: Path, voice_dir: Path) -> None:
        self.database = database.resolve()
        self.voice_dir = voice_dir.resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS uploads (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    original_filename TEXT NOT NULL,
                    uploaded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    upload_id TEXT NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
                    workspace_key TEXT NOT NULL,
                    name TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    UNIQUE(upload_id, workspace_key)
                );
                CREATE TABLE IF NOT EXISTS content (
                    id INTEGER PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    subject TEXT NOT NULL DEFAULT '',
                    filename TEXT NOT NULL,
                    body BLOB NOT NULL,
                    content_type TEXT NOT NULL,
                    UNIQUE(workspace_id, kind, subject, filename)
                );
                CREATE INDEX IF NOT EXISTS content_lookup
                    ON content(workspace_id, kind, filename);
                CREATE TABLE IF NOT EXISTS voice_assets (
                    upload_id TEXT NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
                    relative_path TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    PRIMARY KEY(upload_id, relative_path)
                );
                """
            )

    @staticmethod
    def _workspace_rows(collection: Path) -> list[tuple[str, str, Path, str]]:
        candidates: list[Path] = []
        if (collection / "output").is_dir():
            candidates.append(collection)
        candidates.extend(
            child
            for child in sorted(collection.iterdir(), key=lambda item: item.name.casefold())
            if child.is_dir() and (child / "output").is_dir()
        )
        rows: list[tuple[str, str, Path, str]] = []
        for workspace in candidates:
            key = "." if workspace == collection else workspace.name
            relative = workspace.relative_to(collection).as_posix()
            rows.append((key, workspace.name, workspace, relative))
        return rows

    @staticmethod
    def _content_files(
        output: Path, kinds: Iterable[str]
    ) -> Iterable[tuple[str, str, Path]]:
        for kind in kinds:
            flat = output / kind
            if flat.is_dir():
                for path in sorted(flat.iterdir(), key=lambda item: item.name.casefold()):
                    if path.is_file() and path.suffix.casefold() not in VOICE_SUFFIXES:
                        yield kind, "", path
            if not output.is_dir():
                continue
            for subject in sorted(output.iterdir(), key=lambda item: item.name.casefold()):
                nested = subject / kind
                if not subject.is_dir() or not nested.is_dir():
                    continue
                for path in sorted(nested.iterdir(), key=lambda item: item.name.casefold()):
                    if path.is_file() and path.suffix.casefold() not in VOICE_SUFFIXES:
                        yield kind, subject.name, path

    def import_collection(
        self,
        metadata: dict[str, Any],
        collection: Path,
        kinds: Iterable[str],
    ) -> None:
        """Atomically replace an upload with documents read from ``collection``."""
        upload_id = str(metadata["id"])
        workspaces = self._workspace_rows(collection)
        if not workspaces:
            raise ValueError("The imported collection has no workspaces")

        pending_voice_dir = Path(
            tempfile.mkdtemp(prefix=f".{upload_id}-", dir=self.voice_dir)
        )
        final_voice_dir = self.voice_dir / upload_id
        voice_rows: list[tuple[str, str]] = []
        try:
            for source in collection.rglob("*"):
                if not source.is_file() or source.suffix.casefold() not in VOICE_SUFFIXES:
                    continue
                relative = source.relative_to(collection)
                destination = pending_voice_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                voice_rows.append((relative.as_posix(), str(final_voice_dir / relative)))

            with self._connect() as connection:
                connection.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
                connection.execute(
                    "INSERT INTO uploads(id, name, original_filename, uploaded_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        upload_id,
                        str(metadata["name"]),
                        str(metadata["originalFilename"]),
                        str(metadata["uploadedAt"]),
                    ),
                )
                for key, name, workspace, relative in workspaces:
                    workspace_id = uuid.uuid5(
                        uuid.NAMESPACE_URL, f"personalized-software:{upload_id}:{key}"
                    ).hex
                    connection.execute(
                        "INSERT INTO workspaces(id, upload_id, workspace_key, name, relative_path) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (workspace_id, upload_id, key, name, relative),
                    )
                    for kind, subject, path in self._content_files(workspace / "output", kinds):
                        content_type = (
                            "application/json"
                            if path.suffix.casefold() == ".json"
                            else mimetypes.guess_type(path.name)[0]
                            or "application/octet-stream"
                        )
                        connection.execute(
                            "INSERT INTO content(workspace_id, kind, subject, filename, body, content_type) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                workspace_id,
                                kind,
                                subject,
                                path.name,
                                path.read_bytes(),
                                content_type,
                            ),
                        )
                connection.executemany(
                    "INSERT INTO voice_assets(upload_id, relative_path, file_path) VALUES (?, ?, ?)",
                    ((upload_id, relative, file_path) for relative, file_path in voice_rows),
                )

            if final_voice_dir.exists():
                shutil.rmtree(final_voice_dir)
            if voice_rows:
                pending_voice_dir.replace(final_voice_dir)
            else:
                shutil.rmtree(pending_voice_dir)
        except Exception:
            shutil.rmtree(pending_voice_dir, ignore_errors=True)
            raise

    def list_uploads(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT u.id, u.name, u.original_filename, u.uploaded_at,
                       COUNT(w.id) AS workspace_count
                FROM uploads AS u
                JOIN workspaces AS w ON w.upload_id = u.id
                GROUP BY u.id
                ORDER BY u.uploaded_at DESC
                """
            ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "originalFilename": row["original_filename"],
                "uploadedAt": row["uploaded_at"],
                "workspaceCount": row["workspace_count"],
            }
            for row in rows
        ]

    def list_workspaces(self, upload_id: str) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, workspace_key, name FROM workspaces "
                "WHERE upload_id = ? ORDER BY rowid",
                (upload_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def workspace_exists(self, workspace_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM workspaces WHERE id = ?", (workspace_id,)
            ).fetchone()
        return row is not None

    def manifest(
        self,
        workspace_id: str,
        kinds: dict[str, tuple[str, ...]],
        generated_at: str,
    ) -> dict[str, Any]:
        result: dict[str, list[dict[str, Any]]] = {}
        with self._connect() as connection:
            for kind, sidecar_suffixes in kinds.items():
                rows = connection.execute(
                    "SELECT subject, filename, body FROM content "
                    "WHERE workspace_id = ? AND kind = ? ORDER BY lower(filename)",
                    (workspace_id, kind),
                ).fetchall()
                available = {(row["subject"], row["filename"]) for row in rows}
                documents: list[dict[str, Any]] = []
                for row in rows:
                    filename = row["filename"]
                    if Path(filename).suffix.casefold() != ".json":
                        continue
                    try:
                        data = json.loads(bytes(row["body"]).decode("utf-8-sig"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(data, dict):
                        continue
                    stem = Path(filename).stem
                    title = (
                        data.get("title")
                        or data.get("name")
                        or data.get("episode_title")
                        or stem
                    )
                    documents.append(
                        {
                            "file": filename,
                            "stem": stem,
                            "title": str(title),
                            "sidecars": [
                                f"{stem}{suffix}"
                                for suffix in sidecar_suffixes
                                if (row["subject"], f"{stem}{suffix}") in available
                            ],
                            "subject": row["subject"] or None,
                        }
                    )
                result[kind] = documents
        return {"generatedAt": generated_at, "kinds": result}

    def read_content(
        self, workspace_id: str, kind: str, filename: str
    ) -> tuple[bytes, str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT body, content_type FROM content "
                "WHERE workspace_id = ? AND kind = ? AND filename = ? "
                "ORDER BY CASE WHEN subject = '' THEN 0 ELSE 1 END, lower(subject) LIMIT 1",
                (workspace_id, kind, filename),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(filename)
        return bytes(row["body"]), str(row["content_type"])

    def materialize_podcasts(self, workspace_id: str) -> tuple[Path, Path, list[Path]]:
        """Create a temporary podcast tree for the file-oriented renderer."""
        with self._connect() as connection:
            workspace = connection.execute(
                "SELECT upload_id, relative_path FROM workspaces WHERE id = ?",
                (workspace_id,),
            ).fetchone()
            if workspace is None:
                raise ValueError("The selected workspace no longer exists")
            rows = connection.execute(
                "SELECT subject, filename, body FROM content "
                "WHERE workspace_id = ? AND kind = 'podcasts'",
                (workspace_id,),
            ).fetchall()
            voices = connection.execute(
                "SELECT relative_path, file_path FROM voice_assets WHERE upload_id = ?",
                (workspace["upload_id"],),
            ).fetchall()

        root = Path(tempfile.mkdtemp(prefix="personalized-podcasts-"))
        workspace_root = root / workspace["relative_path"]
        output = workspace_root / "output"
        paths: list[Path] = []
        for row in rows:
            directory = (
                output / row["subject"] / "podcasts"
                if row["subject"]
                else output / "podcasts"
            )
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / row["filename"]
            path.write_bytes(bytes(row["body"]))
            if path.suffix.casefold() == ".json":
                paths.append(path)
        for voice in voices:
            source = Path(voice["file_path"])
            if source.is_file():
                destination = root / voice["relative_path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        return root, output, sorted(paths, key=lambda path: path.name.casefold())

    def save_podcast_outputs(self, workspace_id: str, output: Path) -> None:
        with self._connect() as connection:
            for kind, subject, path in self._content_files(output, ("podcasts",)):
                if path.suffix.casefold() == ".json":
                    continue
                content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                connection.execute(
                    "INSERT INTO content(workspace_id, kind, subject, filename, body, content_type) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(workspace_id, kind, subject, filename) DO UPDATE SET "
                    "body = excluded.body, content_type = excluded.content_type",
                    (workspace_id, kind, subject, path.name, path.read_bytes(), content_type),
                )
