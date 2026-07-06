#!/usr/bin/env python
"""
verify_db.py — prove the app can reach its database (and Redis) BEFORE `up -d`.

Answers "can this box actually talk to the external DB?" for the Supabase / cloud /
native-Postgres deployment. It reads DATABASE_URL exactly the way the app does
(environment first, then `.env`), opens a real connection with psycopg, and checks:

  * the connection succeeds (host reachable + credentials + SSL correct),
  * the `vector` (pgvector) extension is installed,
  * the schema is migrated (the `videos` / `segments` tables exist),
  * (best-effort) Redis responds to PING.

Ends with a clear PASS/FAIL and remediation hints. Run it two ways:

    python scripts/verify_db.py                        # on the host (reads .env)
    docker compose exec api python scripts/verify_db.py # from inside a container
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def _p(ok: bool, msg: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")


def _load_dotenv_if_missing(*keys: str) -> None:
    """Populate os.environ from a sibling .env for keys not already set, so the
    script works on the host too (inside a container these come from env_file)."""
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
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


def _libpq_dsn(url: str) -> str:
    """psycopg wants a bare libpq URL — drop any SQLAlchemy '+driver' qualifier."""
    scheme, rest = url.split("://", 1) if "://" in url else ("postgresql", url)
    scheme = scheme.split("+", 1)[0]  # postgresql+psycopg -> postgresql
    return f"{scheme}://{rest}"


def _mask(url: str) -> str:
    """Hide the password when echoing the URL."""
    try:
        s = urlsplit(url)
        if s.password:
            netloc = s.netloc.replace(f":{s.password}@", ":***@", 1)
            return urlunsplit((s.scheme, netloc, s.path, s.query, s.fragment))
    except Exception:
        pass
    return url


def _check_redis() -> None:
    """Best-effort Redis PING (non-fatal — Redis is the bundled compose service)."""
    url = os.environ.get("REDIS_URL")
    if not url:
        print("  [skip] REDIS_URL not set")
        return
    try:
        import redis  # type: ignore

        r = redis.from_url(url, socket_connect_timeout=5)
        r.ping()
        _p(True, f"Redis PING ok ({_mask(url)})")
    except ImportError:
        print(f"  [skip] redis client not installed here ({_mask(url)}) — checked at runtime")
    except Exception as e:
        # 'redis://redis:6379' only resolves INSIDE the compose network, so a host
        # run failing here is expected and harmless.
        print(f"  [warn] Redis PING failed ({_mask(url)}): {str(e)[:80]}")
        print("         OK if this host isn't on the compose network; retry with"
              " `docker compose exec api python scripts/verify_db.py`.")


def main() -> int:
    print("=== Katbook VIP database verification ===")
    _load_dotenv_if_missing("DATABASE_URL")

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[FAIL] DATABASE_URL is not set (env) and no .env found next to the repo root.")
        print("Remediation: set DATABASE_URL in .env (see .env.production for the template).")
        return 1
    print(f"DATABASE_URL: {_mask(url)}")

    try:
        import psycopg
    except Exception as e:
        print(f"[FAIL] `import psycopg` failed: {e}")
        print("Remediation: pip install 'psycopg[binary]'  (or run inside the api container).")
        return 1

    ok = True
    try:
        with psycopg.connect(_libpq_dsn(url), connect_timeout=15) as cx:
            cur = cx.cursor()
            cur.execute("select version()")
            _p(True, f"connected -> {cur.fetchone()[0][:48]}")

            cur.execute("select 1")
            _p(cur.fetchone()[0] == 1, "SELECT 1 returned 1")

            cur.execute("select exists(select 1 from pg_extension where extname='vector')")
            has_vec = cur.fetchone()[0]
            _p(has_vec, "pgvector extension installed")
            if not has_vec:
                ok = False
                print("     -> run in the DB:  create extension if not exists vector;")

            cur.execute(
                "select to_regclass('public.videos') is not null, "
                "       to_regclass('public.segments') is not null"
            )
            v, s = cur.fetchone()
            _p(bool(v and s), f"schema migrated (videos={bool(v)}, segments={bool(s)})")
            if not (v and s):
                ok = False
                print("     -> migrate once:  alembic upgrade head")
    except Exception as e:
        ok = False
        _p(False, f"connection FAILED: {type(e).__name__}: {str(e)[:160]}")
        print("  Common causes:")
        print("   * Supabase DIRECT host (db.<ref>.supabase.co) is IPv6-only — use the")
        print("     SESSION POOLER string (aws-<n>-<region>.pooler.supabase.com:5432).")
        print("   * wrong password, or missing ?sslmode=require")
        print("   * no outbound network to the DB host/port from this machine.")

    print("\n--- Redis (bundled compose broker) ---")
    _check_redis()

    print(
        "\n"
        + (
            "RESULT: PASS - the app can reach its database. Ready for `docker compose up -d`."
            if ok
            else "RESULT: FAIL - fix the items above before deploying."
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
