# Bulk Import

Four ways to get videos into the pipeline, from single files to a whole
backlog. They're independent — use whichever fits your setup, or mix them.

## Option 1 — S3 (videos in Amazon cloud)

No Docker changes needed. Add your AWS credentials to `.env` (see the `# ---
S3 batch processing` section in `.env.example`) and restart:

```bash
docker compose exec worker python scripts/s3_batch.py --bucket my-edu-videos --prefix chemistry/
```

Lists the bucket, downloads each video, submits it through the normal API
(SHA-256 dedup + enqueue), waits for each job, and prints a summary. Use
`--dry-run` to preview first, `--help` for all flags (parallelism, region,
extensions, force-reprocess, etc.). See `scripts/README.md` and
`api/API_REFERENCE.md` for details.

## Option 2 — NAS (videos on an office network drive)

1. Mount the NAS on the **host** machine (outside Docker — standard OS-level
   mounting):
   ```bash
   sudo mount -t cifs //NAS_IP/SHARE /mnt/nas-videos -o username=USER,password=PASS
   # or NFS: sudo mount -t nfs NAS_IP:/SHARE /mnt/nas-videos
   ```
2. Add `NAS_MOUNT_PATH=/mnt/nas-videos` to `.env` (see the `# --- NAS bulk
   import` section in `.env.example`).
3. Restart: `docker compose up -d` (or the CPU/dev overlay you normally use —
   `-f docker-compose.yml -f docker-compose.override.dev.yml -f
   docker-compose.cpu.yml` on a GPU-less box).

Once that's done, `/data/nas/` inside the `api` and `worker` containers
mirrors your NAS share (mounted read-only — the pipeline never writes back to
it). Enqueue everything in it:

```bash
curl -X POST -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"folder": "/data/nas"}' \
  http://localhost:8000/api/v1/videos/batch
```

or from the dashboard: **Ingest → Enqueue folder / glob → `/data/nas`**, or
via the CLI: `python scripts/cli.py enqueue-folder /data/nas`.

**If you don't have a NAS**, leave `NAS_MOUNT_PATH` unset in `.env` —
`docker-compose.yml` falls back to an empty placeholder directory
automatically, so `/data/nas/` is just empty and the stack starts normally.
No crash, no separate compose file needed. Use S3 or UI upload instead.

## Option 3 — Direct copy into the inbox

For a handful of files already sitting on the host, or scripted from
elsewhere:

```bash
docker cp your_video.mp4 katbook_vip_2-api-1:/data/inbox/
```

Then enqueue the same way: dashboard **Ingest → Enqueue folder / glob →
`/data/inbox`**, or `POST /api/v1/videos/batch` with `"folder": "/data/inbox"`.

## Option 4 — UI upload (single files)

Dashboard → **Ingest → Upload a file** → click to browse or drop a video.
Best for one-off uploads and testing; see the "Force reprocess if already
done" checkbox if you're re-uploading something already processed.

## Which one for a real backlog?

- **S3**: use `s3_batch.py` — it's the only option with built-in per-file
  progress, retry-on-failure tracking, and a `--dry-run` preview for a large,
  unattended bulk run.
- **NAS**: `POST /api/v1/videos/batch` enqueues everything in one call, but
  it's fire-and-forget — no per-file progress/retry tracking beyond what the
  Jobs page already shows. Fine for a few dozen files; for thousands, copying
  into S3 first and using `s3_batch.py` gives you better visibility into
  what failed and needs a retry.
