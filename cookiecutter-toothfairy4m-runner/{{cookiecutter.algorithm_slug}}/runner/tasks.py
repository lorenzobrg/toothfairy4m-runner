import logging
import os

from .api_client import RunnerApiClient, RunnerApiError
from .celery_app import app
from .config import load_config
from .object_storage import ObjectStorage
from .runner import RunnerError, run_job

logger = logging.getLogger(__name__)

cfg = load_config()
api_client = RunnerApiClient(cfg)
storage = ObjectStorage(cfg)

os.makedirs(cfg.runner_workdir_root, exist_ok=True)


@app.task(name="{{ cookiecutter.runner_task_name }}", bind=True, acks_late=True)
def process_job(self, job_id: int):
    logger.info("Received job %s", job_id)

    try:
        claim = api_client.claim_job(int(job_id))
    except RunnerApiError as exc:
        logger.error("Failed to claim job %s: %s", job_id, exc)
        raise

    if not claim.get("claimed"):
        logger.info("Skipping job %s: %s", job_id, claim.get("reason"))
        return {"skipped": True, "reason": claim.get("reason")}

    claimed_job = claim.get("job") or {}
    try:
        result = run_job(cfg=cfg, storage=storage, claimed_job=claimed_job)
        api_client.complete_job(
            int(job_id), output_files=result.outputs, logs=result.logs
        )
        return {"success": True, "outputs": result.outputs}
    except RunnerError as exc:
        msg = str(exc)
        logger.error("Runner failed for job %s: %s", job_id, msg, exc_info=True)
        try:
            api_client.fail_job(int(job_id), error_msg=msg)
        except RunnerApiError:
            logger.exception("Failed to report failure to API for job %s", job_id)
        return {"success": False, "error": msg}
    except Exception as exc:
        msg = str(exc)
        logger.error("Unexpected failure for job %s: %s", job_id, msg, exc_info=True)
        try:
            api_client.fail_job(int(job_id), error_msg=msg)
        except RunnerApiError:
            logger.exception(
                "Failed to report unexpected failure to API for job %s", job_id
            )
        raise
