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
from typing import Any, Dict, List


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


def _named_inputs_from_manifest(manifest: Dict[str, Any]) -> Dict[str, str]:
    inputs = manifest.get("inputs")
    if isinstance(inputs, dict):
        out: Dict[str, str] = {}
        for k, v in inputs.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                out[k] = v
        return out
    return {}


def _input_paths_from_manifest(manifest: Dict[str, Any]) -> List[str]:
    """Return input file paths, in a robust / forgiving way.

    ToothFairy4M runner usually provides:
      manifest["inputs"] as a dict: logical_name -> absolute path in /work/input

    For local experiments, we also accept:
      - {"inputs": ["/work/input/a", "/work/input/b"]}
      - {"input": "/work/input/a"}
    """

    inputs = manifest.get("inputs")
    paths: List[str] = []

    if isinstance(inputs, dict):
        # Prefer the conventional `primary` key when present.
        primary = inputs.get("primary")
        if isinstance(primary, str) and primary.strip():
            paths.append(primary)

        # Deterministic order: then other keys sorted.
        for k in sorted(inputs.keys(), key=lambda x: str(x)):
            if k == "primary":
                continue
            v = inputs.get(k)
            if isinstance(v, str) and v.strip() and v not in paths:
                paths.append(v)

    elif isinstance(inputs, list):
        for v in inputs:
            if isinstance(v, str) and v.strip():
                paths.append(v)

    else:
        single = manifest.get("input")
        if isinstance(single, str) and single.strip():
            paths.append(single)

    return paths


def _is_nifti(path: str) -> bool:
    p = (path or "").lower()
    return p.endswith(".nii") or p.endswith(".nii.gz")


def _guess_content_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _run_algorithm(
    *,
    input_paths: List[str],
    named_inputs: Dict[str, str],
    output_dir: Path,
) -> Path:
    """Implement your algorithm here.

    Keep it simple:
    - read `primary_input` (or iterate over `all_input_paths` / `named_inputs`)
    - write one output file under `output_dir`
    - return the *absolute* output path

    Example (CBCT-ish): if the input is NIfTI and nibabel is installed, reorient
    it to canonical (RAS+) orientation. This is a safe, real-world example of a
    "rotation"/axis-permutation operation that updates the affine correctly.
    If nibabel is not installed (or input is not NIfTI), it falls back to a
    straightforward file copy.
    """

    out_path = output_dir / "{{ cookiecutter.output_filename }}"

    if _is_nifti(input_paths[0]):
        try:
            import nibabel as nib  # type: ignore
        except Exception:
            nib = None

        if nib is not None:
            img = nib.load(input_paths[0])
            rotated = nib.as_closest_canonical(img)
            nib.save(rotated, str(out_path))
            return out_path

    shutil.copy2(input_paths[0], out_path)
    return out_path


def main() -> int:
    input_manifest_path = _require_env("TF_INPUT_MANIFEST")
    output_manifest_path = _require_env("TF_OUTPUT_MANIFEST")

    manifest_raw = _read_json(input_manifest_path)
    if not isinstance(manifest_raw, dict):
        raise SystemExit("Input manifest must be a JSON object")

    input_paths = _input_paths_from_manifest(manifest_raw)
    if not input_paths:
        raise SystemExit("No inputs provided in manifest")

    named_inputs = _named_inputs_from_manifest(manifest_raw)

    out_manifest_file = Path(output_manifest_path)
    output_dir = out_manifest_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    produced = _run_algorithm(
        input_paths=input_paths,
        named_inputs=named_inputs,
        output_dir=output_dir,
    )

    content_type_cfg = "{{ cookiecutter.output_content_type }}".strip()
    content_type = content_type_cfg if content_type_cfg else _guess_content_type(produced.name)

    output_spec: Dict[str, Any] = {"path": produced.name}
    # `content_type` is optional: the external runner uploads without setting ContentType
    # if this field is missing/empty.
    if content_type:
        output_spec["content_type"] = content_type

    outputs = {"{{ cookiecutter.output_key }}": output_spec}
    _write_output_manifest(output_manifest_path, outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
