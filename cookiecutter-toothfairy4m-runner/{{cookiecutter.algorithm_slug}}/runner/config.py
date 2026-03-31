import json
import os
from dataclasses import dataclass
from typing import Dict, Set


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _json_dict_env(name: str, default: Dict[str, str] | None = None) -> Dict[str, str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return dict(default or {})
    try:
        parsed = json.loads(raw)
    except Exception as exc:
        raise RuntimeError(f"{name} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{name} must be a JSON object")
    out: Dict[str, str] = {}
    for k, v in parsed.items():
        if not isinstance(k, str) or not str(k).strip():
            continue
        if not isinstance(v, str) or not str(v).strip():
            continue
        out[str(k).strip()] = str(v).strip()
    return out


@dataclass(frozen=True)
class RunnerConfig:
    runner_task_name: str
    runner_queue: str
    runner_worker_id: str
    runner_api_base_url: str
    runner_api_token: str
    celery_broker_url: str
    celery_result_backend: str
    object_storage_endpoint_url: str
    object_storage_access_key_id: str
    object_storage_secret_access_key: str
    object_storage_bucket: str
    object_storage_use_ssl: bool
    object_storage_key_prefix: str
    algorithm_image_map: Dict[str, str]
    runner_workdir_root: str


def load_config() -> RunnerConfig:
    runner_task_name = os.getenv(
        "RUNNER_TASK_NAME", "{{ cookiecutter.runner_task_name }}"
    ).strip()
    runner_queue = os.getenv("RUNNER_QUEUE", "{{ cookiecutter.runner_queue }}").strip()
    runner_worker_id = os.getenv(
        "RUNNER_WORKER_ID", "{{ cookiecutter.algorithm_slug }}-worker"
    ).strip()
    runner_api_base_url = os.getenv("RUNNER_API_BASE_URL", "").strip().rstrip("/")
    runner_api_token = os.getenv("RUNNER_API_TOKEN", "").strip()
    celery_broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0").strip()
    celery_result_backend = os.getenv(
        "CELERY_RESULT_BACKEND", "redis://redis:6379/1"
    ).strip()
    object_storage_endpoint_url = os.getenv("OBJECT_STORAGE_ENDPOINT_URL", "").strip()
    object_storage_access_key_id = os.getenv("OBJECT_STORAGE_ACCESS_KEY_ID", "").strip()
    object_storage_secret_access_key = os.getenv(
        "OBJECT_STORAGE_SECRET_ACCESS_KEY", ""
    ).strip()
    object_storage_bucket = os.getenv("OBJECT_STORAGE_BUCKET", "toothfairy4m").strip()
    object_storage_use_ssl = _bool_env("OBJECT_STORAGE_USE_SSL", default=False)
    object_storage_key_prefix = (
        os.getenv("OBJECT_STORAGE_KEY_PREFIX", "").strip().strip("/")
    )
    default_map = {
        "{{ cookiecutter.modality_slug }}": "toothfairy4m-{{ cookiecutter.algorithm_slug }}:latest"
    }
    algorithm_image_map = _json_dict_env("ALGORITHM_IMAGE_MAP", default=default_map)
    runner_workdir_root = os.getenv(
        "RUNNER_WORKDIR_ROOT", "/tmp/toothfairy4m-runner"
    ).strip()

    required = {
        "RUNNER_TASK_NAME": runner_task_name,
        "RUNNER_QUEUE": runner_queue,
        "RUNNER_WORKER_ID": runner_worker_id,
        "RUNNER_API_BASE_URL": runner_api_base_url,
        "RUNNER_API_TOKEN": runner_api_token,
        "CELERY_BROKER_URL": celery_broker_url,
        "CELERY_RESULT_BACKEND": celery_result_backend,
        "OBJECT_STORAGE_ENDPOINT_URL": object_storage_endpoint_url,
        "OBJECT_STORAGE_ACCESS_KEY_ID": object_storage_access_key_id,
        "OBJECT_STORAGE_SECRET_ACCESS_KEY": object_storage_secret_access_key,
        "OBJECT_STORAGE_BUCKET": object_storage_bucket,
        "RUNNER_WORKDIR_ROOT": runner_workdir_root,
    }
    missing: Set[str] = {k for k, v in required.items() if not v}
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(f"Missing required environment variables: {names}")

    return RunnerConfig(
        runner_task_name=runner_task_name,
        runner_queue=runner_queue,
        runner_worker_id=runner_worker_id,
        runner_api_base_url=runner_api_base_url,
        runner_api_token=runner_api_token,
        celery_broker_url=celery_broker_url,
        celery_result_backend=celery_result_backend,
        object_storage_endpoint_url=object_storage_endpoint_url,
        object_storage_access_key_id=object_storage_access_key_id,
        object_storage_secret_access_key=object_storage_secret_access_key,
        object_storage_bucket=object_storage_bucket,
        object_storage_use_ssl=object_storage_use_ssl,
        object_storage_key_prefix=object_storage_key_prefix,
        algorithm_image_map=algorithm_image_map,
        runner_workdir_root=runner_workdir_root,
    )
