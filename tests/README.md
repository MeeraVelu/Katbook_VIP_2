# tests/ — test suite

pytest suite that runs entirely on CPU with models mocked (no GPU): router, dedup,
segment math, JSON-recovery, settings/profiles, API contracts, and a Postgres
storage-idempotency integration test (skipped unless `KVIP_TEST_DATABASE_URL` is set).
Run: `pytest` (baseline: 53 passed, 1 skipped).
