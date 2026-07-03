"""Celery worker that runs the GPU pipeline (one video per task, concurrency 1
per GPU). Imports ``katbook_vip`` for the pipeline and ``app.services`` for DB /
job updates."""
