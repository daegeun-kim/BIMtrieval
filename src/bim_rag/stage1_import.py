"""Stage 1 CLI entry point: structured IFC import (entities + relationships).

Wraps ifc_to_db() from pipeline_structured. Accepts an optional --ifc-path
argument; defaults to the project's configured source IFC.

Entry point: `bim-stage1` or `python -m bim_rag.stage1_import`
Do NOT run this unless explicitly authorized.
"""

from __future__ import annotations

import argparse
import sys

from bim_rag.config import IFC_SOURCE_PATH
from bim_rag.pipeline_structured import ifc_to_db
from bim_rag.reporting import print_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage 1: Import IFC entities and relationships into PostgreSQL."
    )
    parser.add_argument(
        "--ifc-path",
        default=str(IFC_SOURCE_PATH),
        help="Path to the IFC file (default: project source IFC).",
    )
    args = parser.parse_args()

    try:
        report = ifc_to_db(args.ifc_path)
        print_report(report, label="Stage 1 Structured Import Report")
    except Exception as exc:
        print(f"[Stage 1] FAILED: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
