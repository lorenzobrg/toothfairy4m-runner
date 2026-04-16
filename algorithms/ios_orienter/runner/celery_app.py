from celery import Celery

from .config import load_config


cfg = load_config()

app = Celery("toothfairy4m_runner")
app.conf.update(
    broker_url=cfg.celery_broker_url,
    result_backend=cfg.celery_result_backend,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_routes={cfg.runner_task_name: {"queue": cfg.runner_queue}},
    worker_prefetch_multiplier=1,
)

app.autodiscover_tasks(["runner"])
