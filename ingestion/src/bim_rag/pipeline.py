"""Convenience orchestration: run Stage 1 then Stage 2 in sequence.

Both stages remain independently callable. This script just chains them.
Entry point: `python -m bim_rag.pipeline`
DO NOT execute unless both Stage 1 and Stage 2 are individually authorized.
"""

from __future__ import annotations

import sys

from bim_rag.reporting import print_report
from bim_rag.stage1_import import run_stage1
from bim_rag.stage2_embed import run_stage2


def main() -> None:
    print("[Pipeline] Starting Stage 1...")
    try:
        r1 = run_stage1()
        print_report(r1, label="Stage 1 Report")
    except Exception as exc:
        print(f"[Pipeline] Stage 1 FAILED: {exc}", file=sys.stderr)
        sys.exit(1)

    print("[Pipeline] Starting Stage 2...")
    try:
        r2 = run_stage2()
        print_report(r2, label="Stage 2 Report")
    except Exception as exc:
        print(f"[Pipeline] Stage 2 FAILED: {exc}", file=sys.stderr)
        sys.exit(1)

    print("[Pipeline] Both stages complete.")


if __name__ == "__main__":
    main()
