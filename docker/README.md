# docker/ — container domain

All Dockerfiles and container helper scripts: `Dockerfile.api` (slim, no ML),
`Dockerfile.worker` (CUDA 12.8 / cu128 torch), `Dockerfile.ui` (nginx static),
plus the worker `entrypoint-worker.sh` and `healthcheck.py`. Orchestrated by the
root `docker-compose*.yml`.
