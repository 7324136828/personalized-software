"""Serve generated content and temporary free-text Q&A sessions.

The server intentionally uses only Python's standard library. Generated files
are read directly from the active content directory on every request, while
workspace ZIP imports are persisted in SQLite. The React application does not
need a separate data-sync step.

Content is organised per subject: ``new_output/<subject>/<kind>/<file>`` (for
example ``new_output/classical_chinese/quizzes/quiz_heart_sutra.json``). The
manifest aggregates every subject into one list per kind. The older flat
layout (``output/<kind>/<file>``) is still read when present, so an existing
checkout keeps working.
"""

from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import uuid
import webbrowser
import zipfile
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, BinaryIO, Callable
from urllib.parse import parse_qs, unquote, urlsplit

try:  # imported as ``backend.server`` (tests, package context)
    from backend import podcast_render
    from backend.content_store import ContentStore
except ImportError:  # run directly: ``python python/backend/server.py``
    import podcast_render
    from content_store import ContentStore


# server.py lives at <repo>/python/backend/server.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "new_output"
DEFAULT_STATIC_DIR = PROJECT_ROOT / "react" / "dist"
DEFAULT_RESPONSE_DIR = Path(tempfile.gettempdir()) / "personalized-software" / "qa-sessions"
DEFAULT_WORKSPACE_ARCHIVE_DIR = (
    Path(tempfile.gettempdir()) / "personalized-software" / "workspaces"
)
DEFAULT_FLASHCARD_AUDIO_DIR = (
    Path(tempfile.gettempdir()) / "personalized-software" / "flashcard-audio"
)
PODCAST_CHECKPOINT_DIR = PROJECT_ROOT / ".checkpoints" / "podcasts"
PODCAST_DEVICE = os.environ.get("PODCAST_DEVICE", "auto")
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_WORKSPACE_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_WORKSPACE_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_WORKSPACE_ARCHIVE_FILES = 20_000
MAX_FLASHCARD_AUDIO_CARDS = 1_000
MAX_FLASHCARD_AUDIO_CHARACTERS = 1_000_000
PODCAST_LOG_CAPACITY = 2_000
FLASHCARD_FRONT_VOICE = os.environ.get("FLASHCARD_FRONT_VOICE", "af_heart")
FLASHCARD_BACK_VOICE = os.environ.get("FLASHCARD_BACK_VOICE", "af_heart")
FLASHCARD_AUDIO_LOCK = threading.Lock()

KINDS: dict[str, tuple[str, ...]] = {
    "quizzes": (),
    "qandas": (),
    "mindmaps": (".md", ".mmd"),
    "flashcards": (".txt",),
    "reports": (".md", ".html"),
    "slides": (".md",),
    "datatables": (".csv",),
    "infographics": (".html", ".svg", ".md", ".wireframe.txt"),
    "podcasts": (".mp3", ".wav"),
}

SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
WRITE_LOCK = threading.Lock()


def workspace_directories(collection: Path) -> list[Path]:
    """Find a workspace at this path and in each immediate child folder."""
    candidates: list[Path] = []
    if (collection / "output").is_dir():
        candidates.append(collection)
    try:
        children = sorted(collection.iterdir(), key=lambda path: path.name.casefold())
    except OSError as error:
        raise ValueError(f"The selected folder could not be read: {collection}") from error
    candidates.extend(
        child for child in children if child.is_dir() and (child / "output").is_dir()
    )
    return candidates


class ContentState:
    """Thread-safe content location shared by every request handler."""

    def __init__(self, output_dir: Path, store: ContentStore) -> None:
        self._lock = threading.RLock()
        self.store = store
        resolved = output_dir.resolve()
        workspace = resolved.parent if resolved.name.casefold() == "output" else None
        self._collection_dir: Path | None = None
        self._initial_workspaces = {
            "initial": {
                "id": "initial",
                "name": workspace.name if workspace is not None else resolved.name,
                "workspaceDirectory": str(workspace) if workspace is not None else None,
                "outputDirectory": str(resolved),
                "databaseWorkspaceId": None,
            }
        }
        self._workspaces = {key: dict(value) for key, value in self._initial_workspaces.items()}
        self._active_workspace = "initial"
        self._upload_progress: dict[str, dict[str, Any]] = {}

    def begin_upload(self, identifier: str) -> None:
        with self._lock:
            if len(self._upload_progress) >= 100:
                self._upload_progress.pop(next(iter(self._upload_progress)))
            self._upload_progress[identifier] = {
                "id": identifier,
                "state": "uploading",
                "percent": 0,
                "message": "Preparing upload",
                "currentWorkspace": None,
                "completedWorkspaces": 0,
                "totalWorkspaces": 0,
            }

    def update_upload(self, identifier: str, **changes: Any) -> None:
        with self._lock:
            progress = self._upload_progress.get(identifier)
            if progress is None:
                return
            progress.update(changes)
            progress["percent"] = max(0, min(100, int(progress["percent"])))

    def upload_status(self, identifier: str) -> dict[str, Any]:
        with self._lock:
            progress = self._upload_progress.get(identifier)
            if progress is None:
                raise FileNotFoundError(identifier)
            return dict(progress)

    @property
    def output_dir(self) -> Path:
        with self._lock:
            output = self._workspaces[self._active_workspace]["outputDirectory"]
            if output is None:
                raise ValueError("Imported content is stored in SQLite")
            return Path(output)

    @property
    def database_workspace_id(self) -> str | None:
        with self._lock:
            value = self._workspaces[self._active_workspace].get("databaseWorkspaceId")
            return str(value) if value is not None else None

    def select_upload(self, upload_id: str, workspace_key: str | None = None) -> None:
        rows = self.store.list_workspaces(upload_id)
        if not rows:
            raise ValueError("The uploaded workspace could not be loaded")
        workspaces: dict[str, dict[str, str | None]] = {}
        for row in rows:
            identifier = row["workspace_key"]
            workspaces[identifier] = {
                "id": identifier,
                "name": row["name"],
                "workspaceDirectory": None,
                "outputDirectory": None,
                "databaseWorkspaceId": row["id"],
            }
        if workspace_key is not None and workspace_key not in workspaces:
            raise ValueError("The requested study set is not in the selected library")
        with self._lock:
            self._collection_dir = None
            self._workspaces = workspaces
            self._active_workspace = workspace_key or next(iter(workspaces))

    def activate_workspace(self, identifier: str) -> Path:
        with self._lock:
            workspace = self._workspaces.get(identifier)
            if workspace is None:
                raise ValueError("The requested workspace is not in the selected folder")
            database_id = workspace.get("databaseWorkspaceId")
            output_value = workspace.get("outputDirectory")
            if database_id is not None:
                if not self.store.workspace_exists(str(database_id)):
                    raise ValueError("The workspace no longer exists in SQLite")
            elif output_value is None or not Path(output_value).is_dir():
                raise ValueError(f"The workspace output folder no longer exists: {output_value}")
            self._active_workspace = identifier
            return Path(output_value) if output_value is not None else self.store.database

    def delete_study_set(self, workspace_id: str) -> dict[str, Any]:
        deleted = self.store.delete_workspace(workspace_id)
        with self._lock:
            loaded_key = next(
                (
                    key
                    for key, workspace in self._workspaces.items()
                    if workspace.get("databaseWorkspaceId") == workspace_id
                ),
                None,
            )
            if loaded_key is not None:
                del self._workspaces[loaded_key]
                if self._workspaces:
                    if self._active_workspace == loaded_key:
                        self._active_workspace = next(iter(self._workspaces))
                else:
                    self._collection_dir = None
                    self._workspaces = {
                        key: dict(value) for key, value in self._initial_workspaces.items()
                    }
                    self._active_workspace = "initial"
        return deleted

    def delete_study_library(self, upload_id: str) -> dict[str, Any]:
        deleted = self.store.delete_upload(upload_id)
        deleted_ids = set(deleted["workspaceIds"])
        with self._lock:
            if any(
                workspace.get("databaseWorkspaceId") in deleted_ids
                for workspace in self._workspaces.values()
            ):
                self._collection_dir = None
                self._workspaces = {
                    key: dict(value) for key, value in self._initial_workspaces.items()
                }
                self._active_workspace = "initial"
        return deleted

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = self._workspaces[self._active_workspace]
            output_value = active.get("outputDirectory")
            database_id = active.get("databaseWorkspaceId")
            exists = (
                self.store.workspace_exists(str(database_id))
                if database_id is not None
                else output_value is not None and Path(output_value).is_dir()
            )
            return {
                "collectionDirectory": (
                    str(self._collection_dir) if self._collection_dir is not None else None
                ),
                "activeWorkspace": self._active_workspace,
                "workspaces": list(self._workspaces.values()),
                "outputDirectory": (
                    str(output_value)
                    if output_value is not None
                    else f"SQLite: {self.store.database}"
                ),
                "workspace": active["workspaceDirectory"],
                "exists": exists,
            }

    def manifest(self) -> dict[str, Any]:
        database_id = self.database_workspace_id
        if database_id is not None:
            return self.store.manifest(database_id, KINDS, utc_now())
        return build_manifest(self.output_dir)

    def read_content(self, kind: str, filename: str) -> tuple[bytes, str]:
        database_id = self.database_workspace_id
        if database_id is not None:
            return self.store.read_content(database_id, kind, filename)
        for kind_dir in kind_dirs(self.output_dir, kind):
            candidate = safe_child(kind_dir, filename)
            if not candidate.is_file():
                continue
            try:
                body = candidate.read_bytes()
            except OSError as error:
                raise FileNotFoundError(filename) from error
            content_type = (
                "application/json"
                if candidate.suffix.casefold() == ".json"
                else mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            )
            return body, content_type
        raise FileNotFoundError(filename)

def _archive_member_path(extract_root: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"ZIP entry uses an absolute path: {member_name}")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." or ":" in part for part in parts):
        raise ValueError(f"ZIP entry has an unsafe path: {member_name}")
    destination = (extract_root / Path(*parts)).resolve()
    try:
        destination.relative_to(extract_root.resolve())
    except ValueError as error:
        raise ValueError(f"ZIP entry escapes the extraction folder: {member_name}") from error
    return destination


def _workspace_manifest(
    extract_root: Path,
) -> tuple[Path, list[tuple[str, str, Path, str]]]:
    """Load the archive's sole workspace.json and resolve its declared outputs."""
    manifests = [
        path
        for path in extract_root.rglob("workspace.json")
        if "__MACOSX" not in path.parts and path.is_file()
    ]
    if not manifests:
        raise ValueError("The ZIP must contain a workspace.json file")
    if len(manifests) > 1:
        raise ValueError("The ZIP must contain exactly one workspace.json file")

    manifest_path = manifests[0]
    collection = manifest_path.parent
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("workspace.json must contain valid UTF-8 JSON") from error
    entries = document.get("workspace") if isinstance(document, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("workspace.json must contain a non-empty 'workspace' array")

    rows: list[tuple[str, str, Path, str]] = []
    seen_paths: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"workspace.json entry {index} must be an object")
        name = entry.get("name")
        raw_path = entry.get("path")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"workspace.json entry {index} requires a non-empty name")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"workspace.json entry {index} requires a non-empty path")
        output = _archive_member_path(collection, raw_path.strip())
        if output.name.casefold() != "output" or not output.is_dir():
            raise ValueError(
                f"workspace.json entry {index} path must reference an existing output folder: "
                f"{raw_path}"
            )
        workspace = output.parent
        relative = workspace.relative_to(collection).as_posix()
        key = relative or "."
        if key in seen_paths:
            raise ValueError(f"workspace.json contains the path more than once: {raw_path}")
        seen_paths.add(key)
        rows.append((key, name.strip(), workspace, relative))
    return collection, rows


def import_workspace_archive(
    source: BinaryIO,
    content_length: int,
    filename: str,
    archive_dir: Path,
    store: ContentStore,
    progress: Callable[[str, int, str | None, int, int], None] | None = None,
) -> dict[str, Any]:
    """Safely unpack a ZIP, then persist its learning content in SQLite."""
    original_name = Path(filename).name
    if not original_name.lower().endswith(".zip"):
        raise ValueError("Only .zip workspace archives can be uploaded")
    if content_length <= 0:
        raise ValueError("The uploaded ZIP is empty")
    if content_length > MAX_WORKSPACE_ARCHIVE_BYTES:
        raise ValueError("The uploaded ZIP exceeds the 512 MB limit")

    archive_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".upload-", dir=archive_dir))
    try:
        archive_path = staging / "upload.zip"
        remaining = content_length
        received = 0
        with archive_path.open("wb") as destination:
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("The ZIP upload ended before all bytes were received")
                destination.write(chunk)
                remaining -= len(chunk)
                received += len(chunk)
                if progress is not None:
                    progress("uploading", 2 + int(18 * received / content_length), None, 0, 0)

        extract_root = staging / "files"
        extract_root.mkdir()
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = archive.infolist()
                file_members = [member for member in members if not member.is_dir()]
                if len(file_members) > MAX_WORKSPACE_ARCHIVE_FILES:
                    raise ValueError("The ZIP contains too many files")
                if sum(member.file_size for member in file_members) > MAX_WORKSPACE_EXTRACTED_BYTES:
                    raise ValueError("The ZIP expands beyond the 2 GB limit")
                member_count = max(1, len(members))
                for member_index, member in enumerate(members, start=1):
                    mode = member.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        raise ValueError(f"ZIP symbolic links are not supported: {member.filename}")
                    if member.flag_bits & 0x1:
                        raise ValueError("Encrypted ZIP files are not supported")
                    target = _archive_member_path(extract_root, member.filename)
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source_file, target.open("wb") as target_file:
                        shutil.copyfileobj(source_file, target_file, length=1024 * 1024)
                    if progress is not None:
                        progress(
                            "extracting",
                            20 + int(30 * member_index / member_count),
                            None,
                            0,
                            0,
                        )
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as error:
            raise ValueError("The uploaded file is not a valid ZIP archive") from error

        if progress is not None:
            progress("validating", 52, None, 0, 0)
        collection, workspaces = _workspace_manifest(extract_root)
        identifier = uuid.uuid4().hex
        metadata = {
            "id": identifier,
            "name": Path(original_name).stem or "workspace",
            "originalFilename": original_name,
            "uploadedAt": utc_now(),
            "collectionRelative": collection.relative_to(staging).as_posix(),
            "workspaceCount": len(workspaces),
        }
        total_workspaces = len(workspaces)

        def store_progress(completed: int, total: int, name: str) -> None:
            if progress is not None:
                progress(
                    "importing",
                    55 + int(40 * completed / max(1, total)),
                    name,
                    completed,
                    total,
                )

        store.import_collection(
            metadata,
            collection,
            KINDS,
            workspaces=workspaces,
            progress=store_progress,
        )
        if progress is not None:
            progress("finalizing", 98, workspaces[-1][1], total_workspaces, total_workspaces)
        return metadata
    except (OSError, RuntimeError, sqlite3.Error) as error:
        raise ValueError(f"The workspace ZIP could not be imported: {error}") from error
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def migrate_workspace_archives(archive_dir: Path, store: ContentStore) -> None:
    """Move uploads created by older releases from extracted files into SQLite."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    for metadata_path in archive_dir.glob("*/metadata.json"):
        legacy_dir = metadata_path.parent
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            identifier = metadata["id"]
            if not isinstance(identifier, str) or not SESSION_ID.fullmatch(identifier):
                continue
            collection = safe_child(legacy_dir, metadata["collectionRelative"])
            if not workspace_directories(collection):
                continue
            # Re-import even if a row exists so a previously interrupted
            # migration also repairs any voice files before cleanup.
            store.import_collection(metadata, collection, KINDS)
            # The transaction (and voice copy, when present) completed before
            # removing the old extracted study-note tree.
            shutil.rmtree(legacy_dir)
        except (KeyError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error, json.JSONDecodeError):
            # A bad legacy upload must not prevent the application from starting.
            continue


def _flashcard_audio_path(cache_dir: Path, text: str, voice: str) -> Path:
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "text": text,
                "voice": voice,
                "speed": 1.0,
                "language": "a",
                "kokoro": podcast_render.KOKORO_SERVICE_VERSION,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return cache_dir / f"{cache_key}.wav"


def generate_flashcard_audio(payload: Any, cache_dir: Path) -> dict[str, Any]:
    """Synthesize and cache both sides of every supplied flashcard."""
    if not isinstance(payload, dict) or not isinstance(payload.get("cards"), list):
        raise ValueError("cards must be an array")
    raw_cards = payload["cards"]
    if not raw_cards:
        raise ValueError("cards must not be empty")
    if len(raw_cards) > MAX_FLASHCARD_AUDIO_CARDS:
        raise ValueError(f"At most {MAX_FLASHCARD_AUDIO_CARDS} flashcards can be narrated")

    cards: list[tuple[str, str]] = []
    total_characters = 0
    for index, card in enumerate(raw_cards):
        if not isinstance(card, dict):
            raise ValueError(f"cards[{index}] must be an object")
        front = card.get("front")
        back = card.get("back")
        if not isinstance(front, str) or not front.strip():
            raise ValueError(f"cards[{index}].front must be a non-empty string")
        if not isinstance(back, str) or not back.strip():
            raise ValueError(f"cards[{index}].back must be a non-empty string")
        front = front.strip()
        back = back.strip()
        total_characters += len(front) + len(back)
        cards.append((front, back))
    if total_characters > MAX_FLASHCARD_AUDIO_CHARACTERS:
        raise ValueError("The flashcard text exceeds the narration limit")

    cache_dir.mkdir(parents=True, exist_ok=True)
    result: list[dict[str, str]] = []
    with FLASHCARD_AUDIO_LOCK:
        for front, back in cards:
            urls: dict[str, str] = {}
            for side, text, voice in (
                ("front", front, FLASHCARD_FRONT_VOICE),
                ("back", back, FLASHCARD_BACK_VOICE),
            ):
                audio_path = _flashcard_audio_path(cache_dir, text, voice)
                if not audio_path.is_file():
                    wav = podcast_render.synthesize_wav(text, voice=voice)
                    temporary = audio_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
                    try:
                        temporary.write_bytes(wav)
                        temporary.replace(audio_path)
                    finally:
                        temporary.unlink(missing_ok=True)
                urls[side] = f"/api/flashcards/audio/{audio_path.name}"
            result.append(urls)
    return {
        "cards": result,
        "frontVoice": FLASHCARD_FRONT_VOICE,
        "backVoice": FLASHCARD_BACK_VOICE,
    }


class PodcastMemoryLogHandler(logging.Handler):
    """Keep a bounded, thread-safe history of podcast renderer messages."""

    def __init__(self, capacity: int = PODCAST_LOG_CAPACITY) -> None:
        super().__init__(level=logging.INFO)
        self.capacity = capacity
        self._entries: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._entries_lock = threading.Lock()
        self._next_id = 1

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            timestamp = datetime.fromtimestamp(record.created, timezone.utc).isoformat()
            with self._entries_lock:
                entry_id = self._next_id
                self._next_id += 1
                self._entries.append(
                    {
                        "id": entry_id,
                        "timestamp": timestamp,
                        "level": record.levelname,
                        "message": message,
                    }
                )
        except Exception:  # pragma: no cover - logging must never stop rendering
            self.handleError(record)

    def clear(self) -> None:
        with self._entries_lock:
            self._entries.clear()

    def snapshot(self, *, after: int = 0, limit: int = 200) -> dict[str, Any]:
        with self._entries_lock:
            stored = list(self._entries)

        oldest_id = stored[0]["id"] if stored else None
        latest_id = stored[-1]["id"] if stored else after
        if after:
            available = [entry for entry in stored if entry["id"] > after]
            selected = available[:limit]
        else:
            available = stored
            selected = stored[-limit:]
        return {
            "entries": selected,
            "nextAfter": selected[-1]["id"] if selected else after,
            "oldestId": oldest_id,
            "latestId": latest_id,
            "hasMore": len(available) > len(selected),
            "truncated": bool(after and oldest_id is not None and after < oldest_id - 1),
            "capacity": self.capacity,
        }


PODCAST_LOG_HANDLER = PodcastMemoryLogHandler()
PODCAST_LOG = logging.getLogger("podcast")
PODCAST_LOG.addHandler(PODCAST_LOG_HANDLER)
PODCAST_LOG.setLevel(logging.INFO)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_child(base: Path, relative: str) -> Path:
    """Resolve a user-supplied relative path, rejecting directory traversal."""
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as error:
        raise ValueError("Path is outside the configured directory") from error
    return candidate


def kind_dirs(output_dir: Path, kind: str) -> list[Path]:
    """Every directory that may hold documents of ``kind``.

    Supports both the per-subject layout (``new_output/<subject>/<kind>/``) and
    the older flat layout (``output/<kind>/``). Subjects are visited in
    case-insensitive name order so results are stable.
    """
    dirs: list[Path] = []
    flat = output_dir / kind
    if flat.is_dir():
        dirs.append(flat)
    if output_dir.is_dir():
        for subject in sorted(output_dir.iterdir(), key=lambda item: item.name.lower()):
            nested = subject / kind
            if subject.is_dir() and nested.is_dir():
                dirs.append(nested)
    return dirs


def build_manifest(output_dir: Path) -> dict[str, Any]:
    """Build the content index directly from the current output directory."""
    kinds: dict[str, list[dict[str, Any]]] = {}
    for kind, sidecar_suffixes in KINDS.items():
        documents: list[dict[str, Any]] = []
        for kind_dir in kind_dirs(output_dir, kind):
            for path in sorted(kind_dir.glob("*.json"), key=lambda item: item.name.lower()):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue
                stem = path.stem
                title = data.get("title") or data.get("name") or data.get("episode_title") or stem
                sidecars = [
                    f"{stem}{suffix}"
                    for suffix in sidecar_suffixes
                    if (kind_dir / f"{stem}{suffix}").is_file()
                ]
                subject = kind_dir.parent.name if kind_dir.parent != output_dir else None
                documents.append(
                    {
                        "file": path.name,
                        "stem": stem,
                        "title": str(title),
                        "sidecars": sidecars,
                        "subject": subject,
                    }
                )
        documents.sort(key=lambda item: item["file"].lower())
        kinds[kind] = documents
    return {"generatedAt": utc_now(), "kinds": kinds}


def _validate_questions(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("questions must be a non-empty array")
    questions: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("question"), str):
            raise ValueError(f"questions[{index}] must contain string id and question fields")
        questions.append({"id": item["id"], "question": item["question"]})
    return questions


def create_session(response_dir: Path, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    title = payload.get("title")
    qa_file = payload.get("qaFile")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string")
    if not isinstance(qa_file, str) or not qa_file.strip():
        raise ValueError("qaFile must be a non-empty string")
    questions = _validate_questions(payload.get("questions"))
    now = utc_now()
    session = {
        "id": uuid.uuid4().hex,
        "qaFile": qa_file,
        "title": title,
        "status": "in_progress",
        "currentQuestion": 0,
        "createdAt": now,
        "updatedAt": now,
        "completedAt": None,
        "responses": [
            {"id": item["id"], "question": item["question"], "answer": ""}
            for item in questions
        ],
    }
    write_session(response_dir, session)
    return session


def session_path(response_dir: Path, session_id: str) -> Path:
    if not SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid session id")
    return response_dir / f"{session_id}.json"


def write_session(response_dir: Path, session: dict[str, Any]) -> None:
    response_dir.mkdir(parents=True, exist_ok=True)
    destination = session_path(response_dir, session["id"])
    temporary = destination.with_suffix(".tmp")
    encoded = json.dumps(session, indent=2, ensure_ascii=False)
    with WRITE_LOCK:
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, destination)


def read_session(response_dir: Path, session_id: str) -> dict[str, Any]:
    path = session_path(response_dir, session_id)
    if not path.is_file():
        raise FileNotFoundError(session_id)
    return json.loads(path.read_text(encoding="utf-8"))


def update_session(response_dir: Path, session_id: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object")
    session = read_session(response_dir, session_id)
    answers = payload.get("answers")
    if not isinstance(answers, list) or len(answers) != len(session["responses"]):
        raise ValueError("answers must match the session question count")
    if not all(isinstance(answer, str) for answer in answers):
        raise ValueError("every answer must be a string")
    current = payload.get("currentQuestion", session["currentQuestion"])
    if not isinstance(current, int) or isinstance(current, bool):
        raise ValueError("currentQuestion must be an integer")
    current = max(0, min(current, len(answers) - 1))
    completed = payload.get("completed", False)
    if not isinstance(completed, bool):
        raise ValueError("completed must be a boolean")

    for response, answer in zip(session["responses"], answers):
        response["answer"] = answer
    now = utc_now()
    session["currentQuestion"] = current
    session["updatedAt"] = now
    if completed:
        session["status"] = "completed"
        session["completedAt"] = session["completedAt"] or now
    else:
        session["status"] = "in_progress"
        session["completedAt"] = None
    write_session(response_dir, session)
    return session


def list_sessions(response_dir: Path) -> list[dict[str, Any]]:
    if not response_dir.is_dir():
        return []
    sessions = []
    for path in response_dir.glob("*.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            sessions.append(
                {
                    "id": item["id"],
                    "qaFile": item["qaFile"],
                    "title": item["title"],
                    "status": item["status"],
                    "updatedAt": item["updatedAt"],
                    "answered": sum(bool(r.get("answer", "").strip()) for r in item["responses"]),
                    "total": len(item["responses"]),
                }
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            continue
    return sorted(sessions, key=lambda item: item["updatedAt"], reverse=True)


# --------------------------------------------------------------------------
# Podcast generation (POST /api/generate_podcast)
# --------------------------------------------------------------------------

PODCAST_JOB_LOCK = threading.Lock()
# One process-wide job at a time. ``state`` is "idle" | "running" | "done" | "error".
podcast_job: dict[str, Any] = {
    "state": "idle",
    "startedAt": None,
    "finishedAt": None,
    "result": None,
}


def podcast_script_paths(output_dir: Path) -> list[Path]:
    """Every podcast script JSON in the content tree (all subjects, plus legacy flat)."""
    paths: list[Path] = []
    for kind_dir in kind_dirs(output_dir, "podcasts"):
        paths.extend(sorted(kind_dir.glob("*.json"), key=lambda item: item.name.lower()))
    return paths


def _run_podcast_job(
    episode_paths: list[Path],
    imported: tuple[ContentStore, str, Path, Path] | None = None,
) -> None:
    PODCAST_LOG.info(
        "Podcast render started: %d script(s), device=%s",
        len(episode_paths),
        PODCAST_DEVICE,
    )
    try:
        result: dict[str, Any] = podcast_render.render_library(
            episode_paths,
            device=PODCAST_DEVICE,
            checkpoint_dir=PODCAST_CHECKPOINT_DIR,
        )
        if imported is not None:
            store, workspace_id, _root, output = imported
            store.save_podcast_outputs(workspace_id, output)
        state = "done"
        PODCAST_LOG.info(
            "Podcast render finished: %d generated, %d skipped, %d failed",
            len(result.get("generated", [])),
            len(result.get("skipped", [])),
            len(result.get("failed", [])),
        )
    except Exception as error:  # noqa: BLE001 - report any failure back to the caller
        result = {"error": str(error)}
        state = "error"
        PODCAST_LOG.exception("Podcast render stopped with an unexpected error")
    finally:
        if imported is not None:
            shutil.rmtree(imported[2], ignore_errors=True)
    with PODCAST_JOB_LOCK:
        podcast_job["state"] = state
        podcast_job["result"] = result
        podcast_job["finishedAt"] = utc_now()


def start_podcast_job(
    output_dir: Path | None = None,
    *,
    store: ContentStore | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Kick off podcast rendering in a background thread; return immediately."""
    with PODCAST_JOB_LOCK:
        if podcast_job["state"] == "running":
            return {"status": "already running", "startedAt": podcast_job["startedAt"]}

    imported: tuple[ContentStore, str, Path, Path] | None = None
    if workspace_id is not None:
        if store is None:
            raise ValueError("SQLite content store is required")
        root, imported_output, episode_paths = store.materialize_podcasts(workspace_id)
        imported = (store, workspace_id, root, imported_output)
    elif output_dir is not None:
        episode_paths = podcast_script_paths(output_dir)
    else:
        raise ValueError("A content source is required")
    with PODCAST_JOB_LOCK:
        # Another request may have started while imported scripts were being
        # materialized. Discard this request's temporary copy in that case.
        if podcast_job["state"] == "running":
            if imported is not None:
                shutil.rmtree(imported[2], ignore_errors=True)
            return {"status": "already running", "startedAt": podcast_job["startedAt"]}
        PODCAST_LOG_HANDLER.clear()
        podcast_job.update(
            state="running", startedAt=utc_now(), finishedAt=None, result=None
        )
        PODCAST_LOG.info("Queued %d podcast script(s) for rendering", len(episode_paths))
    threading.Thread(
        target=_run_podcast_job, args=(episode_paths, imported), daemon=True
    ).start()
    return {"status": "started", "podcasts": len(episode_paths)}


def podcast_job_status() -> dict[str, Any]:
    with PODCAST_JOB_LOCK:
        return dict(podcast_job)


def podcast_log_status(*, after: int = 0, limit: int = 200) -> dict[str, Any]:
    """Return job state together with a bounded page of renderer messages."""
    result = PODCAST_LOG_HANDLER.snapshot(after=after, limit=limit)
    result["job"] = podcast_job_status()
    return result


def query_integer(
    query: dict[str, list[str]], name: str, default: int, minimum: int, maximum: int
) -> int:
    """Read one bounded integer query parameter or raise a client error."""
    raw = query.get(name, [str(default)])[-1]
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


class LearningRequestHandler(SimpleHTTPRequestHandler):
    """HTTP handler for API requests plus the built React application."""

    server_version = "LearningContentBackend/1.0"
    # Keep connections alive so the browser can reuse a small pool of sockets
    # instead of opening (and having the server tear down) one per request. The
    # React views fetch every document of a kind in parallel; under HTTP/1.0 the
    # per-response socket close races with those bursts and surfaces in the app
    # as "Failed to fetch". Every response below sends an accurate
    # Content-Length, which is what makes HTTP/1.1 keep-alive safe here.
    protocol_version = "HTTP/1.1"

    def __init__(
        self,
        *args: Any,
        content_state: ContentState,
        response_dir: Path,
        static_dir: Path,
        workspace_archive_dir: Path,
        flashcard_audio_dir: Path,
        **kwargs: Any,
    ) -> None:
        self.content_state = content_state
        self.response_dir = response_dir
        self.static_dir = static_dir
        self.workspace_archive_dir = workspace_archive_dir
        self.flashcard_audio_dir = flashcard_audio_dir
        super().__init__(*args, directory=str(static_dir), **kwargs)

    @property
    def output_dir(self) -> Path:
        return self.content_state.output_dir

    def _workspace_web_access_allowed(self) -> bool:
        fetch_site = self.headers.get("Sec-Fetch-Site")
        return fetch_site in {None, "same-origin"}

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        super().end_headers()

    def _json(self, status: HTTPStatus, value: Any, *, download: str | None = None) -> None:
        body = json.dumps(value, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json(status, {"error": message})

    def _drain_body(self) -> None:
        """Consume and discard a request body so keep-alive stays in sync."""
        if self.headers.get("Transfer-Encoding"):
            # Decoding a rejected streamed body is needless work. Closing the
            # socket guarantees its bytes cannot be parsed as another request.
            self.close_connection = True
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            return
        if 0 < length <= MAX_REQUEST_BYTES:
            self.rfile.read(length)
        elif length > MAX_REQUEST_BYTES:
            self.close_connection = True

    def _read_chunked_body(
        self,
        destination: BinaryIO,
        maximum: int,
        progress: Callable[[int], None] | None = None,
    ) -> int:
        """Decode an HTTP/1.1 chunked body into ``destination``.

        Vite and other reverse proxies are allowed to replace Content-Length
        with Transfer-Encoding: chunked while streaming a browser upload.
        ``BaseHTTPRequestHandler`` does not decode that framing itself.
        """
        total = 0
        while True:
            line = self.rfile.readline(8193)
            if len(line) > 8192 or not line.endswith(b"\r\n"):
                self.close_connection = True
                raise ValueError("The upload has invalid chunk framing")
            try:
                chunk_size = int(line[:-2].split(b";", 1)[0], 16)
            except ValueError as error:
                self.close_connection = True
                raise ValueError("The upload has an invalid chunk size") from error
            if chunk_size < 0:
                self.close_connection = True
                raise ValueError("The upload has an invalid chunk size")
            if chunk_size == 0:
                # Consume optional trailers and their terminating blank line.
                while True:
                    trailer = self.rfile.readline(8193)
                    if len(trailer) > 8192 or not trailer.endswith(b"\r\n"):
                        self.close_connection = True
                        raise ValueError("The upload has invalid trailer framing")
                    if trailer == b"\r\n":
                        return total
            if total + chunk_size > maximum:
                # The rest of this request is deliberately not consumed. Close
                # the connection so those bytes cannot become another request.
                self.close_connection = True
                raise ValueError("The uploaded ZIP exceeds the 512 MB limit")
            chunk = self.rfile.read(chunk_size)
            if len(chunk) != chunk_size or self.rfile.read(2) != b"\r\n":
                self.close_connection = True
                raise ValueError("The ZIP upload ended before all bytes were received")
            destination.write(chunk)
            total += chunk_size
            if progress is not None:
                progress(total)

    def _receive_workspace_archive(self, filename: str, upload_id: str) -> dict[str, Any]:
        """Read either a fixed-length or chunked ZIP request and import it."""
        def report(
            stage: str,
            percent: int,
            current_workspace: str | None,
            completed: int,
            total: int,
        ) -> None:
            messages = {
                "uploading": "Receiving workspace ZIP",
                "extracting": "Extracting workspace files",
                "validating": "Reading workspace.json",
                "importing": (
                    f"Processing study set {completed + 1} of {total}"
                    if completed < total
                    else "Finishing study sets"
                ),
                "finalizing": "Finalizing study library",
            }
            self.content_state.update_upload(
                upload_id,
                state=stage,
                percent=percent,
                message=messages[stage],
                currentWorkspace=current_workspace,
                completedWorkspaces=completed,
                totalWorkspaces=total,
            )

        if not Path(filename).name.lower().endswith(".zip"):
            self._drain_body()
            raise ValueError("Only .zip workspace archives can be uploaded")
        raw_length = self.headers.get("Content-Length")
        raw_expected_length = self.headers.get("X-File-Size")
        transfer_encoding = self.headers.get("Transfer-Encoding", "")
        encodings = [
            part.strip().casefold()
            for part in transfer_encoding.split(",")
            if part.strip()
        ]

        if raw_length is not None and encodings:
            self.close_connection = True
            raise ValueError("Upload cannot use both Content-Length and Transfer-Encoding")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except ValueError as error:
                self.close_connection = True
                raise ValueError("Invalid Content-Length") from error
            if content_length < 0:
                self.close_connection = True
                raise ValueError("Invalid Content-Length")
            if content_length > MAX_WORKSPACE_ARCHIVE_BYTES:
                self.close_connection = True
            return import_workspace_archive(
                self.rfile,
                content_length,
                filename,
                self.workspace_archive_dir,
                self.content_state.store,
                report,
            )
        if encodings != ["chunked"]:
            self.close_connection = True
            raise ValueError("Content-Length or chunked Transfer-Encoding is required")

        # Spool large uploads to disk rather than keeping hundreds of MB in RAM.
        expected_length: int | None = None
        if raw_expected_length is not None:
            try:
                expected_length = int(raw_expected_length)
            except ValueError as error:
                self.close_connection = True
                raise ValueError("Invalid X-File-Size") from error
            if expected_length <= 0 or expected_length > MAX_WORKSPACE_ARCHIVE_BYTES:
                self.close_connection = True
                raise ValueError("Invalid X-File-Size")

        def receive_progress(received: int) -> None:
            if expected_length is not None:
                report(
                    "uploading",
                    2 + int(18 * min(received, expected_length) / expected_length),
                    None,
                    0,
                    0,
                )

        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as body:
            content_length = self._read_chunked_body(
                body,
                MAX_WORKSPACE_ARCHIVE_BYTES,
                receive_progress,
            )
            if expected_length is not None and content_length != expected_length:
                raise ValueError("The uploaded ZIP size did not match the selected file")
            body.seek(0)
            return import_workspace_archive(
                body,
                content_length,
                filename,
                self.workspace_archive_dir,
                self.content_state.store,
                report,
            )

    def _read_json(self) -> Any:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ValueError("Content-Length is required")
        try:
            length = int(raw_length)
        except ValueError as error:
            raise ValueError("Invalid Content-Length") from error
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Request body is too large")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid UTF-8 JSON") from error

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        requested = urlsplit(self.path)
        path = unquote(requested.path)
        try:
            if path == "/api/health":
                self._json(HTTPStatus.OK, {"status": "ok"})
                return
            if path == "/api/workspace":
                if not self._workspace_web_access_allowed():
                    self._error(
                        HTTPStatus.FORBIDDEN,
                        "Cross-origin workspace access is not allowed",
                    )
                    return
                self._json(HTTPStatus.OK, self.content_state.status())
                return
            if path == "/api/workspace/uploads":
                if not self._workspace_web_access_allowed():
                    self._error(
                        HTTPStatus.FORBIDDEN,
                        "Cross-origin workspace access is not allowed",
                    )
                    return
                self._json(
                    HTTPStatus.OK,
                    {"uploads": self.content_state.store.list_uploads()},
                )
                return
            progress_match = re.fullmatch(
                r"/api/workspace/uploads/progress/([0-9a-f]{32})", path
            )
            if progress_match:
                if not self._workspace_web_access_allowed():
                    self._error(
                        HTTPStatus.FORBIDDEN,
                        "Cross-origin workspace access is not allowed",
                    )
                    return
                self._json(
                    HTTPStatus.OK,
                    self.content_state.upload_status(progress_match.group(1)),
                )
                return
            if path == "/api/content/manifest":
                self._json(HTTPStatus.OK, self.content_state.manifest())
                return
            if path.startswith("/api/flashcards/audio/"):
                self._serve_flashcard_audio(path.removeprefix("/api/flashcards/audio/"))
                return
            if path.startswith("/api/content/"):
                self._serve_content(path.removeprefix("/api/content/"))
                return
            if path == "/api/qa/sessions":
                self._json(HTTPStatus.OK, {"sessions": list_sessions(self.response_dir)})
                return
            if path == "/api/generate_podcast":
                self._json(HTTPStatus.OK, podcast_job_status())
                return
            if path == "/api/generate_podcast/logs":
                query = parse_qs(requested.query)
                after = query_integer(query, "after", 0, 0, 2**63 - 1)
                limit = query_integer(query, "limit", 200, 1, 1_000)
                self._json(
                    HTTPStatus.OK,
                    podcast_log_status(after=after, limit=limit),
                )
                return
            match = re.fullmatch(r"/api/qa/sessions/([^/]+)(/download)?", path)
            if match:
                session = read_session(self.response_dir, match.group(1))
                filename = f"qa-{session['id']}.json" if match.group(2) else None
                self._json(HTTPStatus.OK, session, download=filename)
                return
            if path.startswith("/api/"):
                self._error(HTTPStatus.NOT_FOUND, "API endpoint not found")
                return
            self._serve_static(path)
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))
        except FileNotFoundError:
            self._error(HTTPStatus.NOT_FOUND, "Resource not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        path = unquote(urlsplit(self.path).path)
        if path == "/api/flashcards/audio":
            try:
                generated = generate_flashcard_audio(
                    self._read_json(),
                    self.flashcard_audio_dir,
                )
                self._json(HTTPStatus.OK, generated)
            except ValueError as error:
                self._error(HTTPStatus.BAD_REQUEST, str(error))
            except RuntimeError as error:
                self._error(HTTPStatus.SERVICE_UNAVAILABLE, str(error))
            return
        if path == "/api/workspace/upload":
            if not self._workspace_web_access_allowed():
                self._drain_body()
                self._error(
                    HTTPStatus.FORBIDDEN,
                    "Cross-origin workspace access is not allowed",
                )
                return
            upload_id = self.headers.get("X-Upload-ID") or uuid.uuid4().hex
            if not SESSION_ID.fullmatch(upload_id):
                self._drain_body()
                self._error(HTTPStatus.BAD_REQUEST, "Invalid upload progress ID")
                return
            self.content_state.begin_upload(upload_id)
            try:
                filename = unquote(self.headers.get("X-File-Name") or "workspace.zip")
                upload = self._receive_workspace_archive(filename, upload_id)
                self.content_state.select_upload(upload["id"])
                self.content_state.update_upload(
                    upload_id,
                    state="done",
                    percent=100,
                    message="Study library ready",
                )
                self._json(
                    HTTPStatus.CREATED,
                    {**self.content_state.status(), "upload": upload},
                )
            except ValueError as error:
                self.content_state.update_upload(
                    upload_id,
                    state="error",
                    message=str(error),
                )
                self._error(HTTPStatus.BAD_REQUEST, str(error))
            return
        if path == "/api/workspace/activate":
            if not self._workspace_web_access_allowed():
                self._drain_body()
                self._error(
                    HTTPStatus.FORBIDDEN,
                    "Cross-origin workspace access is not allowed",
                )
                return
            try:
                payload = self._read_json()
                identifier = payload.get("workspaceId") if isinstance(payload, dict) else None
                if not isinstance(identifier, str) or not identifier:
                    raise ValueError("workspaceId must be a non-empty string")
                self.content_state.activate_workspace(identifier)
                self._json(HTTPStatus.OK, self.content_state.status())
            except ValueError as error:
                self._error(HTTPStatus.BAD_REQUEST, str(error))
            return
        if path == "/api/workspace/load":
            if not self._workspace_web_access_allowed():
                self._drain_body()
                self._error(
                    HTTPStatus.FORBIDDEN,
                    "Cross-origin workspace access is not allowed",
                )
                return
            try:
                payload = self._read_json()
                identifier = payload.get("uploadId") if isinstance(payload, dict) else None
                if not isinstance(identifier, str) or not identifier:
                    raise ValueError("uploadId must be a non-empty string")
                if not SESSION_ID.fullmatch(identifier):
                    raise ValueError("Invalid uploaded workspace ID")
                workspace_key = payload.get("workspaceId")
                if workspace_key is not None and (
                    not isinstance(workspace_key, str) or not workspace_key
                ):
                    raise ValueError("workspaceId must be a non-empty string")
                self.content_state.select_upload(identifier, workspace_key)
                self._json(HTTPStatus.OK, self.content_state.status())
            except ValueError as error:
                self._error(HTTPStatus.BAD_REQUEST, str(error))
            return
        if path == "/api/generate_podcast":
            # The "Refresh Podcasts" buttons (React and desktop) call this to
            # (re)synthesise audio for every podcast script JSON in the content
            # tree. Rendering runs in a background thread; poll GET
            # /api/generate_podcast for progress.
            self._drain_body()
            database_id = self.content_state.database_workspace_id
            self._json(
                HTTPStatus.ACCEPTED,
                start_podcast_job(
                    None if database_id is not None else self.output_dir,
                    store=self.content_state.store,
                    workspace_id=database_id,
                ),
            )
            return
        if path != "/api/qa/sessions":
            self._error(HTTPStatus.NOT_FOUND, "API endpoint not found")
            return
        try:
            self._json(HTTPStatus.CREATED, create_session(self.response_dir, self._read_json()))
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib handler API
        path = unquote(urlsplit(self.path).path)
        study_set_match = re.fullmatch(
            r"/api/workspace/study-sets/([0-9a-f]{32})", path
        )
        library_match = re.fullmatch(r"/api/workspace/uploads/([0-9a-f]{32})", path)
        if not study_set_match and not library_match:
            self._error(HTTPStatus.NOT_FOUND, "API endpoint not found")
            return
        if not self._workspace_web_access_allowed():
            self._drain_body()
            self._error(
                HTTPStatus.FORBIDDEN,
                "Cross-origin workspace access is not allowed",
            )
            return
        self._drain_body()
        try:
            deleted = (
                self.content_state.delete_study_set(study_set_match.group(1))
                if study_set_match
                else self.content_state.delete_study_library(library_match.group(1))
            )
            self._json(
                HTTPStatus.OK,
                {**self.content_state.status(), "deleted": deleted},
            )
        except ValueError as error:
            self._error(HTTPStatus.NOT_FOUND, str(error))

    def do_PUT(self) -> None:  # noqa: N802 - stdlib handler API
        path = unquote(urlsplit(self.path).path)
        match = re.fullmatch(r"/api/qa/sessions/([^/]+)", path)
        if not match:
            self._error(HTTPStatus.NOT_FOUND, "API endpoint not found")
            return
        try:
            updated = update_session(self.response_dir, match.group(1), self._read_json())
            self._json(HTTPStatus.OK, updated)
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))
        except FileNotFoundError:
            self._error(HTTPStatus.NOT_FOUND, "Session not found")

    def _serve_content(self, relative: str) -> None:
        kind, separator, file_name = relative.partition("/")
        if not separator or kind not in KINDS or not file_name:
            raise FileNotFoundError(relative)
        body, content_type = self.content_state.read_content(kind, file_name)
        if content_type.startswith("text/") or content_type in {"application/json", "image/svg+xml"}:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_flashcard_audio(self, file_name: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{64}\.wav", file_name):
            raise FileNotFoundError(file_name)
        path = safe_child(self.flashcard_audio_dir, file_name)
        if not path.is_file():
            raise FileNotFoundError(file_name)
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str) -> None:
        if not self.static_dir.is_dir():
            self._error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "React build not found. Run npm run build in react/ or start the development server.",
            )
            return
        requested = safe_child(self.static_dir, path.lstrip("/"))
        if path == "/" or not requested.is_file():
            self.path = "/index.html"
        super().do_GET()


def create_server(
    host: str,
    port: int,
    output_dir: Path,
    response_dir: Path,
    static_dir: Path,
    workspace_archive_dir: Path = DEFAULT_WORKSPACE_ARCHIVE_DIR,
    flashcard_audio_dir: Path = DEFAULT_FLASHCARD_AUDIO_DIR,
) -> ThreadingHTTPServer:
    workspace_archive_dir = workspace_archive_dir.resolve()
    store = ContentStore(
        workspace_archive_dir / "study-notes.sqlite3",
        workspace_archive_dir / "voices",
    )
    migrate_workspace_archives(workspace_archive_dir, store)
    content_state = ContentState(output_dir, store)
    handler = partial(
        LearningRequestHandler,
        content_state=content_state,
        response_dir=response_dir.resolve(),
        static_dir=static_dir.resolve(),
        workspace_archive_dir=workspace_archive_dir,
        flashcard_audio_dir=flashcard_audio_dir.resolve(),
    )
    return ThreadingHTTPServer((host, port), handler)


WILDCARD_HOSTS = {"0.0.0.0", "::", ""}


def is_wildcard_host(host: str) -> bool:
    """True when the server is bound to every interface, not just loopback."""
    return host in WILDCARD_HOSTS


def local_ip() -> str | None:
    """Best-effort LAN address of this machine, for sharing with other devices."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No packets are sent; this just picks the interface that would route out.
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def browser_url(host: str, port: int) -> str:
    """A URL this machine's browser can open (0.0.0.0 is not routable)."""
    shown = "localhost" if is_wildcard_host(host) else host
    return f"http://{shown}:{port}"


def print_reachable_urls(label: str, host: str, port: int) -> None:
    """Print the loopback URL and, when bound wide, the LAN URL to share."""
    if is_wildcard_host(host):
        print(f"[backend] {label} (this device): http://localhost:{port}", flush=True)
        address = local_ip()
        if address:
            print(
                f"[backend] {label} (other devices on this network): "
                f"http://{address}:{port}",
                flush=True,
            )
        else:
            print(
                "[backend] Could not determine this machine's LAN address; "
                "use its IP with the port above.",
                flush=True,
            )
    else:
        print(f"[backend] {label}: http://{host}:{port}", flush=True)


def run_development(args: argparse.Namespace) -> int:
    """Run the API beside Vite and stop both together on Ctrl+C."""
    server = create_server(args.host, args.port, args.output_dir, args.response_dir, args.static_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Vite runs the proxy on this machine, so it always reaches the API over
    # loopback regardless of what the API is also bound to.
    api_url = f"http://127.0.0.1:{server.server_port}"
    print(f"[backend] API: {api_url}/api", flush=True)

    command = [
        "npm.cmd" if os.name == "nt" else "npm",
        "run",
        "dev:frontend",
        "--",
        "--port",
        str(args.frontend_port),
        "--strictPort",
    ]
    if is_wildcard_host(args.host):
        # Expose the Vite dev server on the LAN as well as the API.
        command += ["--host", "0.0.0.0"]
    print_reachable_urls("App", args.host, args.frontend_port)
    env = os.environ.copy()
    env["CONTENT_API_TARGET"] = api_url
    if args.open:
        webbrowser.open(f"http://localhost:{args.frontend_port}/#/qanda")
    try:
        return subprocess.call(command, cwd=PROJECT_ROOT / "react", env=env)
    except KeyboardInterrupt:
        return 0
    finally:
        server.shutdown()
        server.server_close()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve learning content and temporary Q&A responses")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind (use 0.0.0.0 to reach it from other devices)",
    )
    parser.add_argument(
        "--lan",
        action="store_true",
        help="Shortcut for --host 0.0.0.0: serve to other devices on this network",
    )
    parser.add_argument("--port", type=int, default=8765, help="Backend/production web port")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Content root; scanned as <output-dir>/<subject>/<kind>/ (default: new_output)",
    )
    parser.add_argument("--response-dir", type=Path, default=DEFAULT_RESPONSE_DIR)
    parser.add_argument("--static-dir", type=Path, default=DEFAULT_STATIC_DIR)
    parser.add_argument("--dev", action="store_true", help="Run the API and Vite development server together")
    parser.add_argument("--frontend-port", type=int, default=5174)
    parser.add_argument("--open", action="store_true", help="Open the application in a browser")
    parsed = parser.parse_args(argv)
    if parsed.lan and parsed.host == "127.0.0.1":
        parsed.host = "0.0.0.0"
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dev:
        return run_development(args)

    server = create_server(args.host, args.port, args.output_dir, args.response_dir, args.static_dir)
    print_reachable_urls("Application", args.host, server.server_port)
    print(f"[backend] Content: {args.output_dir.resolve()}", flush=True)
    print(f"[backend] Temporary Q&A responses: {args.response_dir.resolve()}", flush=True)
    if args.open:
        webbrowser.open(f"{browser_url(args.host, server.server_port)}/#/qanda")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[backend] Stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
