#!/usr/bin/env python3
"""
kaggle_run.py — push the Katbook VIP notebook to Kaggle, run it headless on a GPU,
wait for it to finish, then mirror results down to ./results. No more opening the
Kaggle website and clicking "Run All".

    python kaggle_run.py             # push -> wait for completion -> sync results
    python kaggle_run.py --no-sync   # push -> wait only (skip local sync)
    python kaggle_run.py --push-only # fire-and-forget (push and exit immediately)
    python kaggle_run.py --status    # just print the current run status and exit

ONE-TIME SETUP
  1. pip install -r requirements-local.txt          (installs the kaggle CLI)
  2. Put your Kaggle API token at:
       Windows  : C:\\Users\\<you>\\.kaggle\\kaggle.json
       Linux/Mac: ~/.kaggle/kaggle.json   (then: chmod 600 ~/.kaggle/kaggle.json)
     (Get it from kaggle.com -> Settings -> API -> Create New Token.)
  3. In kernel-metadata.json, set dataset_sources to your video dataset slug.
  4. Run `python kaggle_run.py --push-only` ONCE to create the kernel, then open it
     on kaggle.com and attach Secrets DATABASE_URL (+ optional HF_TOKEN). Secrets
     cannot be set from the CLI; after attaching once, every later push reuses them.
  5. The notebook clones the package from GitHub, so `git push` your code BEFORE
     running this, otherwise Kaggle runs the previous commit.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
META = HERE / "kernel-metadata.json"


def kernel_id() -> str:
    if not META.exists():
        sys.exit("kernel-metadata.json not found next to this script.")
    try:
        return json.loads(META.read_text(encoding="utf-8"))["id"]
    except Exception as e:
        sys.exit(f"could not read 'id' from kernel-metadata.json: {e}")


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, capture_output=True, text=True)


def _have_cli() -> bool:
    try:
        return _run([sys.executable, "-m", "kaggle","--version"]).returncode == 0
    except FileNotFoundError:
        return False


def status(kid: str) -> str:
    r = _run([sys.executable, "-m", "kaggle","kernels", "status", kid])
    return (r.stdout or r.stderr).strip()


def wait_for_completion(kid: str, interval: int, timeout: int) -> None:
    print(f"Waiting for {kid} to finish (polling every {interval}s)...")
    t0 = time.time()
    while True:
        line = status(kid)
        print("  ", line, flush=True)
        low = line.lower()
        if "complete" in low:
            print("Kernel COMPLETE.")
            return
        if any(w in low for w in ("error", "failed", "cancel")):
            sys.exit(f"Kernel did not finish cleanly: {line}")
        if time.time() - t0 > timeout:
            sys.exit("Timed out waiting for the kernel to finish.")
        time.sleep(interval)


def main() -> None:
    ap = argparse.ArgumentParser(description="Push + run the Katbook VIP notebook on Kaggle headlessly.")
    ap.add_argument("--no-sync", action="store_true", help="don't run sync_results.py after completion")
    ap.add_argument("--push-only", action="store_true", help="push and exit without waiting")
    ap.add_argument("--status", action="store_true", help="print current run status and exit")
    ap.add_argument("--interval", type=int, default=30, help="status poll interval (seconds)")
    ap.add_argument("--timeout", type=int, default=43200, help="max wait (seconds); Kaggle caps a session at 12h")
    args = ap.parse_args()

    if not _have_cli():
        sys.exit("kaggle CLI not found. Run:  pip install -r requirements-local.txt")

    kid = kernel_id()

    if args.status:
        print(status(kid))
        return

    r = _run([sys.executable, "-m", "kaggle","kernels", "push", "-p", str(HERE)])
    print(r.stdout or r.stderr)
    if r.returncode != 0:
        sys.exit("push failed (see output above).")
    print(f"Pushed. Track it at: https://www.kaggle.com/code/{kid}")

    if args.push_only:
        return

    wait_for_completion(kid, args.interval, args.timeout)

    if not args.no_sync:
        sync = HERE / "sync_results.py"
        if sync.exists():
            print("Mirroring results from Postgres -> ./results ...")
            subprocess.run([sys.executable, str(sync)], check=False)
        else:
            print("sync_results.py not found; skipping local sync.")


if __name__ == "__main__":
    main()
