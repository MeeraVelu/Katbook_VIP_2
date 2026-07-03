#!/usr/bin/env python
"""
export_tensorrt.py — OPTIONAL: export the YOLO detector to a TensorRT engine.

Off by default. On Blackwell a TensorRT engine speeds up the (gated) YOLO stage,
but it must be built ON the target GPU with the deployed TensorRT/CUDA versions,
so this is a deliberate, manual step — not part of the image build. After export,
point ``KVIP_YOLO_MODEL`` at the generated ``.engine`` file.

    python scripts/export_tensorrt.py --model yolo11x.pt --half
    # then: export KVIP_YOLO_MODEL=yolo11x.engine

Docs: docs/DEPLOYMENT.md ("Optional: TensorRT for YOLO").
"""

from __future__ import annotations

import argparse


def main() -> int:
    ap = argparse.ArgumentParser(description="Export YOLO weights to a TensorRT engine")
    ap.add_argument("--model", default="yolo11x.pt")
    ap.add_argument("--half", action="store_true", help="FP16 engine (recommended on 5090)")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="0")
    args = ap.parse_args()

    try:
        import torch
        from ultralytics import YOLO
    except Exception as e:
        raise SystemExit(f"ultralytics/torch not available: {e}") from e

    if not torch.cuda.is_available():
        raise SystemExit("A GPU is required to build a TensorRT engine. Run this on the 5090 box.")

    print(f"exporting {args.model} -> TensorRT (half={args.half}, imgsz={args.imgsz})")
    model = YOLO(args.model)
    path = model.export(format="engine", half=args.half, imgsz=args.imgsz, device=args.device)
    print(f"wrote engine: {path}")
    print(f"set KVIP_YOLO_MODEL={path} in your .env to use it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
