"""Serve generated content and temporary free-text Q&A sessions.

The server intentionally uses only Python's standard library. Generated files
are read directly from ``output/`` on every request, so the React application
does not need a separate data-sync step.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import threading
import uuid
import webbrowser
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_STATIC_DIR = PROJECT_ROOT / "react" / "dist"
DEFAULT_RESPONSE_DIR = Path(tempfile.gettempdir()) / "personalized-software" / "qa-sessions"
MAX_REQUEST_BYTES = 2 * 1024 * 1024

KINDS: dict[str, tuple[str, ...]] = {
    "quizzes": (),
    "qandas": (),
    "mindmaps": (".md", ".mmd"),
    "flashcards": (".txt",),
    "reports": (".md", ".html"),
    "slides": (".md",),
    "datatables": (".csv",),
    "infographics": (".html", ".svg", ".md", ".wireframe.txt"),
}

SESSION_ID = re.compile(r"^[0-9a-f]{32}$")
WRITE_LOCK = threading.Lock()


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


def build_manifest(output_dir: Path) -> dict[str, Any]:
    """Build the content index directly from the current output directory."""
    kinds: dict[str, list[dict[str, Any]]] = {}
    for kind, sidecar_suffixes in KINDS.items():
        kind_dir = output_dir / kind
        documents: list[dict[str, Any]] = []
        if kind_dir.is_dir():
            for path in sorted(kind_dir.glob("*.json"), key=lambda item: item.name.lower()):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue
                stem = path.stem
                title = data.get("title") or data.get("name") or stem
                sidecars = [
                    f"{stem}{suffix}"
                    for suffix in sidecar_suffixes
                    if (kind_dir / f"{stem}{suffix}").is_file()
                ]
                documents.append(
                    {"file": path.name, "stem": stem, "title": str(title), "sidecars": sidecars}
                )
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


class LearningRequestHandler(SimpleHTTPRequestHandler):
    """HTTP handler for API requests plus the built React application."""

    server_version = "LearningContentBackend/1.0"

    def __init__(
        self,
        *args: Any,
        output_dir: Path,
        response_dir: Path,
        static_dir: Path,
        **kwargs: Any,
    ) -> None:
        self.output_dir = output_dir
        self.response_dir = response_dir
        self.static_dir = static_dir
        super().__init__(*args, directory=str(static_dir), **kwargs)

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
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/api/health":
                self._json(HTTPStatus.OK, {"status": "ok"})
                return
            if path == "/api/content/manifest":
                self._json(HTTPStatus.OK, build_manifest(self.output_dir))
                return
            if path.startswith("/api/content/"):
                self._serve_content(path.removeprefix("/api/content/"))
                return
            if path == "/api/qa/sessions":
                self._json(HTTPStatus.OK, {"sessions": list_sessions(self.response_dir)})
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
        path = safe_child(self.output_dir / kind, file_name)
        if not path.is_file():
            raise FileNotFoundError(relative)
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/json", "image/svg+xml"}:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
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
) -> ThreadingHTTPServer:
    handler = partial(
        LearningRequestHandler,
        output_dir=output_dir.resolve(),
        response_dir=response_dir.resolve(),
        static_dir=static_dir.resolve(),
    )
    return ThreadingHTTPServer((host, port), handler)


def run_development(args: argparse.Namespace) -> int:
    """Run the API beside Vite and stop both together on Ctrl+C."""
    server = create_server(args.host, args.port, args.output_dir, args.response_dir, args.static_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    api_url = f"http://{args.host}:{server.server_port}"
    print(f"[backend] API: {api_url}/api", flush=True)

    command = ["npm.cmd" if os.name == "nt" else "npm", "run", "dev:frontend", "--", "--port", str(args.frontend_port)]
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
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="Backend/production web port")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--response-dir", type=Path, default=DEFAULT_RESPONSE_DIR)
    parser.add_argument("--static-dir", type=Path, default=DEFAULT_STATIC_DIR)
    parser.add_argument("--dev", action="store_true", help="Run the API and Vite development server together")
    parser.add_argument("--frontend-port", type=int, default=5174)
    parser.add_argument("--open", action="store_true", help="Open the application in a browser")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.dev:
        return run_development(args)

    server = create_server(args.host, args.port, args.output_dir, args.response_dir, args.static_dir)
    url = f"http://{args.host}:{server.server_port}"
    print(f"[backend] Application: {url}", flush=True)
    print(f"[backend] Content: {args.output_dir.resolve()}", flush=True)
    print(f"[backend] Temporary Q&A responses: {args.response_dir.resolve()}", flush=True)
    if args.open:
        webbrowser.open(f"{url}/#/qanda")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[backend] Stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
