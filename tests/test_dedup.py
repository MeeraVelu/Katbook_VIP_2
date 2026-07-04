"""
Dedup semantics + the critical safety rule.

Only byte-identical files share a content hash (and thus a canonical). Different
content -> different hash -> NEVER treated as a duplicate. video_id is a stable
uuid5(source_path), so re-registration is idempotent.
"""

from __future__ import annotations

from api.services.videos import video_id_for
from pipeline import ingest


def _write(p, data: bytes):
    p.write_bytes(data)
    return str(p)


def test_identical_bytes_same_hash(tmp_path):
    a = _write(tmp_path / "a.mp4", b"KATBOOK" * 5000)
    b = _write(tmp_path / "b.mp4", b"KATBOOK" * 5000)  # same content, different name
    assert ingest.file_sha256(a) == ingest.file_sha256(b)


def test_different_content_different_hash(tmp_path):
    # same TOPIC, different CONTENT must never collide -> the safety rule
    a = _write(tmp_path / "pendulum_v1.mp4", b"pendulum lesson take one" * 1000)
    b = _write(tmp_path / "pendulum_v2.mp4", b"pendulum lesson take TWO" * 1000)
    assert ingest.file_sha256(a) != ingest.file_sha256(b)


def test_file_size_bytes(tmp_path):
    p = _write(tmp_path / "x.mp4", b"0123456789")
    assert ingest.file_size_bytes(p) == 10
    assert ingest.file_size_bytes(str(tmp_path / "missing.mp4")) == 0


def test_video_id_is_deterministic_and_path_scoped():
    assert video_id_for("/data/inbox/x.mp4") == video_id_for("/data/inbox/x.mp4")
    assert video_id_for("/data/inbox/x.mp4") != video_id_for("/data/inbox/y.mp4")
