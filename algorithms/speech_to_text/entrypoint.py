"""ToothFairy4M speech-to-text algorithm entrypoint.

This implementation transcribes a single audio input using Whisper and emits one
text output named "transcription".
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Tuple

import whisper


_AUDIO_EXTENSIONS = (
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
    ".webm",
    ".mp4",
    ".aac",
    ".wma",
    ".opus",
)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_output_manifest(output_manifest_path: str, outputs: Dict[str, Any]) -> None:
    Path(output_manifest_path).write_text(
        json.dumps({"version": 1, "outputs": outputs}, indent=2) + "\n",
        encoding="utf-8",
    )


def _pick_primary_input(inputs: Dict[str, Any]) -> Tuple[str, str]:
    for preferred_key in ("input", "primary", "audio", "file_0"):
        candidate = inputs.get(preferred_key)
        if isinstance(candidate, str) and candidate.strip():
            return preferred_key, candidate.strip()

    for key, value in inputs.items():
        if isinstance(value, str) and value.strip():
            return str(key), value.strip()

    raise SystemExit("Input manifest contains no usable input path")


def _pick_first_source_key(manifest_raw: Dict[str, Any]) -> str:
    source_keys = manifest_raw.get("source_keys")
    if isinstance(source_keys, list):
        for value in source_keys:
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _sanitize_relpath(path_value: str) -> str:
    normalized = (path_value or "").replace("\\", "/").lstrip("/")
    parts = [segment for segment in normalized.split("/") if segment not in {"", ".", ".."}]
    return "/".join(parts)


def _convert_raw_to_processed_path(path_value: str) -> str:
    normalized = (path_value or "").replace("\\", "/")
    if "/raw/" in normalized:
        return normalized.replace("/raw/", "/processed/", 1)
    if normalized.startswith("raw/"):
        return "processed/" + normalized[len("raw/") :]
    if normalized.startswith("/raw/"):
        return "/processed/" + normalized[len("/raw/") :]
    return normalized


def _transcription_relpath_from_reference(reference_path: str) -> str:
    converted = _convert_raw_to_processed_path(reference_path)
    converted_lower = converted.lower()
    root, ext = os.path.splitext(converted)

    if converted_lower.endswith(_AUDIO_EXTENSIONS):
        target = f"{root}_transcription.txt"
    elif ext:
        target = f"{root}_transcription.txt"
    else:
        target = f"{converted}_transcription.txt"

    cleaned = _sanitize_relpath(target)
    return cleaned or "transcription.txt"


class SpeechToTextAlgorithm:
    def __init__(self) -> None:
        model_name = (os.getenv("WHISPER_MODEL", "large") or "large").strip()
        self.language = (os.getenv("WHISPER_LANGUAGE", "it") or "it").strip()
        self.audio_model = whisper.load_model(model_name)

    def transcribe(self, input_file: str) -> str:
        result = self.audio_model.transcribe(
            input_file,
            language=self.language,
            condition_on_previous_text=False,
            temperature=0.0,
            verbose=False,
        )
        return str(result.get("text") or "").strip()


def main() -> int:
    input_manifest_path = _require_env("TF_INPUT_MANIFEST")
    output_manifest_path = _require_env("TF_OUTPUT_MANIFEST")

    manifest_raw = _read_json(input_manifest_path)
    inputs = manifest_raw.get("inputs")
    if not isinstance(inputs, dict):
        raise SystemExit("Input manifest must contain an 'inputs' object")

    _, input_audio_path = _pick_primary_input(inputs)
    source_key = _pick_first_source_key(manifest_raw)

    out_manifest_file = Path(output_manifest_path)
    output_dir = out_manifest_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    algorithm = SpeechToTextAlgorithm()
    transcription_text = algorithm.transcribe(input_audio_path)

    reference_path = source_key if source_key else os.path.basename(input_audio_path)
    transcription_relpath = _transcription_relpath_from_reference(reference_path)
    transcription_file = output_dir / transcription_relpath
    transcription_file.parent.mkdir(parents=True, exist_ok=True)
    transcription_file.write_text(transcription_text + "\n", encoding="utf-8")

    transcription_output: Dict[str, Any] = {
        "path": transcription_relpath,
        "content_type": "text/plain",
    }
    # Keep backward compatibility with existing ToothFairy object-key layout.
    if source_key:
        transcription_output["key"] = transcription_relpath

    outputs: Dict[str, Any] = {"transcription": transcription_output}

    _write_output_manifest(output_manifest_path, outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
