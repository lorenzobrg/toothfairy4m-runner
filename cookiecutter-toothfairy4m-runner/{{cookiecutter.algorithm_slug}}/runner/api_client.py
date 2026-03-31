import json
from typing import Any, Dict

import requests

from .config import RunnerConfig


class RunnerApiError(RuntimeError):
    pass


class RunnerApiClient:
    def __init__(self, cfg: RunnerConfig):
        self.base_url = cfg.runner_api_base_url.rstrip("/")
        self.token = cfg.runner_api_token
        self.worker_id = cfg.runner_worker_id

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Runner-Worker-Id": self.worker_id,
        }

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = requests.post(
                url, headers=self._headers, data=json.dumps(payload), timeout=30
            )
        except Exception as exc:
            raise RunnerApiError(f"Runner API request failed: {exc}") from exc

        try:
            data = response.json()
        except Exception:
            body = response.text[:1000]
            raise RunnerApiError(
                f"Runner API returned non-JSON response ({response.status_code}): {body}"
            )

        if response.status_code >= 400:
            raise RunnerApiError(
                f"Runner API error ({response.status_code}): {data.get('error') or data.get('reason') or data}"
            )
        return data

    def claim_job(self, job_id: int) -> Dict[str, Any]:
        return self._post(f"/api/runner/jobs/{job_id}/claim/", {})

    def complete_job(
        self, job_id: int, *, output_files: Dict[str, Any], logs: str = ""
    ) -> Dict[str, Any]:
        return self._post(
            f"/api/runner/jobs/{job_id}/complete/",
            {
                "output_files": output_files,
                "logs": logs,
            },
        )

    def fail_job(self, job_id: int, *, error_msg: str) -> Dict[str, Any]:
        return self._post(f"/api/runner/jobs/{job_id}/fail/", {"error": error_msg})
