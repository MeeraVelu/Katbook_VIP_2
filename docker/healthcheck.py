#!/usr/bin/env python
"""
docker/healthcheck.py — worker liveness probe.

The worker writes a heartbeat to Redis every HEARTBEAT_INTERVAL seconds (see
worker/heartbeat.py). This check passes if that heartbeat exists and is fresh, so
a hung worker (or one that lost the GPU) is reported unhealthy. Exit 0 = healthy.
"""

from __future__ import annotations

import os
import sys
import time


def main() -> int:
    key = "katbook:worker:heartbeat"
    max_age = int(os.environ.get("HEARTBEAT_INTERVAL", "30")) * 3
    try:
        import redis

        r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
        val = r.get(key)
        if not val:
            print("no heartbeat yet")
            return 1
        age = time.time() - float(val)
        if age > max_age:
            print(f"stale heartbeat ({age:.0f}s > {max_age}s)")
            return 1
        print(f"ok (heartbeat age {age:.0f}s)")
        return 0
    except Exception as e:
        print(f"healthcheck error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
