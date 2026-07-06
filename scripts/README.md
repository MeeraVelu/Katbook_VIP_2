# scripts/ — operational CLIs

Standalone operator tools: `cli.py` (typer console for enqueue/watch/search/export),
`verify_gpu.py` (run first on the 5090), `verify_db.py` (prove the app can reach an
external/Supabase DB before `up -d`), `smoke.py` + `make_test_video.py` (CPU
end-to-end check), `reembed.py`, `backup.sh`, `export_tensorrt.py`.
