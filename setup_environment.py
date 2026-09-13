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
REQUIRED_PYTHON = (3, 14, 6)
REQUIRED_PYTHON_TEXT = ".".join(map(str, REQUIRED_PYTHON))


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
KOKORO_ONNX_VERSION = "0.6.1"
ONNX_GPU_VERSION = "1.26.0"
ONNX_GPU_PACKAGE = f"onnxruntime-gpu=={ONNX_GPU_VERSION}"
RTX_NAME = 'NVIDIA GeForce RTX'


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


def venv_is_healthy() -> bool:
    if VENV_PYTHON.is_file() is False:
        return False
    try:
        result = subprocess.run(
            [
                str(VENV_PYTHON),
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
    return result.returncode == 0 and result.stdout.strip() == REQUIRED_PYTHON_TEXT


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


def install_kokoro_onnx(python_executable: Path) -> None:
    """Install tested kokoro-onnx despite its conservative Python upper bound."""
    print(
        f"[setup] Installing kokoro-onnx {KOKORO_ONNX_VERSION} "
        "with its Python-version metadata override."
    )
    run(
        [
            python_executable,
            '-m',
            'pip',
            'install',
            '--upgrade',
            '--ignore-requires-python',
            f'kokoro-onnx=={KOKORO_ONNX_VERSION}',
        ]
    )
    verify = (
        'from importlib.metadata import version; import kokoro_onnx; '
        f'assert version("kokoro-onnx") == {KOKORO_ONNX_VERSION!r}; '
        'print("kokoro-onnx", version("kokoro-onnx"))'
    )
    run([python_executable, '-c', verify])


def install_cuda_pytorch(python_executable: Path) -> bool:
    """Install and verify CUDA-enabled PyTorch when an NVIDIA RTX GPU is present."""
    gpu_names = nvidia_gpu_names()
    rtx_names = [name for name in gpu_names if RTX_NAME.casefold() in name.casefold()]
    if not rtx_names:
        detected = ', '.join(gpu_names) if gpu_names else 'none'
        print(f'[setup] No {RTX_NAME} GPU detected ({detected}); skipping CUDA PyTorch.')
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


def install_gpu_onnxruntime(python_executable: Path) -> None:
    gpu_names = nvidia_gpu_names()
    rtx_names = [name for name in gpu_names if RTX_NAME.casefold() in name.casefold()]
    if not rtx_names:
        detected = ', '.join(gpu_names) if gpu_names else 'none'
        print(f'[setup] No {RTX_NAME} GPU detected ({detected}); using ONNX Runtime on CPU.')
        return

    rtx_display = ', '.join(rtx_names)
    print(f'[setup] RTX GPU detected for ONNX Runtime: {rtx_display}')
    print('[setup] Installing the CUDA 12.8 ONNX Runtime for Kokoro audio generation.')
    # kokoro-onnx declares a dependency on the distribution named
    # "onnxruntime", so its metadata must remain installed for `pip check`.
    # Reinstall the GPU distribution last because both wheels expose the same
    # import package. CUDA/cuDNN still come from PyTorch rather than duplicate
    # NVIDIA runtime packages.
    run(
        [
            python_executable,
            '-m',
            'pip',
            'uninstall',
            '--yes',
            'onnxruntime-gpu',
        ]
    )
    run(
        [
            python_executable,
            '-m',
            'pip',
            'install',
            '--upgrade',
            ONNX_GPU_PACKAGE,
        ]
    )
    verify = (
        'import torch; '
        'assert torch.cuda.is_available(), "CUDA is not available to PyTorch"; '
        'import onnxruntime as ort; '
        'ort.preload_dlls(); '
        'providers = ort.get_available_providers(); '
        'assert "CUDAExecutionProvider" in providers, providers; '
        'print(ort.__version__, providers)'
    )
    run([python_executable, '-c', verify])


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
    if not (REACT_DIR / "package.json").is_file():
        raise SetupError(f"React project was not found in {REACT_DIR}")

    node = executable("node")
    npm = executable("npm")
    node_version = subprocess.check_output([node, "--version"], text=True).strip()
    print(f"[setup] Python {sys.version.split()[0]}")
    print(f"[setup] Node {node_version}")

    if not venv_is_healthy():
        if VENV_DIR.exists():
            print(f"[setup] Removing virtual environment that does not use Python {REQUIRED_PYTHON_TEXT}")
            shutil.rmtree(VENV_DIR)
        print(f"[setup] Creating virtual environment at {VENV_DIR}")
        run([sys.executable, "-m", "venv", VENV_DIR])
    else:
        print(f"[setup] Reusing virtual environment at {VENV_DIR}")

    run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"])
    print("[setup] Installing Python dependencies; audio/ML packages may take several minutes.")
    run([VENV_PYTHON, "-m", "pip", "install", "-r", ROOT / "requirements.txt"])
    install_kokoro_onnx(VENV_PYTHON)
    run([npm, "install"], cwd=REACT_DIR)

    if install_cuda_pytorch(VENV_PYTHON):
        install_gpu_onnxruntime(VENV_PYTHON)

    if not args.skip_verify:
        run([VENV_PYTHON, "-m", "pip", "check"])
        run([VENV_PYTHON, "-m", "compileall", "-q", ROOT / "python"])
        run(
            [VENV_PYTHON, "-m", "unittest", "backend.test_server", "-v"],
            cwd=ROOT / "python",
        )
        smoke_test = (
            "import sys, tkinter, kokoro_onnx, numpy, pandas, pydantic, openai, anthropic; "
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
