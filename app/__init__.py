"""Katbook VIP API service (FastAPI). Contains NO ML models and NO UI — it is a
lightweight, versioned REST surface over Postgres + the Celery queue. All GPU work
happens in the worker."""

__version__ = "3.0.0"
