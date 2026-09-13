"""Build and run the React viewers with their local Python backend."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
REACT_DIR = ROOT / "react"
BACKEND = ROOT / "python" / "backend" / "server.py"
TTS_BACKEND = ROOT / "python-kokoro" / "server.py"
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
TTS_VENV_PYTHON = ROOT / ".venv-tts" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQUIRED_PYTHON = (3, 14, 6)
REQUIRED_PYTHON_TEXT = ".".join(map(str, REQUIRED_PYTHON))
DEFAULT_KOKORO_BASE_URL = "http://127.0.0.1:8880/v1"


class RunError(RuntimeError):
    """Raised when an application command cannot be completed."""


def executable(name: str) -> str:
    candidate = shutil.which(f"{name}.cmd" if os.name == "nt" and name == "npm" else name)
    if candidate is None:
        raise RunError(f"{name} was not found on PATH; run setup.bat first")
    return candidate


def run(
    command: Sequence[str | Path],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
) -> int:
    rendered = [str(part) for part in command]
    print(f"[run] $ {' '.join(rendered)}", flush=True)
    return subprocess.call(rendered, cwd=cwd, env=env)


def kokoro_health_url(base_url: str) -> str:
    return f"{base_url.rstrip('/').removesuffix('/v1')}/health"


def kokoro_is_healthy(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(kokoro_health_url(base_url), timeout=1) as response:
            body = json.loads(response.read().decode("utf-8"))
        return response.status == 200 and body.get("service") == "python-kokoro"
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        AttributeError,
    ):
        return False


def start_kokoro_server(base_url: str) -> subprocess.Popen[str] | None:
    """Start the isolated service, or reuse a compatible service already running."""
    if kokoro_is_healthy(base_url):
        print(f"[run] Reusing Kokoro service at {base_url}", flush=True)
        return None
    if not TTS_VENV_PYTHON.is_file():
        raise RunError(f"Kokoro environment not found at {TTS_VENV_PYTHON}; run setup.bat")
    if not TTS_BACKEND.is_file():
        raise RunError(f"Kokoro server was not found at {TTS_BACKEND}")

    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise RunError(
            f"KOKORO_BASE_URL {base_url!r} is unavailable and is not a managed loopback URL"
        )
    port = parsed.port or 80
    device = os.environ.get("PODCAST_DEVICE", "auto")
    command = [
        str(TTS_VENV_PYTHON),
        str(TTS_BACKEND),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--device",
        device,
    ]
    print(f"[run] $ {' '.join(command)}", flush=True)
    process = subprocess.Popen(command, cwd=ROOT, text=True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RunError(f"Kokoro service exited with code {process.returncode}")
        if kokoro_is_healthy(base_url):
            print(f"[run] Kokoro service ready at {base_url}", flush=True)
            return process
        time.sleep(0.25)
    process.terminate()
    process.wait(timeout=10)
    raise RunError("Kokoro service did not become healthy within 60 seconds")


def stop_process(process: subprocess.Popen[str] | None, label: str) -> None:
    if process is None or process.poll() is not None:
        return
    print(f"[run] Stopping {label}...", flush=True)
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build or run the learning-content application")
    parser.add_argument("command", nargs="?", choices=["serve", "dev", "build"], default="serve")
    parser.add_argument("--port", type=int, help="frontend port; defaults to 4173 or 5174 in dev")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    parser.add_argument(
        "--folder-path",
        type=Path,
        metavar="PATH",
        help="workspace folder whose output directory should be served",
    )
    parser.add_argument(
        "--host",
        help="interface to bind (use 0.0.0.0 to reach the app from other devices)",
    )
    parser.add_argument(
        "--lan",
        action="store_true",
        help="shortcut for --host 0.0.0.0: serve to other devices on this network",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info[:3] != REQUIRED_PYTHON:
        raise RunError(
            f"Python {REQUIRED_PYTHON_TEXT} is required; "
            f"current interpreter is {sys.version.split()[0]}. Run setup.bat with Python "
            f"{REQUIRED_PYTHON_TEXT} first."
        )
    arguments = list(argv if argv is not None else sys.argv[1:])
    if arguments and arguments[0].lower() == "help":
        arguments[0] = "--help"
    args = parse_args(arguments)
    port = args.port or (5174 if args.command == "dev" else 4173)
    host = "0.0.0.0" if args.lan and not args.host else args.host
    host_args = ["--host", host] if host else []
    folder_path = args.folder_path.expanduser().resolve() if args.folder_path else None
    output_dir = (folder_path / "output") if folder_path else (ROOT / "new_output")
    folder_args = ["--folder-path", folder_path] if folder_path else []

    executable("node")
    npm = executable("npm")
    if not (REACT_DIR / "package.json").is_file():
        raise RunError(f"React project was not found in {REACT_DIR}")
    if not output_dir.is_dir() and (folder_path or not (ROOT / "output").is_dir()):
        raise RunError(f"Generated-content folder was not found at {output_dir}")
    if not BACKEND.is_file():
        raise RunError(f"Python backend was not found at {BACKEND}")

    if not (REACT_DIR / "node_modules").is_dir():
        print("[run] Installing React dependencies...")
        if run([npm, "install"], cwd=REACT_DIR):
            raise RunError("npm install failed")

    backend_python = VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable)
    kokoro_base_url = os.environ.get("KOKORO_BASE_URL", DEFAULT_KOKORO_BASE_URL).rstrip("/")
    backend_env = os.environ.copy()
    backend_env["KOKORO_BASE_URL"] = kokoro_base_url
    if args.command == "dev":
        command: list[str | Path] = [
            backend_python,
            BACKEND,
            "--dev",
            "--frontend-port",
            str(port),
            *host_args,
            *folder_args,
        ]
        if not args.no_open:
            command.append("--open")
        tts_process = start_kokoro_server(kokoro_base_url)
        try:
            return run(command, env=backend_env)
        finally:
            stop_process(tts_process, "Kokoro service")

    print("[run] Building React for production...")
    if run([npm, "run", "build"], cwd=REACT_DIR):
        raise RunError("React production build failed")
    if not (REACT_DIR / "dist/index.html").is_file():
        raise RunError("React build completed without producing dist/index.html")
    if args.command == "build":
        print(f"[run] Build ready at {REACT_DIR / 'dist'}")
        return 0

    command = [backend_python, BACKEND, "--port", str(port), *host_args, *folder_args]
    if not args.no_open:
        command.append("--open")
    tts_process = start_kokoro_server(kokoro_base_url)
    try:
        return run(command, env=backend_env)
    finally:
        stop_process(tts_process, "Kokoro service")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunError as error:
        print(f"\n[run] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
