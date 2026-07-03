#!/usr/bin/env python
"""
cli.py — operator CLI for the Katbook VIP API (typer + httpx).

Talks to the running API over HTTP, so it needs no DB/ML deps. Covers the four
operator tasks: enqueue a folder/file, watch a job's progress, search, and
reprocess one video. ``export`` mirrors the DB records to local JSON (replacing
the legacy ``sync_results.py``).

    export KATBOOK_API=http://localhost:8000
    export API_KEY=...                      # if the API requires it
    python scripts/cli.py enqueue /data/inbox/lecture.mp4
    python scripts/cli.py enqueue-folder /data/inbox
    python scripts/cli.py watch <job_id>
    python scripts/cli.py search "time period of a pendulum" --mode hybrid
    python scripts/cli.py reprocess <video_id_or_path>
    python scripts/cli.py export ./results
"""

from __future__ import annotations

import os
import time

import httpx
import typer

app = typer.Typer(add_completion=False, help="Katbook VIP operator CLI")


def _base() -> str:
    return os.environ.get("KATBOOK_API", "http://localhost:8000").rstrip("/")


def _headers() -> dict:
    key = os.environ.get("API_KEY")
    return {"X-API-Key": key} if key else {}


def _client() -> httpx.Client:
    return httpx.Client(base_url=_base(), headers=_headers(), timeout=60)


@app.command()
def enqueue(path: str):
    """Register a single server-side video path for processing."""
    with _client() as c:
        r = c.post("/api/v1/videos", json={"source_path": path})
        typer.echo(r.text)
        r.raise_for_status()


@app.command("enqueue-folder")
def enqueue_folder(folder: str = typer.Argument(None), glob: str = typer.Option(None)):
    """Enqueue every video in a folder (recursively) or matching a glob."""
    with _client() as c:
        r = c.post("/api/v1/videos/batch", json={"folder": folder, "glob": glob})
        typer.echo(r.text)
        r.raise_for_status()


@app.command()
def watch(job_id: str, interval: float = 3.0):
    """Poll a job until it reaches done/failed, printing stage transitions."""
    last = None
    with _client() as c:
        while True:
            r = c.get(f"/api/v1/jobs/{job_id}")
            r.raise_for_status()
            j = r.json()
            key = (j["state"], j.get("current_stage"))
            if key != last:
                typer.echo(
                    f"[{j['state']}] stage={j.get('current_stage')} elapsed={j.get('elapsed_sec')}s"
                )
                last = key
            if j["state"] in ("done", "failed"):
                if j.get("error"):
                    typer.echo(f"error: {j['error']}")
                raise typer.Exit(0 if j["state"] == "done" else 1)
            time.sleep(interval)


@app.command()
def search(query: str, mode: str = "semantic", limit: int = 10):
    """Search processed segments (semantic | keyword | hybrid)."""
    with _client() as c:
        r = c.get("/api/v1/search", params={"q": query, "mode": mode, "limit": limit})
        r.raise_for_status()
        data = r.json()
        typer.echo(f"=== {data['mode']} | {data['count']} result(s) for {query!r} ===")
        for h in data["results"]:
            ts = f"{int(h['start_sec'] // 60)}:{int(h['start_sec'] % 60):02d}"
            typer.echo(
                f"  [{ts}] {h.get('topic')} ({h.get('subject')})  "
                f"score={h['score']:.3f}  video={str(h['video_id'])[:8]} seg={h['seg_index']}"
            )


@app.command()
def reprocess(video_or_path: str):
    """Force reprocessing of one video by source path (force=true)."""
    with _client() as c:
        r = c.post("/api/v1/videos", json={"source_path": video_or_path, "force": True})
        typer.echo(r.text)
        r.raise_for_status()


@app.command()
def export(out_dir: str = "results"):
    """Mirror every video record (with segments) from the API into local JSON."""
    import json
    from pathlib import Path

    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)
    page, size, total_written = 1, 100, 0
    with _client() as c:
        while True:
            r = c.get("/api/v1/videos", params={"page": page, "page_size": size})
            r.raise_for_status()
            body = r.json()
            for item in body["items"]:
                d = c.get(f"/api/v1/videos/{item['video_id']}")
                if d.status_code == 200:
                    rec = d.json()
                    fn = outp / f"{str(rec['video_id'])[:8]}.json"
                    fn.write_text(json.dumps(rec, indent=2, default=str))
                    total_written += 1
            if page * size >= body["total"]:
                break
            page += 1
    typer.echo(f"wrote {total_written} record(s) to {outp}")


if __name__ == "__main__":
    app()
