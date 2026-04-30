"""Minimal ToothFairy4M algorithm entrypoint.

What ToothFairy4M expects from your container:

1) The runner sets two env vars:
   - TF_INPUT_MANIFEST=/work/input/manifest.json
   - TF_OUTPUT_MANIFEST=/work/output/manifest.json

2) Your container must:
   - read the JSON file at TF_INPUT_MANIFEST
   - write output file(s) into the directory that contains TF_OUTPUT_MANIFEST
   - write an *output manifest* JSON at TF_OUTPUT_MANIFEST with the shape:

     {
       "version": 1,
       "outputs": {
         "some_key": {"path": "relative_filename.ext", "content_type": "..."}
       }
     }

Input manifest (minimal, and recommended to rely on):

  {
    "version": 1,
    "inputs": {
      "primary": "/work/input/some_input.ext"
    }
  }

The runner may include extra fields like `job` or `source_keys`. Your algorithm
should usually ignore them unless you need them.
"""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any, Dict


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


def _guess_content_type(path: str) -> str | None:
    # Uses filename to guess content type.
    guessed, _ = mimetypes.guess_type(path)
    return guessed 


def _suffix(path: str) -> str:
    # Preserve compound suffixes like ".nii.gz".
    return "".join(Path(path).suffixes)


def _run_algorithm(
    *,
    inputs: Dict[str, str],
    output_dir: Path,
) -> Dict[str, Path]:
    """Implement your algorithm here.

    This default implementation is intentionally minimal and multi-output:
    it copies each input file to `/work/output/` under the same logical name.
    """

    produced: Dict[str, Path] = {}
    for logical_name, in_path in inputs.items():
        out_path = output_dir / f"{logical_name}{_suffix(in_path)}"
        shutil.copy2(in_path, out_path)
        produced[str(logical_name)] = out_path

    return produced


def main() -> int:
    input_manifest_path = _require_env("TF_INPUT_MANIFEST")
    output_manifest_path = _require_env("TF_OUTPUT_MANIFEST")

    manifest_raw = _read_json(input_manifest_path)
    inputs = manifest_raw["inputs"]

    out_manifest_file = Path(output_manifest_path)
    output_dir = out_manifest_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    produced = _run_algorithm(inputs=inputs, output_dir=output_dir)

    outputs: Dict[str, Any] = {}
    for logical_name, out_path in produced.items():
        out_spec: Dict[str, Any] = {"path": out_path.name}
        content_type = _guess_content_type(out_path.name)
        if content_type:
            out_spec["content_type"] = content_type
        outputs[str(logical_name)] = out_spec

    _write_output_manifest(output_manifest_path, outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
