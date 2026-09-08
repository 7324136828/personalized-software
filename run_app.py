"""Build and run the React viewers with their local Python backend."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parent
REACT_DIR = ROOT / "react"
BACKEND = ROOT / "python" / "backend" / "server.py"
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


class RunError(RuntimeError):
    """Raised when an application command cannot be completed."""


def executable(name: str) -> str:
    candidate = shutil.which(f"{name}.cmd" if os.name == "nt" and name == "npm" else name)
    if candidate is None:
        raise RunError(f"{name} was not found on PATH; run setup.bat first")
    return candidate


def run(command: Sequence[str | Path], *, cwd: Path = ROOT) -> int:
    rendered = [str(part) for part in command]
    print(f"[run] $ {' '.join(rendered)}", flush=True)
    return subprocess.call(rendered, cwd=cwd)


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
        return run(command)

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
    return run(command)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunError as error:
        print(f"\n[run] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
