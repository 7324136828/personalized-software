#!/usr/bin/env python3
"""Translate one or more UTF-8 text files into English with Ollama or OpenAI."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import socket
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# DEFAULT_OLLAMA_MODEL = "gemma4:e4b"
DEFAULT_OLLAMA_MODEL = "gpt-oss:20b-cloud"
DEFAULT_OPENAI_MODEL = "gpt-5-nano"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_CONTEXT_WINDOW = 4_096
DEFAULT_RETRIES = 5
DEFAULT_CHECKPOINT = Path(".translation_checkpoint.json")
DEFAULT_CONFIG = Path("config.json")
DEFAULT_OUTPUT_DIR = Path("output")
CHECKPOINT_VERSION = 1
PROMPT_VERSION = 2
CJK_SOURCE_CODES = frozenset({"zh", "ja", "ko", "yue"})
IGNORED_CHECKPOINT_SETTINGS = frozenset({"model", "provider", "host", "sequence"})


@dataclass(frozen=True)
class ModelConfig:
    model: str
    provider: str
    retries: int


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Translate .txt files into English using Ollama or OpenAI."
    )
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help=(
            "Optional .txt files or folders. Folders are scanned recursively; "
            "default: .\\input"
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output path (only valid when translating one input file).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Directory for translated files; names will end in _en.txt "
            f"(default: .\\{DEFAULT_OUTPUT_DIR})."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=("ollama", "openai"),
        default="ollama",
        help="Translation API provider (default: ollama).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Model sequence configuration file (default: {DEFAULT_CONFIG}).",
    )
    parser.add_argument(
        "--model",
        help=(
            f"Model name (defaults: {DEFAULT_OLLAMA_MODEL} for Ollama, "
            f"{DEFAULT_OPENAI_MODEL} for OpenAI)."
        ),
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_OLLAMA_HOST,
        help=f"Ollama server URL (default: {DEFAULT_OLLAMA_HOST}).",
    )
    parser.add_argument(
        "--source-language",
        default="Chinese",
        help="Source language name (default: Chinese).",
    )
    parser.add_argument(
        "--source-code",
        default="zh",
        help="Source language code used by TranslateGemma (default: zh).",
    )
    parser.add_argument(
        "--style",
        choices=("natural", "literal"),
        default="natural",
        help="Prefer natural English or a more literal translation (default: natural).",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="Input text encoding (default: utf-8-sig, which also accepts UTF-8).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        metavar="CHARS",
        help=(
            "Maximum source characters per API request. By default this is "
            "calculated from the provider's planning context window."
        ),
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        metavar="TOKENS",
        help=(
            "Maximum output tokens per API request. The default is -1 "
            "(no explicit limit; the model or server decides when to stop)."
        ),
    )
    parser.add_argument(
        "--context-window",
        type=int,
        metavar="TOKENS",
        help=(
            "Context window used for chunk planning. It is also sent to Ollama; "
            "by default Ollama's active context is detected via /api/ps."
        ),
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=(
            "Retries after API failures. Ollama retries every Ollama error; OpenAI "
            f"retries temporary failures (default: {DEFAULT_RETRIES})."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        metavar="SECONDS",
        help="Timeout for each API request (default: 600).",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=DEFAULT_CHECKPOINT,
        help=f"Progress file used for resume support (default: {DEFAULT_CHECKPOINT}).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing translated output file.",
    )
    parser.add_argument(
        "--skip-completed",
        action="store_true",
        help="Skip completed checkpoint outputs even if their contents were modified.",
    )
    args = parser.parse_args(argv)
    if args.output and args.output_dir:
        parser.error("--output and --output-dir cannot be used together")
    if args.chunk_size is not None and args.chunk_size < 100:
        parser.error("--chunk-size must be at least 100 characters")
    if args.max_output_tokens is not None and args.max_output_tokens < -1:
        parser.error("--max-output-tokens must be -1 (no explicit limit) or positive")
    if args.max_output_tokens == 0:
        parser.error("--max-output-tokens cannot be zero")
    if args.context_window is not None and args.context_window < 1_024:
        parser.error("--context-window must be at least 1024 tokens")
    if args.retries < 0:
        parser.error("--retries cannot be negative")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def load_model_sequence(path: Path, args: argparse.Namespace) -> list[ModelConfig]:
    """Load the ordered model fallback sequence, or use the CLI model."""
    default_model = (
        DEFAULT_OPENAI_MODEL if args.provider == "openai" else DEFAULT_OLLAMA_MODEL
    )
    if args.model is not None or not path.exists():
        return [ModelConfig(args.model or default_model, args.provider, args.retries)]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read config {path}: {exc}") from exc

    entries = data.get("sequences") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"Config {path} must contain a non-empty 'sequences' list.")

    sequence: list[ModelConfig] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Config sequence entry {index} must be an object.")
        model = entry.get("model")
        provider = entry.get("provider", "ollama")
        retries = entry.get("retries", args.retries)
        if (
            not isinstance(model, str)
            or not model.strip()
            or provider not in {"ollama", "openai"}
            or not isinstance(retries, int)
            or isinstance(retries, bool)
            or retries < 0
        ):
            raise ValueError(
                f"Config sequence entry {index} must have a model, provider "
                "of 'ollama' or 'openai', and non-negative integer retries."
            )
        sequence.append(ModelConfig(model.strip(), provider, retries))
    return sequence


def collect_input_files(paths: Iterable[Path]) -> list[Path]:
    """Expand inputs and return unique source files from smallest to largest."""
    files: list[Path] = []
    seen: set[Path] = set()

    for path in paths:
        if not path.exists():
            raise ValueError(f"Input path does not exist: {path}")

        if path.is_dir():
            candidates = sorted(
                (
                    candidate
                    for candidate in path.rglob("*")
                    if candidate.is_file()
                    and candidate.suffix.lower() == ".txt"
                    and not candidate.stem.lower().endswith("_en")
                ),
                key=lambda candidate: str(candidate).casefold(),
            )
        elif path.is_file():
            if path.suffix.lower() != ".txt":
                raise ValueError(f"Input must be a .txt file or folder: {path}")
            candidates = [path]
        else:
            raise ValueError(f"Input is not a regular file or folder: {path}")

        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved not in seen:
                files.append(candidate)
                seen.add(resolved)

    if not files:
        raise ValueError("No source .txt files were found.")

    try:
        return sorted(
            files,
            key=lambda candidate: (
                candidate.stat().st_size,
                str(candidate.resolve()).casefold(),
            ),
        )
    except OSError as exc:
        raise ValueError(f"Could not determine an input file size: {exc}") from exc


def split_long_line(line: str, max_chars: int) -> list[str]:
    """Split an unusually long line, preferring sentence punctuation."""
    parts: list[str] = []
    remaining = line
    punctuation = ("。", "！", "？", ".", "!", "?", ";", "；", ",", "，", " ")

    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        cut = max(window.rfind(mark) for mark in punctuation)
        if cut < max_chars // 2:
            cut = max_chars
        else:
            cut += 1
        parts.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()

    if remaining:
        parts.append(remaining)
    return parts or [""]


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Group complete lines into chunks small enough for reliable API calls."""
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for line in text.splitlines():
        for fragment in split_long_line(line, max_chars):
            added_length = len(fragment) + (1 if current else 0)
            if current and current_length + added_length > max_chars:
                chunk = "\n".join(current)
                if chunk.strip():
                    chunks.append(chunk)
                current = []
                current_length = 0

            current.append(fragment)
            current_length += len(fragment) + (1 if len(current) > 1 else 0)

    if current:
        chunk = "\n".join(current)
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def translation_prompt(
    text: str,
    source_language: str,
    source_code: str,
    style: str,
) -> str:
    """Build the prompt format recommended for TranslateGemma."""
    style_instruction = (
        "Use fluent, natural English while preserving the original meaning and tone."
        if style == "natural"
        else "Translate closely and literally while still producing grammatical English."
    )
    return (
        f"You are a professional {source_language} ({source_code}) to English (en) "
        "translator. Your goal is to accurately convey the meaning and nuances of the "
        f"original {source_language} text while adhering to English grammar, vocabulary, "
        "and cultural sensitivities.\n"
        "Return exactly one valid JSON object and nothing else. Do not use a Markdown "
        "code fence. Use exactly this schema: "
        '{"translated_text": "English translation"}. '
        "Put the complete translation in translated_text and encode line breaks and "
        "quotation marks with valid JSON escaping. Do not return additional keys or "
        "additional JSON objects.\n"
        f"{style_instruction}\n"
        "Preserve headings, lists, paragraph boundaries, and line breaks as closely as "
        "possible. Keep names, technical terms, numbers, and formatting accurate.\n"
        f"Please translate the following {source_language} text into English:\n\n\n{text}"
    )


def extract_translated_text(response_text: str) -> str:
    """Extract translated_text from exactly one embedded JSON object."""
    decoder = json.JSONDecoder()
    json_values: list[object] = []
    cursor = 0

    while cursor < len(response_text):
        if response_text[cursor] not in "{[":
            cursor += 1
            continue
        try:
            value, end = decoder.raw_decode(response_text, cursor)
        except json.JSONDecodeError:
            cursor += 1
            continue
        json_values.append(value)
        if len(json_values) > 1:
            return response_text
        cursor = end

    if len(json_values) == 1:
        value = json_values[0]
        if isinstance(value, dict) and isinstance(value.get("translated_text"), str):
            return value["translated_text"]
    return response_text


class TranslationAPIError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class OllamaError(TranslationAPIError):
    pass


class OpenAIAPIError(TranslationAPIError):
    pass


def ollama_base_url(host: str) -> str:
    base_url = host.rstrip("/")
    return base_url[:-4] if base_url.endswith("/api") else base_url


def active_model_context_window(host: str, model: str, timeout: float) -> int | None:
    """Return the selected model's allocated context from Ollama's /api/ps."""
    request = Request(f"{ollama_base_url(host)}/api/ps", method="GET")
    try:
        with urlopen(request, timeout=min(timeout, 5.0)) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None

    requested = model.casefold()
    requested_with_tag = requested if ":" in requested else f"{requested}:latest"
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return None

    for loaded in models:
        if not isinstance(loaded, dict):
            continue
        names = {loaded.get("name"), loaded.get("model")}
        normalized_names = {
            name.casefold() if ":" in name else f"{name.casefold()}:latest"
            for name in names
            if isinstance(name, str)
        }
        context_length = loaded.get("context_length")
        if requested_with_tag in normalized_names and isinstance(context_length, int):
            return context_length if context_length > 0 else None
    return None


def resolve_translation_limits(args: argparse.Namespace) -> None:
    """Populate automatic context, chunk, and output limits on parsed arguments."""
    explicit_context_window = args.context_window is not None
    if explicit_context_window:
        context_window = args.context_window
    elif args.provider == "ollama":
        context_window = active_model_context_window(args.host, args.model, args.timeout)
        if context_window is None:
            context_window = DEFAULT_CONTEXT_WINDOW
            print(
                f"Context: {args.model} is not currently loaded; using the conservative "
                f"{context_window}-token planning default. Use --context-window to override.",
                file=sys.stderr,
            )
    else:
        context_window = DEFAULT_CONTEXT_WINDOW
        print(
            f"Context: using the conservative {context_window}-token planning default "
            "for OpenAI. Use --context-window to override.",
            file=sys.stderr,
        )

    prompt_reserve = max(128, context_window // 16)
    safety_reserve = max(128, context_window // 16)
    max_output_tokens = args.max_output_tokens if args.max_output_tokens is not None else -1
    output_token_reserve = (
        context_window // 2 if max_output_tokens == -1 else max_output_tokens
    )
    input_token_budget = (
        context_window - prompt_reserve - safety_reserve - output_token_reserve
    )
    if input_token_budget < 100:
        raise ValueError(
            f"The {context_window}-token context window leaves too little room for input "
            f"with --max-output-tokens {max_output_tokens}. Lower the output limit or "
            "increase --context-window."
        )

    source_code = args.source_code.casefold().split("-", 1)[0]
    chars_per_token = 1 if source_code in CJK_SOURCE_CODES else 3
    automatic_chunk_size = input_token_budget * chars_per_token

    args.context_window = context_window
    args.configure_context_window = explicit_context_window
    args.max_output_tokens = max_output_tokens
    args.chunk_size = args.chunk_size or automatic_chunk_size

    output_description = (
        "no explicit output token limit" if max_output_tokens == -1
        else f"up to {max_output_tokens} output tokens"
    )
    print(
        f"Context: {context_window} tokens for {args.model}; chunk size "
        f"{args.chunk_size} source characters; {output_description}.",
        file=sys.stderr,
    )


def ollama_chat(
    host: str,
    *,
    model: str,
    prompt: str,
    max_output_tokens: int,
    context_window: int | None,
    timeout: float,
) -> str:
    """Send one non-streaming request to Ollama's local chat endpoint."""
    base_url = ollama_base_url(host)
    url = f"{base_url}/api/chat"
    options: dict[str, object] = {"temperature": 0}
    if max_output_tokens != -1:
        options["num_predict"] = max_output_tokens
    if context_window is not None:
        options["num_ctx"] = context_window
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": options,
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        response = urlopen(request, timeout=timeout)
        with response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        try:
            error_data = json.loads(error_body)
            error_message = (
                error_data.get("error", error_body)
                if isinstance(error_data, dict)
                else error_body
            )
        except json.JSONDecodeError:
            error_message = error_body
        details = f": {error_message}" if error_message else ""
        hint = f" Run 'ollama pull {model}' first." if exc.code == 404 else ""
        raise OllamaError(
            f"Ollama returned HTTP {exc.code}{details}.{hint}",
            retryable=exc.code == 429 or exc.code >= 500,
        ) from exc
    except URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise OllamaError(
                f"Ollama request timed out after {timeout:g} seconds.", retryable=True
            ) from exc
        raise OllamaError(
            f"Could not connect to Ollama at {base_url}. Is Ollama running? ({exc.reason})"
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise OllamaError(
            f"Ollama request timed out after {timeout:g} seconds.", retryable=True
        ) from exc
    except Exception as exc:
        raise OllamaError(f"Ollama request failed: {exc}") from exc

    try:
        data = json.loads(response_body)
        returned_text = data["message"]["content"]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
        raise OllamaError("Ollama returned an invalid chat response.") from exc
    if not isinstance(returned_text, str) or not returned_text.strip():
        raise OllamaError("Ollama returned an empty translation.")
    translated_text = extract_translated_text(returned_text)
    if not translated_text.strip():
        raise OllamaError("Ollama returned an empty translated_text value.")
    return translated_text


def create_openai_client(timeout: float) -> object:
    """Create an OpenAI client while keeping the SDK optional for Ollama users."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIAPIError(
            "OpenAI support requires the 'openai' package. Install it with "
            "'python -m pip install openai'."
        ) from exc

    try:
        return OpenAI(timeout=timeout, max_retries=0)
    except Exception as exc:
        raise OpenAIAPIError(f"Could not initialize the OpenAI client: {exc}") from exc


def openai_response(
    client: object,
    *,
    model: str,
    prompt: str,
    max_output_tokens: int,
) -> str:
    """Send one request through the OpenAI Responses API."""
    request_options: dict[str, object] = {"model": model, "input": prompt}
    if max_output_tokens != -1:
        request_options["max_output_tokens"] = max_output_tokens

    try:
        responses = getattr(client, "responses")
        response = responses.create(**request_options)
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        retryable = (
            status_code in {408, 409, 429}
            or (isinstance(status_code, int) and status_code >= 500)
            or type(exc).__name__ in {"APIConnectionError", "APITimeoutError"}
        )
        raise OpenAIAPIError(
            f"OpenAI API request failed: {exc}", retryable=retryable
        ) from exc

    returned_text = getattr(response, "output_text", None)
    if not isinstance(returned_text, str) or not returned_text.strip():
        raise OpenAIAPIError("OpenAI returned an empty or invalid response.")
    translated_text = extract_translated_text(returned_text)
    if not translated_text.strip():
        raise OpenAIAPIError("OpenAI returned an empty translated_text value.")
    return translated_text


def translate_chunk(
    chunk: str,
    *,
    host: str,
    openai_client: object | None,
    models: list[ModelConfig],
    source_language: str,
    source_code: str,
    style: str,
    max_output_tokens: int,
    context_window: int | None,
    timeout: float,
) -> str:
    errors: list[str] = []
    prompt = translation_prompt(chunk, source_language, source_code, style)
    for model_config in models:
        for attempt in range(model_config.retries + 1):
            try:
                if model_config.provider == "openai":
                    if openai_client is None:
                        raise AssertionError("OpenAI client was not initialized")
                    return openai_response(
                        openai_client,
                        model=model_config.model,
                        prompt=prompt,
                        max_output_tokens=max_output_tokens,
                    )
                return ollama_chat(
                    host,
                    model=model_config.model,
                    prompt=prompt,
                    max_output_tokens=max_output_tokens,
                    context_window=context_window,
                    timeout=timeout,
                )
            except TranslationAPIError as exc:
                errors.append(f"{model_config.provider}/{model_config.model}: {exc}")
                should_retry = isinstance(exc, OllamaError) or exc.retryable
                if should_retry and attempt < model_config.retries:
                    delay = min(2**attempt, 20) + random.random()
                    print(
                        f"  {model_config.provider.capitalize()} error for {model_config.model} "
                        f"(attempt {attempt + 1}/{model_config.retries + 1}): {exc} "
                        f"Retrying in {delay:.1f}s...",
                        file=sys.stderr,
                    )
                    time.sleep(delay)
                else:
                    print(
                        f"  {model_config.provider.capitalize()} model {model_config.model} "
                        "exhausted; trying the next configured model.",
                        file=sys.stderr,
                    )

    raise TranslationAPIError(
        "All configured translation models failed: " + " | ".join(errors)
    )


def output_path_for(input_path: Path, args: argparse.Namespace) -> Path:
    if args.output:
        return args.output
    filename = f"{input_path.stem}_en.txt"
    output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    return output_dir / filename


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path_key(path: Path) -> str:
    """Return a stable, readable checkpoint key for a path."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    """Write text through a neighboring temporary file, then replace atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(text, encoding="utf-8")
    temporary_path.replace(path)


def load_checkpoint(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": CHECKPOINT_VERSION, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read checkpoint {path}: {exc}") from exc
    if (
        not isinstance(data, dict)
        or data.get("version") != CHECKPOINT_VERSION
        or not isinstance(data.get("files"), dict)
    ):
        raise ValueError(
            f"Checkpoint {path} has an unsupported or invalid format. "
            "Move or delete it to start a new checkpoint."
        )
    return data


def save_checkpoint(path: Path, checkpoint: dict[str, object]) -> None:
    atomic_write_text(
        path,
        json.dumps(checkpoint, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def translation_settings(
    args: argparse.Namespace,
    output_path: Path,
    models: list[ModelConfig],
) -> dict[str, object]:
    """Return every setting that can affect a resumed translation."""
    return {
        "prompt_version": PROMPT_VERSION,
        "provider": args.provider,
        "model": args.model,
        "sequence": [model.__dict__ for model in models],
        "host": args.host.rstrip("/") if args.provider == "ollama" else None,
        "source_language": args.source_language,
        "source_code": args.source_code,
        "style": args.style,
        "encoding": args.encoding,
        "chunk_size": args.chunk_size,
        "max_output_tokens": args.max_output_tokens,
        "context_window": args.context_window,
        "output": path_key(output_path),
    }


def checkpoint_entry_matches(
    entry: object,
    *,
    source_sha256: str,
    settings: dict[str, object],
) -> bool:
    """Match a checkpoint without tying resume state to its saved model."""
    if not isinstance(entry, dict):
        return False
    saved_settings = entry.get("settings")
    if not isinstance(saved_settings, dict):
        return False

    comparable_saved_settings = {
        key: value
        for key, value in saved_settings.items()
        if key not in IGNORED_CHECKPOINT_SETTINGS
    }
    comparable_current_settings = {
        key: value
        for key, value in settings.items()
        if key not in IGNORED_CHECKPOINT_SETTINGS
    }
    return (
        entry.get("source_sha256") == source_sha256
        and comparable_saved_settings == comparable_current_settings
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_paths = args.inputs or [Path("input")]

    try:
        models = load_model_sequence(args.config, args)
        args.model = models[0].model
        args.provider = models[0].provider
        resolve_translation_limits(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        input_files = collect_input_files(input_paths)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.output and len(input_files) != 1:
        print(
            "Error: --output can only be used when exactly one source file is selected.",
            file=sys.stderr,
        )
        return 2

    planned_outputs = [output_path_for(path, args) for path in input_files]
    normalized_outputs = [path.resolve() for path in planned_outputs]
    if len(set(normalized_outputs)) != len(normalized_outputs):
        print(
            "Error: two inputs would write to the same output path. "
            "Rename one input or translate it separately with --output.",
            file=sys.stderr,
        )
        return 2

    for input_path, output_path in zip(input_files, planned_outputs):
        if input_path.resolve() == output_path.resolve():
            print(f"Error: refusing to overwrite the input file: {input_path}", file=sys.stderr)
            return 2

    openai_client: object | None = None
    if any(model.provider == "openai" for model in models):
        try:
            openai_client = create_openai_client(args.timeout)
        except OpenAIAPIError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

    try:
        checkpoint = load_checkpoint(args.checkpoint)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    checkpoint_files = checkpoint["files"]
    assert isinstance(checkpoint_files, dict)

    completed_count = 0
    skipped_count = 0

    for input_path, output_path in zip(input_files, planned_outputs):
        try:
            source_bytes = input_path.read_bytes()
            source_text = source_bytes.decode(args.encoding)
        except (OSError, UnicodeError, LookupError) as exc:
            print(f"Error reading {input_path}: {exc}", file=sys.stderr)
            return 1

        source_key = path_key(input_path)
        source_sha256 = sha256_bytes(source_bytes)
        settings = translation_settings(args, output_path, models)
        existing_entry = checkpoint_files.get(source_key)
        entry_matches = checkpoint_entry_matches(
            existing_entry,
            source_sha256=source_sha256,
            settings=settings,
        )

        if (
            not args.overwrite
            and entry_matches
            and isinstance(existing_entry, dict)
            and existing_entry.get("status") == "completed"
            and output_path.exists()
        ):
            expected_output_sha256 = existing_entry.get("output_sha256")
            actual_output_sha256 = sha256_bytes(output_path.read_bytes())
            if (
                isinstance(expected_output_sha256, str)
                and expected_output_sha256 != actual_output_sha256
            ):
                if args.skip_completed:
                    print(
                        f"Checkpoint: completed output was modified, skipping {input_path} "
                        f"(--skip-completed): {output_path}",
                        file=sys.stderr,
                    )
                    skipped_count += 1
                    continue
                print(
                    f"Error: completed output was modified: {output_path}. "
                    "Use --overwrite to translate it again.",
                    file=sys.stderr,
                )
                return 2
            print(f"Checkpoint: already completed, skipping {input_path}", file=sys.stderr)
            skipped_count += 1
            continue

        in_progress_match = (
            not args.overwrite
            and entry_matches
            and isinstance(existing_entry, dict)
            and existing_entry.get("status") == "in_progress"
        )

        if output_path.exists() and not args.overwrite and not in_progress_match:
            if existing_entry is None:
                now = utc_now()
                checkpoint_files[source_key] = {
                    "status": "completed",
                    "source_sha256": source_sha256,
                    "settings": settings,
                    "output_sha256": sha256_bytes(output_path.read_bytes()),
                    "completed_at": now,
                    "updated_at": now,
                    "imported_existing_output": True,
                }
                try:
                    save_checkpoint(args.checkpoint, checkpoint)
                except OSError as exc:
                    print(f"Error writing checkpoint {args.checkpoint}: {exc}", file=sys.stderr)
                    return 1
                print(
                    f"Checkpoint: existing output recorded, skipping {input_path}",
                    file=sys.stderr,
                )
                skipped_count += 1
                continue
            print(
                f"Error: {output_path} does not match the current source/settings checkpoint. "
                "Use --overwrite to translate it again.",
                file=sys.stderr,
            )
            return 2

        chunks = chunk_text(source_text, args.chunk_size)

        translated_chunks: list[str] = []
        if in_progress_match and isinstance(existing_entry, dict):
            saved_chunks = existing_entry.get("translated_chunks")
            saved_total = existing_entry.get("total_chunks")
            if (
                isinstance(saved_chunks, list)
                and all(isinstance(chunk, str) for chunk in saved_chunks)
                and saved_total == len(chunks)
                and len(saved_chunks) <= len(chunks)
            ):
                translated_chunks = list(saved_chunks)

        now = utc_now()
        progress_entry: dict[str, object] = {
            "status": "in_progress",
            "source_sha256": source_sha256,
            "settings": settings,
            "total_chunks": len(chunks),
            "completed_chunks": len(translated_chunks),
            "translated_chunks": translated_chunks,
            "started_at": (
                existing_entry.get("started_at", now)
                if in_progress_match and isinstance(existing_entry, dict)
                else now
            ),
            "updated_at": now,
        }
        checkpoint_files[source_key] = progress_entry

        try:
            save_checkpoint(args.checkpoint, checkpoint)
        except OSError as exc:
            print(f"Error writing checkpoint {args.checkpoint}: {exc}", file=sys.stderr)
            return 1

        if chunks and len(translated_chunks) == len(chunks):
            print(
                f"Finalizing {input_path}; all {len(chunks)} chunk(s) were checkpointed...",
                file=sys.stderr,
            )
        elif translated_chunks:
            print(
                f"Resuming {input_path} at chunk {len(translated_chunks) + 1}/"
                f"{len(chunks)}...",
                file=sys.stderr,
            )
        elif chunks:
            print(f"Translating {input_path} ({len(chunks)} chunk(s))...", file=sys.stderr)
        else:
            print(f"Processing empty file: {input_path}", file=sys.stderr)

        try:
            for index in range(len(translated_chunks), len(chunks)):
                if len(chunks) > 1:
                    print(f"  Chunk {index + 1}/{len(chunks)}", file=sys.stderr)
                translated_chunks.append(
                    translate_chunk(
                        chunks[index],
                        host=args.host,
                        openai_client=openai_client,
                        models=models,
                        source_language=args.source_language,
                        source_code=args.source_code,
                        style=args.style,
                        max_output_tokens=args.max_output_tokens,
                        context_window=(
                            args.context_window
                            if args.configure_context_window
                            else None
                        ),
                        timeout=args.timeout,
                    )
                )
                progress_entry["completed_chunks"] = len(translated_chunks)
                progress_entry["translated_chunks"] = translated_chunks
                progress_entry["updated_at"] = utc_now()
                save_checkpoint(args.checkpoint, checkpoint)
        except Exception as exc:
            progress_entry["last_error"] = str(exc)
            progress_entry["updated_at"] = utc_now()
            try:
                save_checkpoint(args.checkpoint, checkpoint)
            except OSError as checkpoint_exc:
                print(
                    f"Additionally failed to update checkpoint: {checkpoint_exc}",
                    file=sys.stderr,
                )
            print(f"Error translating {input_path}: {exc}", file=sys.stderr)
            return 1

        translated_text = "\n".join(translated_chunks) + ("\n" if chunks else "")

        try:
            atomic_write_text(output_path, translated_text)
        except OSError as exc:
            print(f"Error writing {output_path}: {exc}", file=sys.stderr)
            return 1

        completed_at = utc_now()
        checkpoint_files[source_key] = {
            "status": "completed",
            "source_sha256": source_sha256,
            "settings": settings,
            "total_chunks": len(chunks),
            "completed_chunks": len(chunks),
            "output_sha256": sha256_bytes(output_path.read_bytes()),
            "started_at": progress_entry["started_at"],
            "completed_at": completed_at,
            "updated_at": completed_at,
        }
        try:
            save_checkpoint(args.checkpoint, checkpoint)
        except OSError as exc:
            print(f"Error writing checkpoint {args.checkpoint}: {exc}", file=sys.stderr)
            return 1
        print(f"Wrote {output_path}", file=sys.stderr)
        completed_count += 1

    print(
        f"Finished: {completed_count} translated, {skipped_count} skipped from checkpoint.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
