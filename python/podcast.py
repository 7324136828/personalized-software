#!/usr/bin/env python3
"""Create resumable podcasts from all JSON files in the input folder.

Install: python -m pip install -r requirements.txt
Run:     python main.py
GPU:     python main.py --device cuda
Check:   python main.py --dry-run
WAV:     python main.py --format wav --device cpu

Voices come from cast[].voice_file. Directions are never spoken. [pause=N]
inserts N milliseconds BEFORE that scene's dialogue; an empty dialogue can
hold a pause between turns. Style keywords adjust speed only, not emotion.
Kokoro downloads pretrained model/voice files on first use (internet required).
CUDA is the default. Use --device auto to allow CPU fallback, or --device cpu.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import logging
import math
from pathlib import Path
import re
import subprocess
import tempfile
import wave


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_INPUT = PROJECT_ROOT / "input" / "podcast1.json"
DEFAULT_INPUT_DIR = PROJECT_ROOT / "input"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "podcasts"
DEFAULT_CHECKPOINT_DIR = PROJECT_ROOT / ".checkpoints" / "podcasts"
MODEL_REPO = "hexgrad/Kokoro-82M"
SAMPLE_RATE = 24_000
LOG = logging.getLogger("podcast")
PAUSE = re.compile(r"\[pause\s*=\s*(\d+)\]", re.IGNORECASE)
PACING = (("dramatic", 0.90), ("reflective", 0.93), ("calm", 0.96),
          ("upbeat", 1.04))


@dataclass(frozen=True)
class Turn:
    segment: str
    speaker: str
    voice: str
    text: str
    speed: float
    pause_ms: int


def required_text(obj: dict, key: str, context: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a nonempty string.")
    return value.strip()


def optional_text(obj: dict, key: str, context: str) -> str:
    value = obj.get(key, "")
    if not isinstance(value, str):
        raise ValueError(f"{context}.{key} must be a string.")
    return value.strip()


def pacing(style: str) -> float:
    for keyword, factor in PACING:
        if re.search(rf"\b{keyword}\b", style, re.IGNORECASE):
            return factor
    return 1.0


def direction_pause(directions: str) -> int | None:
    """None means no explicit pause; zero means an explicit zero-length pause."""
    matches = PAUSE.findall(directions)
    if re.search(r"\[pause\b", PAUSE.sub("", directions), re.IGNORECASE):
        raise ValueError(f"Invalid pause in {directions!r}; use [pause=400].")
    if matches:
        duration = sum(int(value) for value in matches)
        if duration > 60_000:
            raise ValueError("A scene's explicit pause must be at most 60000 ms.")
        return duration
    if re.search(r"\bpauses?\b", directions, re.IGNORECASE):
        return 350
    return None


def load_episode(path: Path) -> dict:
    episode = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(episode, dict):
        raise ValueError("The input JSON must be an object.")
    required_text(episode, "episode_title", "episode")
    optional_text(episode, "podcast_show", "episode")
    return episode


def plan_episode(episode: dict, input_dir: Path, speed: float = 1.0,
                 turn_pause: int = 250, segment_pause: int = 800,
                 use_style: bool = True) -> list[Turn]:
    cast = episode.get("cast")
    script = episode.get("script")
    if not isinstance(cast, list) or not cast:
        raise ValueError("cast must be a nonempty list.")
    if not isinstance(script, list) or not script:
        raise ValueError("script must be a nonempty list.")
    speakers = {}
    for index, member in enumerate(cast):
        context = f"cast[{index}]"
        if not isinstance(member, dict):
            raise ValueError(f"{context} must be an object.")
        speaker = required_text(member, "speaker_id", context)
        if speaker in speakers:
            raise ValueError(f"Duplicate speaker_id: {speaker}")
        voice = required_text(member, "voice_file", context)
        if voice.lower().endswith(".pt"):
            voice_path = Path(voice)
            if not voice_path.is_absolute():
                voice_path = input_dir / voice_path
            if not voice_path.is_file():
                raise ValueError(f"Voice file not found: {voice_path}")
            voice = str(voice_path.resolve())
        speakers[speaker] = (voice, optional_text(member, "style", context))

    turns = []
    pending_pause = None
    boundary_pause = 0
    previous_speaker = None
    for index, segment in enumerate(script):
        context = f"script[{index}]"
        if not isinstance(segment, dict):
            raise ValueError(f"{context} must be an object.")
        name = required_text(segment, "segment_name", context)
        scenes = segment.get("scenes")
        if not isinstance(scenes, list):
            raise ValueError(f"{context}.scenes must be a list.")
        if turns:
            boundary_pause = segment_pause
        for scene_index, scene in enumerate(scenes):
            location = f"{context}.scenes[{scene_index}]"
            if not isinstance(scene, dict):
                raise ValueError(f"{location} must be an object.")
            speaker = required_text(scene, "speaker_id", location)
            if speaker not in speakers:
                raise ValueError(f"{location}: unknown speaker {speaker!r}.")
            text = optional_text(scene, "dialogue", location)
            directions = optional_text(scene, "directions", location)
            pause = direction_pause(directions)
            if pause is not None:
                pending_pause = (pending_pause or 0) + pause
            if not text:
                continue
            voice, style = speakers[speaker]
            # A recognized scene cue overrides the speaker's usual pacing.
            factor = pacing(directions)
            if factor == 1.0:
                factor = pacing(style)
            automatic = turn_pause if previous_speaker not in (None, speaker) else 0
            gap = (pending_pause if pending_pause is not None
                   else max(boundary_pause, automatic))
            turns.append(Turn(name, speaker, voice, text,
                              speed * factor if use_style else speed, gap))
            previous_speaker = speaker
            pending_pause = None
            boundary_pause = 0
    if not turns:
        raise ValueError("The script contains no spoken dialogue.")
    if pending_pause:
        turns.append(Turn(turns[-1].segment, "", "", "", speed, pending_pause))
    return turns


def write_wav(turns: list[Turn], path: Path, pipeline) -> float:
    """Stream PCM chunks to disk, keeping memory independent of episode length."""
    import numpy as np

    frames = 0
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        for index, turn in enumerate(turns, 1):
            silence_frames = round(turn.pause_ms * SAMPLE_RATE / 1000)
            remaining = silence_frames
            while remaining:
                count = min(remaining, SAMPLE_RATE)
                output.writeframesraw(b"\0\0" * count)
                remaining -= count
            frames += silence_frames
            if not turn.text:
                continue
            LOG.info("[%d/%d] %s / %s (%s, speed %.2f)", index, len(turns),
                     turn.segment, turn.speaker, turn.voice, turn.speed)
            spoken_frames = 0
            try:
                for _, _, audio in pipeline(turn.text, voice=turn.voice, speed=turn.speed):
                    if audio is None:
                        continue
                    if hasattr(audio, "detach"):
                        audio = audio.detach().cpu().numpy()
                    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
                    if not np.isfinite(samples).all():
                        raise RuntimeError("Kokoro returned non-finite audio samples.")
                    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
                    output.writeframesraw(pcm.tobytes())
                    spoken_frames += pcm.size
                if not spoken_frames:
                    raise RuntimeError("Kokoro returned no audio for this dialogue.")
            except Exception as exc:
                raise RuntimeError(
                    f"Synthesis failed in {turn.segment!r}, speaker {turn.speaker!r}: {exc}"
                ) from exc
            frames += spoken_frames
    return frames / SAMPLE_RATE


def select_device(requested: str) -> str:
    """Check actual CUDA execution before downloading/loading the speech model."""
    if requested == "cpu":
        LOG.info("Using CPU for speech synthesis.")
        return "cpu"
    if requested not in ("auto", "cuda"):
        raise ValueError(f"Unsupported device: {requested}")

    import torch

    cuda_help = (
        "Install CUDA-enabled PyTorch in the Python environment running this script: "
        "python -m pip install --upgrade torch --index-url https://download.pytorch.org/whl/cu128. "
        "Also check your NVIDIA driver. Use --device cpu to run without CUDA."
    )
    try:
        if not torch.cuda.is_available():
            detail = ("This PyTorch installation is CPU-only."
                      if torch.version.cuda is None
                      else f"PyTorch CUDA {torch.version.cuda} cannot access an NVIDIA GPU.")
            raise RuntimeError(detail)
        # Availability alone does not guarantee this PyTorch build supports the
        # GPU architecture. Execute and synchronize a tiny kernel to check.
        torch.ones(1, device="cuda").add_(1).item()
        index = torch.cuda.current_device()
        properties = torch.cuda.get_device_properties(index)
        LOG.info("Using CUDA GPU %d: %s (%.1f GiB VRAM; PyTorch %s; CUDA %s)",
                 index, properties.name, properties.total_memory / (1024 ** 3),
                 torch.__version__, torch.version.cuda)
        return "cuda"
    except (RuntimeError, AssertionError) as exc:
        if requested == "cuda":
            raise RuntimeError(f"GPU startup check failed: {exc} {cuda_help}") from exc
        LOG.warning("CUDA unavailable: %s Falling back to CPU. %s", exc, cuda_help)
        return "cpu"


class LazyPipeline:
    """Share a model across the batch, loading it only for uncached speech."""

    def __init__(self, lang_code: str, device: str):
        self.lang_code = lang_code
        self.device = device
        self.pipeline = None

    def __call__(self, *args, **kwargs):
        if self.pipeline is None:
            try:
                from kokoro import KPipeline
            except ImportError as exc:
                raise RuntimeError(
                    "Missing audio dependencies. Run: python -m pip install -r requirements.txt"
                ) from exc
            selected_device = select_device(self.device)
            LOG.info("Loading Kokoro; first use may download model and voice files.")
            self.pipeline = KPipeline(lang_code=self.lang_code, repo_id=MODEL_REPO,
                                      device=selected_device)
        return self.pipeline(*args, **kwargs)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checkpoint_context(lang_code: str) -> dict:
    packages = {}
    for package in ("kokoro", "misaki", "torch"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = "not-installed"
    return {"schema": 1, "sample_rate": SAMPLE_RATE, "model": MODEL_REPO,
            "lang_code": lang_code, "packages": packages}


def checkpoint_valid(audio: Path, receipt: Path) -> bool:
    try:
        metadata = json.loads(receipt.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or metadata.get("sha256") != file_hash(audio):
            return False
        with wave.open(str(audio), "rb") as source:
            return (source.getframerate() == SAMPLE_RATE and source.getnchannels() == 1
                    and source.getsampwidth() == 2 and source.getcomptype() == "NONE"
                    and source.getnframes() == metadata.get("frames"))
    except (OSError, ValueError, EOFError, wave.Error):
        return False


def write_checkpointed_wav(turns: list[Turn], path: Path, pipeline,
                           checkpoint_dir: Path, lang_code: str,
                           restart: bool = False) -> float:
    """Commit complete turns atomically; interrupted turns are retried next run."""
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    context = checkpoint_context(lang_code)
    voice_hashes = {turn.voice: file_hash(Path(turn.voice)) for turn in turns
                    if turn.voice.lower().endswith(".pt")}
    frames = 0
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        for index, turn in enumerate(turns, 1):
            identity = {"context": context, "turn": asdict(turn),
                        "voice_hash": voice_hashes.get(turn.voice)}
            key = hashlib.sha256(json.dumps(identity, sort_keys=True,
                                            ensure_ascii=False).encode("utf-8")).hexdigest()
            cached = checkpoint_dir / f"{key}.wav"
            receipt = checkpoint_dir / f"{key}.checkpoint.json"
            if restart or not checkpoint_valid(cached, receipt):
                LOG.info("Checkpoint [%d/%d]: generating %s / %s",
                         index, len(turns), turn.segment, turn.speaker)
                with tempfile.TemporaryDirectory(prefix="pending-", dir=checkpoint_dir) as temp:
                    pending = Path(temp) / "turn.wav"
                    write_wav([turn], pending, pipeline)
                    with wave.open(str(pending), "rb") as audio:
                        count = audio.getnframes()
                    metadata = {"sha256": file_hash(pending), "frames": count,
                                "identity": identity}
                    pending_receipt = Path(temp) / "turn.checkpoint.json"
                    pending_receipt.write_text(json.dumps(metadata, indent=2,
                                                          ensure_ascii=False), encoding="utf-8")
                    pending.replace(cached)
                    pending_receipt.replace(receipt)
            else:
                LOG.info("Checkpoint [%d/%d]: reused %s / %s",
                         index, len(turns), turn.segment, turn.speaker)
            with wave.open(str(cached), "rb") as source:
                copied = 0
                while chunk := source.readframes(SAMPLE_RATE):
                    output.writeframesraw(chunk)
                    copied += len(chunk) // 2
                if copied != source.getnframes():
                    raise RuntimeError(f"Truncated checkpoint audio: {cached}")
                frames += copied
    return frames / SAMPLE_RATE


def render_episode(episode: dict, turns: list[Turn], output: Path,
                   lang_code: str, device: str, bitrate: str,
                   checkpoint_dir: Path | None = None, restart: bool = False,
                   pipeline=None) -> float:
    try:
        if output.suffix.lower() == ".mp3":
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError(
            "Missing audio dependencies. Run: python -m pip install -r requirements.txt"
        ) from exc

    if pipeline is None:
        pipeline = LazyPipeline(lang_code, device)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Publish only a completed file; failures leave existing output intact.
    with tempfile.TemporaryDirectory(prefix="kokoro-", dir=output.parent) as temp:
        wav_path = Path(temp) / "episode.wav"
        if checkpoint_dir is None:
            duration = write_wav(turns, wav_path, pipeline)
        else:
            duration = write_checkpointed_wav(turns, wav_path, pipeline,
                                              checkpoint_dir, lang_code, restart)
        completed = wav_path
        if output.suffix.lower() == ".mp3":
            completed = Path(temp) / "episode.mp3"
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav_path),
                 "-codec:a", "libmp3lame", "-b:a", bitrate,
                 "-metadata", f"title={episode['episode_title']}",
                 "-metadata", f"artist={episode.get('podcast_show', '')}", str(completed)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode:
                raise RuntimeError(f"MP3 encoding failed: {result.stderr.strip()}")
        completed.replace(output)
    return duration


def positive_speed(value: str) -> float:
    speed = float(value)
    if not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
        raise argparse.ArgumentTypeError("speed must be between 0.5 and 2.0")
    return speed


def milliseconds(value: str) -> int:
    duration = int(value)
    if not 0 <= duration <= 60_000:
        raise argparse.ArgumentTypeError("pause must be between 0 and 60000 ms")
    return duration


def discover_inputs(path: Path) -> list[Path]:
    if path.is_dir():
        inputs = sorted((item for item in path.iterdir()
                         if item.is_file() and item.suffix.lower() == ".json"),
                        key=lambda item: item.name.casefold())
    elif path.is_file() and path.suffix.lower() == ".json":
        inputs = [path]
    else:
        raise ValueError(f"Input must be an existing JSON file or folder: {path}")
    if not inputs:
        raise ValueError(f"No JSON files found in {path}")
    stems = [item.stem.casefold() for item in inputs]
    if len(set(stems)) != len(stems):
        raise ValueError("Input filenames would produce duplicate output names.")
    return inputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_DIR,
                        help="JSON file or folder to scan for *.json (default: input/)")
    parser.add_argument("--output", type=Path, help="Exact MP3/WAV path; requires exactly one input file")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--format", choices=("mp3", "wav"), default="mp3")
    parser.add_argument("--checkpoint-dir", type=Path, default=DEFAULT_CHECKPOINT_DIR)
    checkpoint_options = parser.add_mutually_exclusive_group()
    checkpoint_options.add_argument("--restart", action="store_true", help="Regenerate all turns, replacing checkpoints")
    checkpoint_options.add_argument("--no-checkpoint", action="store_true", help="Disable checkpoint reads and writes")
    parser.add_argument("--lang-code", choices=list("abefhijpz"), default="a")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="cuda",
                        help="cuda (default): require NVIDIA GPU; auto: allow CPU fallback; cpu: force CPU")
    parser.add_argument("--speed", type=positive_speed, default=1.0)
    parser.add_argument("--turn-pause", type=milliseconds, default=250, help="Speaker change gap in ms")
    parser.add_argument("--segment-pause", type=milliseconds, default=800, help="Segment gap in ms")
    parser.add_argument("--bitrate", choices=("128k", "192k", "256k", "320k"), default="192k")
    parser.add_argument("--no-style-pacing", action="store_true", help="Use the same speed for all hosts")
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview without loading Kokoro")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        inputs = discover_inputs(args.input)
        if args.output and len(inputs) != 1:
            raise ValueError("--output requires exactly one input file; use --output-dir for a batch.")
        if args.output and args.output.suffix.lower() not in (".mp3", ".wav"):
            raise ValueError("Output extension must be .mp3 or .wav.")
        pipeline = LazyPipeline(args.lang_code, args.device)
        failures = 0
        for index, source in enumerate(inputs, 1):
            output = args.output or args.output_dir / f"{source.stem}.{args.format}"
            LOG.info("File [%d/%d]: %s", index, len(inputs), source.name)
            try:
                if output.resolve() == source.resolve():
                    raise ValueError("Input and output paths must differ.")
                episode = load_episode(source)
                turns = plan_episode(episode, source.parent, args.speed,
                                     args.turn_pause, args.segment_pause, not args.no_style_pacing)
                LOG.info("%s: %d segments, %d spoken turns", episode["episode_title"],
                         len(episode["script"]), sum(bool(turn.text) for turn in turns))
                if args.dry_run:
                    for turn in turns:
                        LOG.info("%s | %s | %s | speed=%.2f | pause=%d ms | %s",
                                 turn.segment, turn.speaker, turn.voice, turn.speed,
                                 turn.pause_ms, turn.text[:90])
                    LOG.info("Validation passed. Output would be %s", output)
                    continue
                source_key = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:16]
                checkpoint_dir = (None if args.no_checkpoint else
                                  args.checkpoint_dir / f"{source.stem}-{source_key}")
                duration = render_episode(episode, turns, output, args.lang_code, args.device,
                                          args.bitrate, checkpoint_dir, args.restart, pipeline)
                LOG.info("Saved %s (%.1f minutes)", output.resolve(), duration / 60)
            except (OSError, ValueError, RuntimeError, ImportError, EOFError, wave.Error) as exc:
                failures += 1
                LOG.error("%s: %s", source.name, exc)
        LOG.info("Batch complete: %d succeeded, %d failed.", len(inputs) - failures, failures)
        return 1 if failures else 0
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        LOG.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        LOG.warning("Cancelled. Completed checkpoints are retained; rerun to resume.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
