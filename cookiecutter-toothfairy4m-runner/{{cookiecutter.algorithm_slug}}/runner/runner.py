import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .config import RunnerConfig
from .object_storage import ObjectStorage, ObjectStorageError

logger = logging.getLogger(__name__)


class RunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunnerResult:
    outputs: Dict[str, Any]
    logs: str = ""


def _parse_input_spec(input_file_path: str) -> Any:
    if not input_file_path:
        return ""
    s = input_file_path.strip()
    if s.startswith("{") or s.startswith("["):
        try:
            return json.loads(s)
        except Exception:
            return input_file_path
    return input_file_path


def _localize_inputs(
    *, storage: ObjectStorage, workdir: str, input_spec: Any
) -> Tuple[Dict[str, str], List[str]]:
    inputs_dir = os.path.join(workdir, "work", "input")
    os.makedirs(inputs_dir, exist_ok=True)

    localized: Dict[str, str] = {}
    source_keys: List[str] = []

    def download_one(logical_name: str, key_or_path: str):
        if not key_or_path:
            return
        key = key_or_path.lstrip("/")
        if not key:
            return

        if not storage.exists(key) and (key.endswith("/") or "/" in key):
            prefix = key.rstrip("/") + "/"
            keys = list(storage.list_keys(prefix))
            if not keys:
                raise RunnerError(f"Input object not found: {key}")
            for idx, child_key in enumerate(keys):
                download_one(f"{logical_name}_{idx}", child_key)
            return

        base = os.path.basename(key.rstrip("/")) or logical_name
        filename = (
            f"{logical_name}__{base}" if logical_name and logical_name != base else base
        )
        dest = os.path.join(inputs_dir, filename)
        storage.download_file(key, dest)
        localized[logical_name] = f"/work/input/{filename}"
        source_keys.append(key)

    if isinstance(input_spec, dict):
        files_list = (
            input_spec.get("files")
            if isinstance(input_spec.get("files"), list)
            else None
        )
        if files_list is not None:
            for idx, v in enumerate(files_list):
                download_one(f"file_{idx}", str(v))
        else:
            for k, v in input_spec.items():
                if isinstance(v, list):
                    for idx, item in enumerate(v):
                        download_one(f"{k}_{idx}", str(item))
                else:
                    download_one(str(k), str(v))
    elif isinstance(input_spec, list):
        for idx, v in enumerate(input_spec):
            download_one(f"file_{idx}", str(v))
    else:
        download_one("input", str(input_spec))

    return localized, source_keys


def _run_docker(*, image: str, workdir: str, env: Dict[str, str]) -> str:
    local_work_dir = os.path.join(workdir, "work")
    os.makedirs(local_work_dir, exist_ok=True)

    create_cmd = ["docker", "create"]
    for k, v in env.items():
        create_cmd.extend(["-e", f"{k}={v}"])
    create_cmd.append(image)

    create_proc = subprocess.run(create_cmd, capture_output=True, text=True)
    if create_proc.returncode != 0:
        combined = (create_proc.stdout or "") + "\n" + (create_proc.stderr or "")
        raise RunnerError(f"Failed to create algorithm container: {combined[-2000:]}")

    container_id = (create_proc.stdout or "").strip()
    if not container_id:
        raise RunnerError(
            "Failed to create algorithm container: no container id returned"
        )

    try:
        cp_in_cmd = ["docker", "cp", local_work_dir, f"{container_id}:/"]
        cp_in_proc = subprocess.run(cp_in_cmd, capture_output=True, text=True)
        if cp_in_proc.returncode != 0:
            combined = (cp_in_proc.stdout or "") + "\n" + (cp_in_proc.stderr or "")
            raise RunnerError(
                f"Failed to stage inputs into algorithm container: {combined[-2000:]}"
            )

        start_cmd = ["docker", "start", "-a", container_id]
        start_proc = subprocess.run(start_cmd, capture_output=True, text=True)

        logs = ""
        if start_proc.stdout:
            logs += start_proc.stdout
        if start_proc.stderr:
            logs += "\n" + start_proc.stderr

        cp_out_cmd = ["docker", "cp", f"{container_id}:/work/output", local_work_dir]
        subprocess.run(cp_out_cmd, capture_output=True, text=True)

        if start_proc.returncode != 0:
            raise RunnerError(
                f"Algorithm container failed with code {start_proc.returncode}: {logs[-2000:]}"
            )

        return logs
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_id], capture_output=True, text=True
        )


def run_job(
    *, cfg: RunnerConfig, storage: ObjectStorage, claimed_job: Dict[str, Any]
) -> RunnerResult:
    modality = str(claimed_job.get("modality_slug") or "").strip()
    job_id = int(claimed_job.get("id"))
    project_slug = str(claimed_job.get("project_slug") or "default")
    input_file_path = str(claimed_job.get("input_file_path") or "")
    output_files_meta = (
        claimed_job.get("output_files")
        if isinstance(claimed_job.get("output_files"), dict)
        else {}
    )

    image = cfg.algorithm_image_map.get(modality)
    if not image:
        raise RunnerError(f"No algorithm image configured for modality {modality}")

    workdir = tempfile.mkdtemp(
        prefix=f"tf_ext_runner_{job_id}_", dir=cfg.runner_workdir_root
    )
    try:
        input_spec = _parse_input_spec(input_file_path)
        if isinstance(input_spec, str) and isinstance(output_files_meta, dict):
            input_files = output_files_meta.get("input_files")
            if isinstance(input_files, list) and input_files:
                input_spec = input_files

        localized_inputs, source_keys = _localize_inputs(
            storage=storage, workdir=workdir, input_spec=input_spec
        )

        input_manifest_path = os.path.join(workdir, "work", "input", "manifest.json")
        output_dir = os.path.join(workdir, "work", "output")
        os.makedirs(output_dir, exist_ok=True)
        output_manifest_path = os.path.join(output_dir, "manifest.json")

        with open(input_manifest_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": 1,
                    "job": {"id": job_id, "modality": modality},
                    "inputs": localized_inputs,
                    "source_keys": source_keys,
                },
                f,
                indent=2,
            )

        env = {
            "TF_JOB_ID": str(job_id),
            "TF_MODALITY": modality,
            "TF_INPUT_MANIFEST": "/work/input/manifest.json",
            "TF_OUTPUT_MANIFEST": "/work/output/manifest.json",
        }
        logs = _run_docker(image=image, workdir=workdir, env=env)

        if not os.path.exists(output_manifest_path):
            raise RunnerError("Algorithm did not write output manifest")

        with open(output_manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        outputs = manifest.get("outputs", {})
        if not isinstance(outputs, dict):
            raise RunnerError("Invalid output manifest: 'outputs' must be an object")

        uploaded_outputs: Dict[str, Any] = {}
        for logical_name, out_spec in outputs.items():
            if isinstance(out_spec, str):
                out_path = out_spec
                content_type = None
            elif isinstance(out_spec, dict):
                out_path = out_spec.get("path")
                content_type = out_spec.get("content_type")
            else:
                continue

            if not out_path:
                continue

            abs_out_path = (
                out_path
                if str(out_path).startswith("/")
                else os.path.join(output_dir, str(out_path))
            )
            if not os.path.exists(abs_out_path):
                raise RunnerError(
                    f"Declared output not found: {logical_name} -> {abs_out_path}"
                )

            key = f"{project_slug}/processed/{modality}/job_{job_id}/{os.path.basename(abs_out_path)}"
            try:
                storage.upload_file(abs_out_path, key=key, content_type=content_type)
            except ObjectStorageError as exc:
                raise RunnerError(
                    f"Failed uploading output '{logical_name}' to object storage: {exc}"
                ) from exc

            uploaded_outputs[str(logical_name)] = {
                "path": key,
                "filename": os.path.basename(abs_out_path),
                "content_type": content_type,
            }

        return RunnerResult(outputs=uploaded_outputs, logs=logs)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
