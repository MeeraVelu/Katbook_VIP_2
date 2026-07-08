# scripts/ — operational CLIs

Standalone operator tools: `cli.py` (typer console for enqueue/watch/search/export),
`verify_gpu.py` (run first on the 5090), `verify_db.py` (prove the app can reach an
external/Supabase DB before `up -d`), `smoke.py` + `make_test_video.py` (CPU
end-to-end check), `reembed.py`, `backup.sh`, `export_tensorrt.py`.

`s3_batch.py` bulk-imports videos from an S3 bucket through the normal API flow
(SHA-256 dedup + enqueue), tracking progress and skipping files already in the DB.
It needs `boto3` (bundled in the worker image; `pip install boto3` for host runs):

    # MODE 1 — any machine, uploads the bytes to the API
    python scripts/s3_batch.py --bucket my-edu-videos --prefix chemistry/

    # MODE 2 — inside Docker, downloads into the shared inbox and registers by path
    docker compose exec worker python scripts/s3_batch.py \
        --bucket my-edu-videos --submit path --api-url http://api:8000

Use `--dry-run` to preview, `--help` for all flags.
