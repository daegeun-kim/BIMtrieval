"""`bim-import` — the one command that ingests a local IFC file (Task 34).

Wraps the existing idempotent `ifc_to_db()` entry point, which performs the
complete workflow: structured import (entities + relationships), semantic
manifest generation, and stored corpus vectors. Re-running it on the same file
is safe — content is fingerprinted, so an unchanged model is recognised rather
than duplicated.

Accepts a path from anywhere on disk, or a bare filename located in the
documented `ifc/` folder at the repository root, so a 170 MB model never has to
be copied to be ingested.

    bim-import "IFC Schependomlaan incl planningsdata.ifc"
    bim-import D:/models/tower.ifc
"""

from __future__ import annotations

import argparse
import sys

from bim_rag.config import get_ifc_dir, resolve_ifc_path
from bim_rag.reporting import print_report


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bim-import",
        description=(
            "Import one IFC model into PostgreSQL: structured tables, semantic "
            "manifest, and stored vectors. Idempotent."
        ),
        epilog=f"A bare filename is resolved in {get_ifc_dir()}",
    )
    parser.add_argument(
        "ifc",
        help="Path to an .ifc file, or a filename inside the repository's ifc/ folder.",
    )
    args = parser.parse_args()

    try:
        ifc_path = resolve_ifc_path(args.ifc)
    except FileNotFoundError as exc:
        print(f"[bim-import] {exc}", file=sys.stderr)
        sys.exit(1)

    # Imported here, not at module scope: this pulls in torch and the embedding
    # model stack, so `bim-import --help` stays instant.
    from bim_rag.pipeline_structured import ifc_to_db

    try:
        report = ifc_to_db(str(ifc_path))
    except Exception as exc:
        print(f"[bim-import] FAILED: {exc}", file=sys.stderr)
        print(
            "[bim-import] If the schema does not exist yet, run `bim-db-init` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    print_report(report, label="Import Report")


if __name__ == "__main__":
    main()
