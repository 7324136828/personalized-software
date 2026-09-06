"""Create and verify the repository's Python and React environments."""

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
VENV_DIR = ROOT / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


class SetupError(RuntimeError):
    """Raised when a setup step cannot be completed."""


def executable(name: str) -> str:
    candidate = shutil.which(f"{name}.cmd" if os.name == "nt" and name == "npm" else name)
    if candidate is None:
        raise SetupError(f"{name} was not found on PATH")
    return candidate


def run(command: Sequence[str | Path], *, cwd: Path = ROOT, quiet: bool = False) -> None:
    rendered = [str(part) for part in command]
    print(f"[setup] $ {' '.join(rendered)}", flush=True)
    result = subprocess.run(
        rendered,
        cwd=cwd,
        stdout=subprocess.DEVNULL if quiet else None,
        check=False,
    )
    if result.returncode:
        raise SetupError(f"Command failed with exit code {result.returncode}: {' '.join(rendered)}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set up the Python and React development environments")
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="install dependencies without tests, typechecking, or building",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if sys.version_info < (3, 11):
        raise SetupError(
            f"Python 3.11+ is required; current interpreter is {sys.version.split()[0]}"
        )
    if not (ROOT / "requirements.txt").is_file():
        raise SetupError(f"requirements.txt was not found in {ROOT}")
    if not (REACT_DIR / "package.json").is_file():
        raise SetupError(f"React project was not found in {REACT_DIR}")

    node = executable("node")
    npm = executable("npm")
    node_version = subprocess.check_output([node, "--version"], text=True).strip()
    print(f"[setup] Python {sys.version.split()[0]}")
    print(f"[setup] Node {node_version}")

    if not VENV_PYTHON.is_file():
        print(f"[setup] Creating virtual environment at {VENV_DIR}")
        run([sys.executable, "-m", "venv", VENV_DIR])
    else:
        print(f"[setup] Reusing virtual environment at {VENV_DIR}")

    run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"])
    print("[setup] Installing Python dependencies; audio/ML packages may take several minutes.")
    run([VENV_PYTHON, "-m", "pip", "install", "-r", ROOT / "requirements.txt"])
    run([npm, "install"], cwd=REACT_DIR)

    if not args.skip_verify:
        run([VENV_PYTHON, "-m", "pip", "check"])
        run([VENV_PYTHON, "-m", "compileall", "-q", ROOT / "python", ROOT / "python_backend"])
        run([VENV_PYTHON, "-m", "unittest", "python_backend.test_server", "-v"])
        smoke_test = (
            "import sys, tkinter, kokoro, numpy, pandas, pydantic, openai, anthropic; "
            f"sys.path.insert(0, {str(ROOT / 'python')!r}); "
            "import ollama_learning; "
            "from ollama_learning.qanda import QAGenerator; "
            "print('Python imports OK')"
        )
        run([VENV_PYTHON, "-c", smoke_test])
        run([VENV_PYTHON, ROOT / "python/qanda_launcher.py", "--help"], quiet=True)
        run([npm, "run", "typecheck"], cwd=REACT_DIR)
        run([npm, "run", "build"], cwd=REACT_DIR)

    print("\n[setup] Environment ready.")
    print("[setup] Start development: python run_app.py dev")
    activation = ".venv\\Scripts\\activate.bat" if os.name == "nt" else "source .venv/bin/activate"
    print(f"[setup] Activate Python: {activation}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SetupError as error:
        print(f"\n[setup] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
