import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _pick_primary_input(inputs: Dict[str, str]) -> Tuple[Optional[str], List[str]]:
    """Default input selection strategy.

    Many ToothFairy4M algorithms accept a single primary input.
    If your algorithm needs special selection (e.g. prefer NIfTI over DICOM),
    replace this function.
    """

    paths = [p for p in (inputs or {}).values() if p]
    if not paths:
        return None, []
    return paths[0], paths


def _write_output_manifest(output_manifest_path: str, outputs: Dict[str, dict]) -> None:
    out_manifest_file = Path(output_manifest_path)
    out_manifest_file.write_text(
        json.dumps({"version": 1, "outputs": outputs}, indent=2) + "\n",
        encoding="utf-8",
    )


def _algorithm_specific_work(
    *,
    manifest: dict,
    job_id: Optional[str],
    inputs: Dict[str, str],
    primary_input: Optional[str],
    all_inputs: List[str],
    output_dir: Path,
) -> Dict[str, dict]:
    """Implement your algorithm here.

    Return a dict mapping output keys to:
      {"path": <filename relative to output_dir>, "content_type": <mime type>}

    Notes:
    - The runner will set TF_OUTPUT_MANIFEST to something like /work/output/manifest.json
    - Your output files should be written under output_dir (/work/output)
    """

    out_file = output_dir / "{{ cookiecutter.output_filename }}"
    payload = {
        "version": 1,
        "algorithm": "{{ cookiecutter.algorithm_slug }}",
        "job_id": job_id,
        "primary_input": os.path.basename(primary_input) if primary_input else None,
        "input_count": len(all_inputs),
        "input_keys": sorted([str(k) for k in (inputs or {}).keys()]),
    }
    out_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return {
        "{{ cookiecutter.output_key }}": {
            "path": out_file.name,
            "content_type": "{{ cookiecutter.output_content_type }}",
        }
    }


def main() -> int:
    input_manifest_path = _require_env("TF_INPUT_MANIFEST")
    output_manifest_path = _require_env("TF_OUTPUT_MANIFEST")

    manifest = _read_json(input_manifest_path)

    job = manifest.get("job") or {}
    job_id = job.get("id")

    inputs = manifest.get("inputs") or {}
    primary, all_paths = _pick_primary_input(inputs)
    if not primary:
        raise SystemExit("No inputs provided")

    out_manifest_file = Path(output_manifest_path)
    output_dir = out_manifest_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs = _algorithm_specific_work(
        manifest=manifest,
        job_id=job_id,
        inputs=inputs,
        primary_input=primary,
        all_inputs=all_paths,
        output_dir=output_dir,
    )

    _write_output_manifest(output_manifest_path, outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
