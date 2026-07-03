#!/usr/bin/env python
"""
verify_gpu.py — RUN THIS FIRST on the production box.

Confirms the machine can actually run the pipeline on an RTX 5090 (Blackwell,
sm_120): prints driver / CUDA / torch versions, checks the device capability,
runs a real GPU matmul (this is what fails with "no kernel image is available for
execution on the device" when torch was NOT built for sm_120), and loads + frees a
tiny model. Ends with a clear PASS/FAIL and remediation hints.

    python scripts/verify_gpu.py
"""

from __future__ import annotations

import subprocess
import sys

BLACKWELL = (12, 0)


def _p(ok: bool, msg: str) -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")


def _nvidia_smi() -> None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        print("nvidia-smi:", out or "(no output)")
    except FileNotFoundError:
        print("nvidia-smi: NOT FOUND (install the NVIDIA driver / container toolkit)")


def main() -> int:
    print("=== Katbook VIP GPU verification ===")
    _nvidia_smi()

    try:
        import torch
    except Exception as e:
        print(f"\n[FAIL] `import torch` failed: {e}")
        print("Remediation: install torch built for CUDA 12.8:")
        print("  pip install torch --index-url https://download.pytorch.org/whl/cu128")
        return 1

    print(f"\ntorch: {torch.__version__}")
    print(f"torch CUDA build: {getattr(torch.version, 'cuda', None)}")
    print(
        f"cuDNN: {torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else 'n/a'}"
    )

    ok = True

    if not torch.cuda.is_available():
        _p(False, "torch.cuda.is_available() is False")
        print(
            "Remediation: driver 570+, CUDA 12.8+, and a cu128 torch wheel are required "
            "for Blackwell. Inside Docker, ensure the NVIDIA Container Toolkit + `--gpus all`."
        )
        return 1
    _p(True, "CUDA is available to torch")

    name = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    print(f"device: {name}  capability sm_{cap[0]}{cap[1]}  count={torch.cuda.device_count()}")

    if cap >= BLACKWELL:
        _p(True, f"device capability sm_{cap[0]}{cap[1]} >= sm_120 (Blackwell)")
    elif cap[0] >= 7:
        _p(True, f"device capability sm_{cap[0]}{cap[1]} (pre-Blackwell but supported)")
    else:
        ok = False
        _p(False, f"device capability sm_{cap[0]}{cap[1]} is too old (need sm_70+)")

    # The decisive test: run a kernel. This is what actually fails on a mismatched
    # (older) torch/CUDA stack against a Blackwell card.
    try:
        a = torch.randn(512, 512, device="cuda")
        b = torch.randn(512, 512, device="cuda")
        c = (a @ b).sum().item()
        torch.cuda.synchronize()
        _p(True, f"GPU matmul executed (checksum={c:.1f})")
    except Exception as e:
        ok = False
        _p(False, f"GPU matmul FAILED: {str(e)[:160]}")
        print("  -> classic 'older CUDA stack on Blackwell'. Install cu128 wheels:")
        print("     pip install torch --index-url https://download.pytorch.org/whl/cu128")
        print("     (or the nightly cu128/cu129 index if the stable wheel lacks sm_120)")

    # load + free a tiny model to confirm the transformers stack works end-to-end
    try:
        from transformers import AutoModel

        m = AutoModel.from_pretrained("prajjwal1/bert-tiny").to("cuda").eval()
        del m
        torch.cuda.empty_cache()
        _p(True, "loaded + freed a tiny model on the GPU")
    except Exception as e:
        _p(False, f"tiny-model load failed: {str(e)[:160]} (network or transformers issue)")

    print(
        "\n"
        + (
            "RESULT: PASS — this box is ready to run the worker."
            if ok
            else "RESULT: FAIL — fix the items above before deploying."
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
