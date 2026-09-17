"""Serve generated content and temporary free-text Q&A sessions.

The server intentionally uses only Python's standard library. Generated files
are read directly from the active content directory on every request, so the
React application does not need a separate data-sync step. The local website
can switch that directory by uploading or reopening a workspace ZIP.

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
from typing import Any, BinaryIO
from urllib.parse import parse_qs, unquote, urlsplit

try:  # imported as ``backend.server`` (tests, package context)
    from backend import podcast_render
except ImportError:  # run directly: ``python python/backend/server.py``
    import podcast_render


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

    def __init__(self, output_dir: Path) -> None:
        self._lock = threading.RLock()
        resolved = output_dir.resolve()
        workspace = resolved.parent if resolved.name.casefold() == "output" else None
        self._collection_dir: Path | None = None
        self._workspaces = {
            "initial": {
                "id": "initial",
                "name": workspace.name if workspace is not None else resolved.name,
                "workspaceDirectory": str(workspace) if workspace is not None else None,
                "outputDirectory": str(resolved),
            }
        }
        self._active_workspace = "initial"

    @property
    def output_dir(self) -> Path:
        with self._lock:
            return Path(self._workspaces[self._active_workspace]["outputDirectory"])

    def select_collection(self, collection: Path) -> Path:
        collection = collection.expanduser().resolve()
        candidates = workspace_directories(collection)
        if not candidates:
            raise ValueError(
                "The selected folder must contain an output folder, or have immediate "
                "subfolders that contain output folders"
            )

        workspaces: dict[str, dict[str, str | None]] = {}
        for workspace in candidates:
            identifier = "." if workspace == collection else workspace.name
            workspaces[identifier] = {
                "id": identifier,
                "name": workspace.name,
                "workspaceDirectory": str(workspace),
                "outputDirectory": str(workspace / "output"),
            }
        with self._lock:
            self._collection_dir = collection
            self._workspaces = workspaces
            self._active_workspace = next(iter(workspaces))
            return Path(workspaces[self._active_workspace]["outputDirectory"])

    def activate_workspace(self, identifier: str) -> Path:
        with self._lock:
            workspace = self._workspaces.get(identifier)
            if workspace is None:
                raise ValueError("The requested workspace is not in the selected folder")
            output_dir = Path(workspace["outputDirectory"])
            if not output_dir.is_dir():
                raise ValueError(f"The workspace output folder no longer exists: {output_dir}")
            self._active_workspace = identifier
            return output_dir

    def status(self) -> dict[str, Any]:
        with self._lock:
            active = self._workspaces[self._active_workspace]
            output_dir = Path(active["outputDirectory"])
            return {
                "collectionDirectory": (
                    str(self._collection_dir) if self._collection_dir is not None else None
                ),
                "activeWorkspace": self._active_workspace,
                "workspaces": list(self._workspaces.values()),
                "outputDirectory": str(output_dir),
                "workspace": active["workspaceDirectory"],
                "exists": output_dir.is_dir(),
            }


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


def _find_uploaded_collection(extract_root: Path) -> Path:
    """Find outputs at the archive root or beneath a single wrapper folder."""
    candidate = extract_root
    for _ in range(10):
        if workspace_directories(candidate):
            return candidate
        try:
            children = [
                child
                for child in candidate.iterdir()
                if child.is_dir() and child.name != "__MACOSX"
            ]
        except OSError as error:
            raise ValueError("The extracted workspace could not be read") from error
        if len(children) != 1:
            break
        candidate = children[0]
    raise ValueError(
        "The ZIP must contain a workspace with output, or immediate subfolders "
        "that contain output folders"
    )


def import_workspace_archive(
    source: BinaryIO,
    content_length: int,
    filename: str,
    archive_dir: Path,
) -> tuple[dict[str, Any], Path]:
    """Persist and safely extract an uploaded workspace ZIP in the temp area."""
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
        with archive_path.open("wb") as destination:
            while remaining:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("The ZIP upload ended before all bytes were received")
                destination.write(chunk)
                remaining -= len(chunk)

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
                for member in members:
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
        except (zipfile.BadZipFile, zipfile.LargeZipFile) as error:
            raise ValueError("The uploaded file is not a valid ZIP archive") from error

        collection = _find_uploaded_collection(extract_root)
        identifier = uuid.uuid4().hex
        metadata = {
            "id": identifier,
            "name": Path(original_name).stem or "workspace",
            "originalFilename": original_name,
            "uploadedAt": utc_now(),
            "collectionRelative": collection.relative_to(staging).as_posix(),
            "workspaceCount": len(workspace_directories(collection)),
        }
        (staging / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        archive_path.unlink()
        final_dir = archive_dir / identifier
        staging.replace(final_dir)
        return metadata, final_dir / metadata["collectionRelative"]
    except (OSError, RuntimeError) as error:
        raise ValueError(f"The workspace ZIP could not be extracted: {error}") from error
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def list_workspace_archives(archive_dir: Path) -> list[dict[str, Any]]:
    """List valid, previously extracted workspace ZIPs."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    uploads: list[dict[str, Any]] = []
    for metadata_path in archive_dir.glob("*/metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            identifier = metadata["id"]
            if not isinstance(identifier, str) or not SESSION_ID.fullmatch(identifier):
                continue
            collection = safe_child(metadata_path.parent, metadata["collectionRelative"])
            workspaces = workspace_directories(collection)
            if not workspaces:
                continue
            uploads.append(
                {
                    "id": identifier,
                    "name": str(metadata["name"]),
                    "originalFilename": str(metadata["originalFilename"]),
                    "uploadedAt": str(metadata["uploadedAt"]),
                    "workspaceCount": len(workspaces),
                }
            )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    uploads.sort(key=lambda item: item["uploadedAt"], reverse=True)
    return uploads


def workspace_archive_collection(archive_dir: Path, identifier: str) -> Path:
    """Resolve a saved upload ID to its validated extracted collection."""
    if not SESSION_ID.fullmatch(identifier):
        raise ValueError("Invalid uploaded workspace ID")
    upload_dir = safe_child(archive_dir, identifier)
    try:
        metadata = json.loads((upload_dir / "metadata.json").read_text(encoding="utf-8"))
        collection = safe_child(upload_dir, metadata["collectionRelative"])
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("The uploaded workspace could not be loaded") from error
    if not workspace_directories(collection):
        raise ValueError("The uploaded workspace no longer contains any output folders")
    return collection


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


def _run_podcast_job(episode_paths: list[Path]) -> None:
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
    with PODCAST_JOB_LOCK:
        podcast_job["state"] = state
        podcast_job["result"] = result
        podcast_job["finishedAt"] = utc_now()


def start_podcast_job(output_dir: Path) -> dict[str, Any]:
    """Kick off podcast rendering in a background thread; return immediately."""
    episode_paths = podcast_script_paths(output_dir)
    with PODCAST_JOB_LOCK:
        if podcast_job["state"] == "running":
            return {"status": "already running", "startedAt": podcast_job["startedAt"]}
        PODCAST_LOG_HANDLER.clear()
        podcast_job.update(
            state="running", startedAt=utc_now(), finishedAt=None, result=None
        )
        PODCAST_LOG.info("Queued %d podcast script(s) for rendering", len(episode_paths))
    threading.Thread(
        target=_run_podcast_job, args=(episode_paths,), daemon=True
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
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if 0 < length <= MAX_REQUEST_BYTES:
            self.rfile.read(length)

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
                    {"uploads": list_workspace_archives(self.workspace_archive_dir)},
                )
                return
            if path == "/api/content/manifest":
                self._json(HTTPStatus.OK, build_manifest(self.output_dir))
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
            try:
                raw_length = self.headers.get("Content-Length")
                if raw_length is None:
                    raise ValueError("Content-Length is required")
                try:
                    content_length = int(raw_length)
                except ValueError as error:
                    raise ValueError("Invalid Content-Length") from error
                filename = unquote(self.headers.get("X-File-Name") or "workspace.zip")
                upload, collection = import_workspace_archive(
                    self.rfile,
                    content_length,
                    filename,
                    self.workspace_archive_dir,
                )
                self.content_state.select_collection(collection)
                self._json(
                    HTTPStatus.CREATED,
                    {**self.content_state.status(), "upload": upload},
                )
            except ValueError as error:
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
                collection = workspace_archive_collection(
                    self.workspace_archive_dir,
                    identifier,
                )
                self.content_state.select_collection(collection)
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
            self._json(HTTPStatus.ACCEPTED, start_podcast_job(self.output_dir))
            return
        if path != "/api/qa/sessions":
            self._error(HTTPStatus.NOT_FOUND, "API endpoint not found")
            return
        try:
            self._json(HTTPStatus.CREATED, create_session(self.response_dir, self._read_json()))
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))

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
        # The manifest merges every subject into one list per kind, so a request
        # only carries "<kind>/<file>". Look through each subject's kind folder
        # (and the legacy flat folder) for the first match.
        path = None
        for kind_dir in kind_dirs(self.output_dir, kind):
            candidate = safe_child(kind_dir, file_name)
            if candidate.is_file():
                path = candidate
                break
        if path is None:
            raise FileNotFoundError(relative)
        try:
            body = path.read_bytes()
        except OSError as error:
            # A transient read failure (for example the file briefly locked by an
            # editor on Windows) must still produce a proper HTTP response rather
            # than an aborted connection, which the app would report as a network
            # "Failed to fetch" error.
            raise FileNotFoundError(relative) from error
        if path.suffix == ".json":
            content_type = "application/json"
        else:
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
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
    content_state = ContentState(output_dir)
    handler = partial(
        LearningRequestHandler,
        content_state=content_state,
        response_dir=response_dir.resolve(),
        static_dir=static_dir.resolve(),
        workspace_archive_dir=workspace_archive_dir.resolve(),
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
