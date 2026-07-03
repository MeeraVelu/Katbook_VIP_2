#!/usr/bin/env bash
# Worker entrypoint: start the Celery worker on the GPU queue.
# Concurrency is 1 per GPU (models are large); the `solo` pool avoids fork issues
# with CUDA/torch. Scale out by starting another worker container pinned to a
# different GPU via CUDA_VISIBLE_DEVICES.
set -euo pipefail

CONCURRENCY="${WORKER_CONCURRENCY:-1}"
LOGLEVEL="${CELERY_LOGLEVEL:-INFO}"

echo "Starting Katbook worker: queue=gpu concurrency=${CONCURRENCY} CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-unset}"

exec celery -A worker.celery_app worker \
    --queues gpu \
    --concurrency "${CONCURRENCY}" \
    --pool solo \
    --loglevel "${LOGLEVEL}" \
    --without-gossip --without-mingle
