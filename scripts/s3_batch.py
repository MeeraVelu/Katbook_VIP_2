#!/usr/bin/env python
"""
s3_batch.py — bulk-import videos from an S3 bucket through the normal Katbook flow.

This is an EXTERNAL operator tool: it lists an S3 bucket, downloads each video, and
submits it to the running API exactly like the UI would (SHA-256 dedup + enqueue in
the worker). It touches NO pipeline / API / worker code — it only calls the public
HTTP API and reads the `videos` table to skip files already imported.

    python scripts/s3_batch.py --bucket my-edu-videos --prefix chemistry/ --region ap-southeast-1

Two ways to run it:

  MODE 1 — Direct (any machine with Python, no Docker):
      pip install boto3            # (+ 'psycopg[binary]' if you want --skip-existing)
      export API_KEY=...           # if the API requires it
      python scripts/s3_batch.py --bucket my-videos
    Downloads to a local staging dir and UPLOADS the bytes to the API
    (`--submit upload`, the default) — works from anywhere the API URL is reachable.

  MODE 2 — Inside Docker (downloads straight into the shared inbox volume):
      docker compose exec worker python scripts/s3_batch.py \
          --bucket my-videos --submit path --inbox /data/inbox --api-url http://api:8000
    Downloads into /data/inbox (shared with the api container) and registers each
    file BY PATH — no re-upload of the bytes.

AWS credentials come from the standard chain (env AWS_ACCESS_KEY_ID /
AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION, ~/.aws/…, or an instance role). On the
host they are also read from the repo `.env`, the same way scripts/verify_db.py
reads DATABASE_URL.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlsplit, urlunsplit

VIDEO_EXTS_DEFAULT = "mp4,webm,mov,mkv"


# --------------------------------------------------------------------------- #
# .env loading + small helpers (mirrors scripts/verify_db.py so host runs work)
# --------------------------------------------------------------------------- #
def _load_dotenv_if_missing(*keys: str) -> None:
    """Populate os.environ from the repo `.env` for keys not already set, so the
    tool works on the host too (inside a container these come from env_file)."""
    if all(os.environ.get(k) for k in keys):
        return
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _mask(url: str) -> str:
    """Hide the password when echoing a DB URL."""
    try:
        s = urlsplit(url)
        if s.password:
            netloc = s.netloc.replace(f":{s.password}@", ":***@", 1)
            return urlunsplit((s.scheme, netloc, s.path, s.query, s.fragment))
    except Exception:
        pass
    return url


def _human_size(n: int | None) -> str:
    if not n:
        return "?"
    val = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{val:.0f} {unit}" if unit in ("B", "KB") else f"{val:.1f} {unit}"
        val /= 1024
    return f"{n} B"


class BatchAbort(Exception):
    """Fatal, whole-run error (bad credentials, missing bucket) — stop immediately."""


class DuplicateError(RuntimeError):
    """Raised for a 409 'already processed' response (see api/errors.py,
    code='duplicate') — NOT a real failure, the caller should skip gracefully."""

    def __init__(self, message: str, details: dict | None):
        super().__init__(message)
        self.details = details or {}


# --------------------------------------------------------------------------- #
# API client — stdlib urllib only (keeps the tool's only new dep = boto3)
# --------------------------------------------------------------------------- #
class ApiClient:
    def __init__(self, base_url: str, api_key: str | None, timeout: float = 120.0):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self, extra: dict | None = None) -> dict:
        h = dict(extra or {})
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    def _send(self, req: urlrequest.Request) -> tuple[int, dict]:
        try:
            with urlrequest.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urlerror.HTTPError as e:
            raw = e.read()
            try:
                body = json.loads(raw) if raw else {}
            except Exception:
                body = {"error": {"message": raw[:200].decode("utf-8", "replace")}}
            return e.code, body

    @staticmethod
    def _err_message(status: int, body: dict) -> str:
        env = (body or {}).get("error") or {}
        return env.get("message") or body.get("detail") or f"HTTP {status}"

    @classmethod
    def _raise_for_status(cls, status: int, body: dict) -> None:
        if status < 400:
            return
        env = (body or {}).get("error") or {}
        message = cls._err_message(status, body)
        if status == 409 and env.get("code") == "duplicate":
            raise DuplicateError(message, env.get("details"))
        raise RuntimeError(message)

    def register_path(self, source_path: str, force: bool) -> dict:
        """POST /api/v1/videos — register a server-visible path (JSON, no upload)."""
        data = json.dumps({"source_path": source_path, "force": force}).encode()
        req = urlrequest.Request(
            f"{self.base}/api/v1/videos",
            data=data,
            headers=self._headers({"Content-Type": "application/json"}),
            method="POST",
        )
        status, body = self._send(req)
        self._raise_for_status(status, body)
        return body

    def upload(self, local_path: str, filename: str, force: bool) -> dict:
        """POST /api/v1/videos/upload — multipart upload of the file bytes.

        The body is spooled to a temp file (small stays in RAM, large spills to
        disk) and streamed with an explicit Content-Length, so multi-GB videos do
        not have to be held in memory."""
        body, length, content_type = _build_multipart(local_path, filename, {"force": str(force)})
        headers = self._headers({"Content-Type": content_type, "Content-Length": str(length)})
        req = urlrequest.Request(
            f"{self.base}/api/v1/videos/upload", data=body, headers=headers, method="POST"
        )
        try:
            status, resp = self._send(req)
        finally:
            body.close()
        self._raise_for_status(status, resp)
        return resp

    def job(self, job_id: str) -> dict:
        req = urlrequest.Request(
            f"{self.base}/api/v1/jobs/{job_id}", headers=self._headers(), method="GET"
        )
        status, body = self._send(req)
        if status >= 400:
            raise RuntimeError(self._err_message(status, body))
        return body

    def video(self, video_id: str) -> dict:
        req = urlrequest.Request(
            f"{self.base}/api/v1/videos/{video_id}", headers=self._headers(), method="GET"
        )
        status, body = self._send(req)
        if status >= 400:
            raise RuntimeError(self._err_message(status, body))
        return body

    def ping(self) -> None:
        """Fail fast with a clear message if the API is unreachable."""
        try:
            req = urlrequest.Request(f"{self.base}/health", method="GET")
            with urlrequest.urlopen(req, timeout=10):
                return
        except Exception as e:  # noqa: BLE001 — surface a friendly hint
            raise BatchAbort(
                f"Cannot reach the API at {self.base} ({type(e).__name__}: {str(e)[:120]}).\n"
                "  * MODE 1 (host): is the API up? try --api-url http://localhost:8000\n"
                "  * MODE 2 (docker): use --api-url http://api:8000"
            ) from e


def _build_multipart(local_path: str, filename: str, fields: dict[str, str]):
    """Encode a multipart/form-data body into a SpooledTemporaryFile.

    Returns ``(fileobj_positioned_at_0, content_length, content_type)``."""
    boundary = "----katbookS3Batch" + os.urandom(16).hex()
    crlf = b"\r\n"
    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    for name, val in fields.items():
        spool.write(b"--" + boundary.encode() + crlf)
        spool.write(f'Content-Disposition: form-data; name="{name}"'.encode() + crlf + crlf)
        spool.write(str(val).encode() + crlf)
    spool.write(b"--" + boundary.encode() + crlf)
    spool.write(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode() + crlf
    )
    spool.write(b"Content-Type: application/octet-stream" + crlf + crlf)
    with open(local_path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            spool.write(chunk)
    spool.write(crlf + b"--" + boundary.encode() + b"--" + crlf)
    length = spool.tell()
    spool.seek(0)
    return spool, length, f"multipart/form-data; boundary={boundary}"


# --------------------------------------------------------------------------- #
# skip-existing — read the `videos` table by filename (optional, degrades gracefully)
# --------------------------------------------------------------------------- #
def load_existing_filenames(database_url: str | None) -> set[str] | None:
    """Return the set of basenames already present in the `videos` table, or None
    if the DB can't be reached / psycopg isn't installed (skip-existing is then
    disabled with a warning rather than failing the whole run)."""
    if not database_url:
        print("  [warn] --skip-existing on but DATABASE_URL is not set — skip check disabled.")
        return None
    try:
        import psycopg  # type: ignore
    except Exception:
        print(
            "  [warn] --skip-existing on but psycopg is not installed here — skip check disabled.\n"
            "         install it with:  pip install 'psycopg[binary]'   (or run inside a container)."
        )
        return None
    # psycopg wants a bare libpq URL — drop any SQLAlchemy '+driver' qualifier.
    scheme, rest = (
        database_url.split("://", 1) if "://" in database_url else ("postgresql", database_url)
    )
    dsn = f"{scheme.split('+', 1)[0]}://{rest}"
    try:
        with psycopg.connect(dsn, connect_timeout=15) as cx:
            rows = cx.execute(
                "SELECT source_path FROM videos WHERE status <> 'soft_deleted'"
            ).fetchall()
    except Exception as e:  # noqa: BLE001
        print(
            f"  [warn] could not read the videos table ({type(e).__name__}: {str(e)[:100]}) — "
            "skip check disabled."
        )
        return None
    names = {os.path.basename(r[0]) for r in rows if r[0]}
    print(f"  loaded {len(names)} existing filename(s) from the database ({_mask(dsn)}).")
    return names


# --------------------------------------------------------------------------- #
# S3
# --------------------------------------------------------------------------- #
def make_s3_client(region: str):
    try:
        import boto3  # type: ignore
    except Exception as e:
        raise BatchAbort(
            "boto3 is not installed. Install it with:  pip install boto3"
        ) from e
    return boto3.client("s3", region_name=region)


def verify_bucket(s3, bucket: str) -> None:
    """Fail fast with a clear message on bad credentials or a missing bucket."""
    from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

    try:
        s3.head_bucket(Bucket=bucket)
    except NoCredentialsError as e:
        raise BatchAbort(
            "AWS credentials not found. Set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY "
            "(env or .env), configure ~/.aws/credentials, or use an instance role."
        ) from e
    except EndpointConnectionError as e:
        raise BatchAbort(f"Cannot reach S3 ({str(e)[:120]}). Check the --region and network.") from e
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
            raise BatchAbort(
                f"AWS credentials rejected for bucket {bucket!r} (code {code}). "
                "Check the access key / secret and the region."
            ) from e
        if code in ("404", "NoSuchBucket"):
            raise BatchAbort(
                f"Bucket {bucket!r} does not exist (or not in region '{s3.meta.region_name}')."
            ) from e
        raise BatchAbort(f"S3 error checking bucket {bucket!r}: {code or e}") from e


def list_video_keys(s3, bucket: str, prefix: str, exts: tuple[str, ...]) -> list[tuple[str, int]]:
    """List every object under prefix whose extension matches, as (key, size)."""
    from botocore.exceptions import ClientError

    out: list[tuple[str, int]] = []
    paginator = s3.get_paginator("list_objects_v2")
    try:
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix or ""):
            for obj in page.get("Contents", []) or []:
                key = obj["Key"]
                if key.endswith("/"):  # folder placeholder
                    continue
                if key.rsplit(".", 1)[-1].lower() in exts:
                    out.append((key, int(obj.get("Size", 0))))
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket"):
            raise BatchAbort(f"Bucket {bucket!r} does not exist.") from e
        if code in ("403", "AccessDenied"):
            raise BatchAbort(f"Access denied listing {bucket!r}/{prefix} (code {code}).") from e
        raise BatchAbort(f"S3 error listing {bucket!r}: {code or e}") from e
    return out


# --------------------------------------------------------------------------- #
# Run bookkeeping
# --------------------------------------------------------------------------- #
@dataclass
class Failure:
    key: str
    stage: str  # "download" | "submit" | "process" | "timeout"
    error: str


@dataclass
class Results:
    total: int = 0
    processed: int = 0
    # covers BOTH "already processed at this same path" and "byte-identical to
    # another video" — the API now returns the same 409 shape for both (see
    # DuplicateError), so this tool no longer distinguishes them.
    skipped_existing: int = 0
    failures: list[Failure] = field(default_factory=list)

    def fail(self, key: str, stage: str, error: str) -> None:
        self.failures.append(Failure(key, stage, error[:300]))


@dataclass
class Downloaded:
    index: int
    key: str
    size: int
    local_path: str | None  # None => download failed
    error: str | None = None


# --------------------------------------------------------------------------- #
# Core: download-ahead producer + submit/wait/delete consumer
# --------------------------------------------------------------------------- #
def _download_worker(
    s3, bucket: str, keys: list[tuple[str, int]], inbox: Path, q: "Queue[Downloaded | None]",
    stop: threading.Event,
) -> None:
    """Download each key (in order) into `inbox`, pushing results onto a bounded
    queue. The queue's maxsize caps how many files sit on disk ahead of the
    consumer (``--max-parallel``), keeping disk usage low."""
    for i, (key, size) in enumerate(keys, 1):
        if stop.is_set():
            break
        basename = os.path.basename(key)
        dest = inbox / basename
        print(f"[{i}/{len(keys)}] Downloading {key} ({_human_size(size)})...")
        try:
            s3.download_file(bucket, key, str(dest))
            q.put(Downloaded(i, key, size, str(dest)))
        except Exception as e:  # noqa: BLE001 — record + continue to the next file
            q.put(Downloaded(i, key, size, None, f"{type(e).__name__}: {str(e)[:200]}"))
    q.put(None)  # sentinel: no more items


def _wait_for_job(api: ApiClient, job_id: str, poll: float, timeout: float) -> dict:
    """Poll a job until done/failed. Raises TimeoutError past `timeout`."""
    start = time.monotonic()
    last_stage = None
    while True:
        j = api.job(job_id)
        state, stage = j.get("state"), j.get("current_stage")
        if stage != last_stage and stage:
            print(f"        …{stage}")
            last_stage = stage
        if state in ("done", "failed"):
            return j
        if time.monotonic() - start > timeout:
            raise TimeoutError(f"job did not finish within {int(timeout)}s (last state={state})")
        time.sleep(poll)


def _summarize_video(api: ApiClient, video_id: str) -> str:
    """Best-effort 'Subject: X, Topic: Y' line from the video rollup."""
    try:
        detail = api.video(video_id)
        roll = detail.get("rollup") or {}
        subject = roll.get("subject") or "—"
        topic = roll.get("primary_topic") or "—"
        segs = detail.get("segments") or []
        return f"Subject: {subject}, Topic: {topic} ({len(segs)} segment(s))"
    except Exception:
        return "processed"


def process_batch(
    api: ApiClient,
    s3,
    bucket: str,
    keys: list[tuple[str, int]],
    inbox: Path,
    *,
    submit: str,
    force: bool,
    delete_local: bool,
    max_parallel: int,
    poll: float,
    job_timeout: float,
) -> Results:
    res = Results(total=len(keys))
    q: "Queue[Downloaded | None]" = Queue(maxsize=max(1, max_parallel))
    stop = threading.Event()
    producer = threading.Thread(
        target=_download_worker, args=(s3, bucket, keys, inbox, q, stop), daemon=True
    )
    producer.start()

    n = len(keys)
    try:
        while True:
            item = q.get()
            if item is None:
                break
            tag = f"[{item.index}/{n}]"

            if item.local_path is None:  # download failed
                print(f"{tag} Download FAILED: {item.error} ❌")
                res.fail(item.key, "download", item.error or "download error")
                continue

            print(f"{tag} Downloaded. Submitting to queue...")
            try:
                if submit == "path":
                    resp = api.register_path(item.local_path, force)
                else:
                    resp = api.upload(item.local_path, os.path.basename(item.key), force)
            except DuplicateError as e:
                # 409 from the API: already processed (same path) or byte-identical
                # to another video — not a failure, just nothing to do. Use --force
                # to reprocess anyway.
                res.skipped_existing += 1
                existing = e.details.get("existing_video_id", "?")
                print(f"{tag} Already processed (video {str(existing)[:8]}) — skipped. ⏭️")
                _maybe_delete(item.local_path, delete_local)
                continue
            except Exception as e:  # noqa: BLE001
                print(f"{tag} Submit FAILED: {str(e)[:160]} ❌")
                res.fail(item.key, "submit", str(e))
                _maybe_delete(item.local_path, delete_local)
                continue

            video_id = str(resp.get("video_id") or "")
            job_id = resp.get("job_id")

            # queued -> wait for the worker to finish
            try:
                job = _wait_for_job(api, str(job_id), poll, job_timeout)
            except TimeoutError as e:
                print(f"{tag} Processing TIMED OUT: {e} ❌")
                res.fail(item.key, "timeout", str(e))
                _maybe_delete(item.local_path, delete_local)
                continue
            except Exception as e:  # noqa: BLE001 — API/network blip while polling
                print(f"{tag} Error while waiting: {str(e)[:160]} ❌")
                res.fail(item.key, "process", str(e))
                _maybe_delete(item.local_path, delete_local)
                continue

            if job.get("state") == "failed":
                err = job.get("error") or "processing failed"
                print(f"{tag} Processing FAILED: {str(err)[:160]} ❌")
                res.fail(item.key, "process", str(err))
            else:
                res.processed += 1
                print(f"{tag} Processing complete. {_summarize_video(api, video_id)} ✅")

            _maybe_delete(item.local_path, delete_local)
    except KeyboardInterrupt:
        print("\nInterrupted — stopping after the current file. Partial summary follows.")
        stop.set()
    finally:
        stop.set()
    return res


def _maybe_delete(path: str, delete_local: bool) -> None:
    if delete_local and path:
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _resolve_inbox(raw: str, submit: str) -> Path:
    """Ensure the download dir exists. In `upload` mode fall back to a temp staging
    dir if the requested inbox can't be created (e.g. /data/inbox on a laptop)."""
    inbox = Path(raw)
    try:
        inbox.mkdir(parents=True, exist_ok=True)
        # writability probe
        probe = inbox / ".katbook_write_test"
        probe.touch()
        probe.unlink()
        return inbox
    except OSError:
        if submit == "path":
            raise BatchAbort(
                f"Inbox {raw!r} is not writable, but --submit path needs to write into the "
                "shared inbox volume. Run inside the container or pick a shared path."
            )
        staging = Path(tempfile.mkdtemp(prefix="katbook_s3_"))
        print(f"  [note] {raw!r} not writable — staging downloads in {staging} instead.")
        return staging


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="s3_batch.py",
        description="Bulk-import videos from S3 through the Katbook API (dedup + enqueue).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--bucket", required=True, help="S3 bucket name")
    p.add_argument("--prefix", default="", help="Folder/prefix inside the bucket (default: all)")
    p.add_argument("--region", default=None, help="AWS region (default: $AWS_DEFAULT_REGION or ap-southeast-1)")
    p.add_argument("--extensions", default=VIDEO_EXTS_DEFAULT, help="Comma-separated video extensions")
    p.add_argument("--max-parallel", type=int, default=1, help="How many files to download AHEAD (disk cap)")
    p.add_argument("--dry-run", action="store_true", help="List what WOULD be processed, then exit")
    p.add_argument(
        "--skip-existing", action=argparse.BooleanOptionalAction, default=True,
        help="Skip files whose filename already exists in the videos table",
    )
    p.add_argument(
        "--delete-local", action=argparse.BooleanOptionalAction, default=True,
        help="Delete the local copy after processing to save disk",
    )
    # submission / connection
    p.add_argument(
        "--submit", choices=("upload", "path"), default="upload",
        help="upload=send bytes to the API (any machine); path=register a shared-inbox path (MODE 2)",
    )
    p.add_argument("--inbox", default=None, help="Download dir (default: $VIDEO_INBOX_DIR or /data/inbox)")
    p.add_argument("--api-url", default=None, help="API base URL (default: $KATBOOK_API or http://localhost:8000)")
    p.add_argument("--api-key", default=None, help="X-API-Key (default: $API_KEY)")
    p.add_argument("--database-url", default=None, help="Postgres URL for --skip-existing (default: $DATABASE_URL)")
    p.add_argument("--poll-interval", type=float, default=3.0, help="Seconds between job status polls")
    p.add_argument("--job-timeout", type=float, default=3600.0, help="Max seconds to wait per video")
    p.add_argument("--force", action="store_true", help="Reprocess even if already done (force=true)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _load_dotenv_if_missing(
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION",
        "API_KEY", "DATABASE_URL", "KATBOOK_API", "VIDEO_INBOX_DIR",
    )

    region = args.region or os.environ.get("AWS_DEFAULT_REGION") or "ap-southeast-1"
    api_url = args.api_url or os.environ.get("KATBOOK_API") or "http://localhost:8000"
    api_key = args.api_key or os.environ.get("API_KEY")
    database_url = args.database_url or os.environ.get("DATABASE_URL")
    inbox_raw = args.inbox or os.environ.get("VIDEO_INBOX_DIR") or "/data/inbox"
    exts = tuple(e.strip().lower().lstrip(".") for e in args.extensions.split(",") if e.strip())

    print("=== Katbook VIP — S3 batch import ===")
    print(f"bucket={args.bucket!r} prefix={args.prefix!r} region={region} exts={','.join(exts)}")
    print(f"api={api_url} submit={args.submit} skip_existing={args.skip_existing} "
          f"delete_local={args.delete_local} max_parallel={args.max_parallel}")

    try:
        s3 = make_s3_client(region)
        verify_bucket(s3, args.bucket)
        keys = list_video_keys(s3, args.bucket, args.prefix, exts)
    except BatchAbort as e:
        print(f"\nFATAL: {e}")
        return 2

    if not keys:
        print("No matching video objects found. Nothing to do.")
        return 0
    print(f"found {len(keys)} matching video object(s).")

    # skip-existing filter (by filename)
    skipped_existing_keys: list[str] = []
    if args.skip_existing:
        existing = load_existing_filenames(database_url)
        if existing is not None:
            kept = []
            for key, size in keys:
                if os.path.basename(key) in existing:
                    skipped_existing_keys.append(key)
                else:
                    kept.append((key, size))
            keys = kept

    # warn on duplicate basenames within the batch (they collide in the inbox)
    seen: dict[str, str] = {}
    for key, _ in keys:
        base = os.path.basename(key)
        if base in seen:
            print(f"  [warn] duplicate filename {base!r}: {key} collides with {seen[base]} "
                  "(same inbox path/video_id — the later one wins).")
        else:
            seen[base] = key

    if args.dry_run:
        print(f"\n--- DRY RUN: {len(keys)} file(s) would be processed "
              f"({len(skipped_existing_keys)} skipped as already-in-DB) ---")
        for i, (key, size) in enumerate(keys, 1):
            print(f"  [{i}/{len(keys)}] {key} ({_human_size(size)})")
        return 0

    # Real run — confirm the API is reachable before downloading anything.
    api = ApiClient(api_url, api_key)
    try:
        api.ping()
    except BatchAbort as e:
        print(f"\nFATAL: {e}")
        return 2

    inbox = _resolve_inbox(inbox_raw, args.submit)
    print(f"downloading into {inbox}\n")

    res = process_batch(
        api, s3, args.bucket, keys, inbox,
        submit=args.submit, force=args.force, delete_local=args.delete_local,
        max_parallel=args.max_parallel, poll=args.poll_interval, job_timeout=args.job_timeout,
    )
    res.skipped_existing += len(skipped_existing_keys)

    # ---- summary ----
    print(f"\n[{res.total}/{res.total}] Done.\n")
    print("Summary:")
    print(f"  Total matched:            {res.total + len(skipped_existing_keys)}")
    print(f"  Processed:                {res.processed} ✅")
    print(f"  Skipped (already processed / duplicate): {res.skipped_existing}")
    print(f"  Failed:                   {len(res.failures)} ❌")
    if res.failures:
        print("\nFailures (retry these):")
        for f in res.failures:
            print(f"  - [{f.stage}] {f.key}: {f.error}")
    return 1 if res.failures else 0


if __name__ == "__main__":
    sys.exit(main())
