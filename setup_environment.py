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
TTS_ROOT = ROOT / "python-kokoro"
TTS_REQUIREMENTS = TTS_ROOT / "requirements.txt"
_ACTIVE_ENVIRONMENT = (
    sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    or bool(os.environ.get("VIRTUAL_ENV"))
    or bool(os.environ.get("CONDA_PREFIX"))
)
try:
    _PROJECT_ENVIRONMENT = Path(sys.prefix).resolve() == VENV_DIR.resolve()
except OSError:
    _PROJECT_ENVIRONMENT = False
_TTS_CACHE_ROOT = Path(
    os.environ.get("LOCALAPPDATA")
    or os.environ.get("XDG_CACHE_HOME")
    or Path.home() / ".cache"
)
TTS_VENV_DIR = (
    Path(
        os.environ.get(
            "PERSONALIZED_SOFTWARE_TTS_VENV",
            _TTS_CACHE_ROOT / "personalized-software" / ".venv-tts",
        )
    )
    if _ACTIVE_ENVIRONMENT and not _PROJECT_ENVIRONMENT
    else ROOT / ".venv-tts"
)
TTS_VENV_PYTHON = TTS_VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQUIRED_PYTHON = (3, 14, 6)
REQUIRED_PYTHON_TEXT = ".".join(map(str, REQUIRED_PYTHON))
TTS_PYTHON = (3, 12)
TTS_PYTHON_TEXT = ".".join(map(str, TTS_PYTHON))


CUDA_TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
CUDA_TORCH_VERSION = "2.11.0+cu128"
CUDA_TORCHAUDIO_VERSION = "2.11.0+cu128"
CUDA_TORCHVISION_VERSION = "0.26.0+cu128"
CUDA_RUNTIME_VERSION = "12.8"
CUDA_TORCH_PACKAGES = (
    f"torch=={CUDA_TORCH_VERSION}",
    f"torchaudio=={CUDA_TORCHAUDIO_VERSION}",
    f"torchvision=={CUDA_TORCHVISION_VERSION}",
)
RTX_NAME = 'NVIDIA GeForce RTX'
MAIN_TTS_PACKAGES = (
    "kokoro",
    "kokoro-onnx",
    "misaki",
    "torch",
    "torchaudio",
    "torchvision",
    "transformers",
    "onnxruntime",
    "onnxruntime-gpu",
)


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


def venv_is_healthy(python_executable: Path, expected: tuple[int, ...]) -> bool:
    if python_executable.is_file() is False:
        return False
    try:
        result = subprocess.run(
            [
                str(python_executable),
                "-c",
                "import sys; print('.'.join(map(str, sys.version_info[:3])))",
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            text=True,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    if result.returncode:
        return False
    try:
        actual = tuple(int(part) for part in result.stdout.strip().split("."))
    except ValueError:
        return False
    return actual[: len(expected)] == expected


def python_312_command() -> list[str | Path]:
    """Find a real Python 3.12 interpreter for the isolated TTS environment."""
    candidates: list[list[str | Path]] = []
    if sys.version_info[:2] == TTS_PYTHON:
        candidates.append([sys.executable])
    if os.name == "nt":
        launcher = shutil.which("py")
        if launcher:
            candidates.append([launcher, "-3.12"])
    else:
        python = shutil.which("python3.12")
        if python:
            candidates.append([python])

    for command in candidates:
        result = subprocess.run(
            [*map(str, command), "-c", "import sys; print(sys.version_info[:2])"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == "(3, 12)":
            return command
    raise SetupError(
        "Python 3.12 is required for the isolated Kokoro service. "
        "Install Python 3.12, ensure `py -3.12` works, and rerun setup.bat."
    )


def nvidia_gpu_names() -> list[str]:
    nvidia_smi = shutil.which('nvidia-smi')
    if nvidia_smi is None:
        return []
    result = subprocess.run(
        [nvidia_smi, '--query-gpu=name', '--format=csv,noheader'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        print('[setup] nvidia-smi could not query installed GPUs; skipping GPU-specific packages.')
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def install_cuda_pytorch(python_executable: Path) -> bool:
    """Install and verify CUDA-enabled PyTorch when an NVIDIA RTX GPU is present."""
    gpu_names = nvidia_gpu_names()
    rtx_names = [name for name in gpu_names if RTX_NAME.casefold() in name.casefold()]
    if not rtx_names:
        detected = ', '.join(gpu_names) if gpu_names else 'none'
        print(f'[setup] No {RTX_NAME} GPU detected ({detected}); Kokoro will use CPU PyTorch.')
        return False

    rtx_display = ', '.join(rtx_names)
    print(f'[setup] RTX GPU detected: {rtx_display}')
    print(f'[setup] Installing PyTorch with CUDA {CUDA_RUNTIME_VERSION} support.')
    run(
        [
            python_executable,
            '-m',
            'pip',
            'install',
            '--upgrade',
            '--index-url',
            CUDA_TORCH_INDEX,
            *CUDA_TORCH_PACKAGES,
        ]
    )
    verify = (
        'import torch, torchaudio, torchvision; '
        f'assert torch.__version__ == {CUDA_TORCH_VERSION!r}, torch.__version__; '
        f'assert torchaudio.__version__ == {CUDA_TORCHAUDIO_VERSION!r}, torchaudio.__version__; '
        f'assert torchvision.__version__ == {CUDA_TORCHVISION_VERSION!r}, torchvision.__version__; '
        f'assert torch.version.cuda == {CUDA_RUNTIME_VERSION!r}, torch.version.cuda; '
        'assert torch.cuda.is_available(), "CUDA is not available to PyTorch"; '
        'torch.ones(1, device="cuda").add_(1).item(); '
        'print(torch.__version__, torch.version.cuda, torch.cuda.get_device_name(0))'
    )
    run([python_executable, '-c', verify])
    return True


def remove_main_tts_dependencies(python_executable: Path) -> None:
    """Enforce that speech-model packages live only in `.venv-tts`."""
    print("[setup] Removing TTS-only packages from the main environment.")
    run([python_executable, "-m", "pip", "uninstall", "--yes", *MAIN_TTS_PACKAGES])


def in_active_environment() -> bool:
    return _ACTIVE_ENVIRONMENT


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
    if sys.version_info[:3] != REQUIRED_PYTHON:
        raise SetupError(
            f"Python {REQUIRED_PYTHON_TEXT} is required; "
            f"current interpreter is {sys.version.split()[0]}"
        )
    if not (ROOT / "requirements.txt").is_file():
        raise SetupError(f"requirements.txt was not found in {ROOT}")
    if not TTS_REQUIREMENTS.is_file():
        raise SetupError(f"Kokoro requirements were not found at {TTS_REQUIREMENTS}")
    if not (REACT_DIR / "package.json").is_file():
        raise SetupError(f"React project was not found in {REACT_DIR}")

    node = executable("node")
    npm = executable("npm")
    node_version = subprocess.check_output([node, "--version"], text=True).strip()
    print(f"[setup] Python {sys.version.split()[0]}")
    print(f"[setup] Node {node_version}")

    if in_active_environment():
        main_python = Path(sys.executable)
        print(f"[setup] Using active Python environment at {sys.prefix}")
    else:
        if not venv_is_healthy(VENV_PYTHON, REQUIRED_PYTHON):
            if VENV_DIR.exists():
                print(f"[setup] Removing virtual environment that does not use Python {REQUIRED_PYTHON_TEXT}")
                shutil.rmtree(VENV_DIR)
            print(f"[setup] Creating virtual environment at {VENV_DIR}")
            run([sys.executable, "-m", "venv", VENV_DIR])
        else:
            print(f"[setup] Reusing virtual environment at {VENV_DIR}")
        main_python = VENV_PYTHON

    tts_creator = python_312_command()
    if not venv_is_healthy(TTS_VENV_PYTHON, TTS_PYTHON):
        if TTS_VENV_DIR.exists():
            print(
                f"[setup] Removing TTS environment that does not use Python {TTS_PYTHON_TEXT}"
            )
            shutil.rmtree(TTS_VENV_DIR)
        print(
            f"[setup] Creating isolated Python {TTS_PYTHON_TEXT} TTS environment "
            f"at {TTS_VENV_DIR}"
        )
        run([*tts_creator, "-m", "venv", TTS_VENV_DIR])
    else:
        print(f"[setup] Reusing isolated TTS environment at {TTS_VENV_DIR}")

    run([main_python, "-m", "pip", "install", "--upgrade", "pip"])
    print("[setup] Installing main Python dependencies.")
    run([main_python, "-m", "pip", "install", "-r", ROOT / "requirements.txt"])
    remove_main_tts_dependencies(main_python)
    run([TTS_VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"])
    print("[setup] Installing isolated Kokoro dependencies; this may take several minutes.")
    install_cuda_pytorch(TTS_VENV_PYTHON)
    run([TTS_VENV_PYTHON, "-m", "pip", "install", "-r", TTS_REQUIREMENTS])
    run([npm, "install"], cwd=REACT_DIR)

    if not args.skip_verify:
        run([main_python, "-m", "pip", "check"])
        run([TTS_VENV_PYTHON, "-m", "pip", "check"])
        run([main_python, "-m", "compileall", "-q", ROOT / "python"])
        run([TTS_VENV_PYTHON, "-m", "compileall", "-q", TTS_ROOT])
        run(
            [main_python, "-m", "unittest", "backend.test_server", "-v"],
            cwd=ROOT / "python",
        )
        run(
            [TTS_VENV_PYTHON, "-m", "unittest", "discover", "-s", TTS_ROOT, "-p", "test_*.py"],
        )
        smoke_test = (
            "import sys, tkinter, numpy, pandas, pydantic, openai, anthropic; "
            f"sys.path.insert(0, {str(ROOT / 'python')!r}); "
            "import ollama_learning; "
            "from ollama_learning.qanda import QAGenerator; "
            "print('Python imports OK')"
        )
        run([main_python, "-c", smoke_test])
        tts_smoke_test = (
            "import sys, kokoro, torch; "
            "assert sys.version_info[:2] == (3, 12); "
            "print('Kokoro imports OK', torch.__version__)"
        )
        run([TTS_VENV_PYTHON, "-c", tts_smoke_test])
        run([main_python, ROOT / "python/qanda_launcher.py", "--help"], quiet=True)
        run([npm, "run", "typecheck"], cwd=REACT_DIR)
        run([npm, "run", "build"], cwd=REACT_DIR)

    print("\n[setup] Environment ready.")
    print("[setup] Start development: python run_app.py dev")
    if in_active_environment():
        print(f"[setup] Main dependencies installed in active environment: {sys.prefix}")
    else:
        activation = ".venv\\Scripts\\activate.bat" if os.name == "nt" else "source .venv/bin/activate"
        print(f"[setup] Activate Python: {activation}")
    tts_activation = (
        f"{TTS_VENV_DIR}\\Scripts\\activate.bat"
        if os.name == "nt"
        else f"source {TTS_VENV_DIR}/bin/activate"
    )
    print(f"[setup] Activate Kokoro Python: {tts_activation}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SetupError as error:
        print(f"\n[setup] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
