"""Celery worker that runs the GPU pipeline (one video per task, concurrency 1
per GPU). Imports ``pipeline`` for the pipeline and ``api.services`` for DB /
job updates."""
