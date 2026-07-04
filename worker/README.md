# worker/ — jobs domain

Celery worker (one video per task, concurrency 1 per GPU) that runs the
`katbook_vip` pipeline, reports per-stage job progress, retries transient failures,
and publishes a GPU heartbeat. Run: `celery -A worker.celery_app worker`.
