"""`ingestion.ipynb` as the one-run readiness workflow (task25 §9.1).

The notebook is the single path a user runs to make a new IFC fully ready. Two
properties must hold and are easy to break by accident:

1. it CALLS the production pipeline rather than reimplementing any of it — a
   second manifest implementation living in a notebook would drift silently from
   the one ingestion actually uses;
2. it verifies all four artifacts (database rows, semantic manifest, vectors,
   viewer) before declaring a model query-ready.

These tests read the notebook as data, so they hold without executing it or
requiring a database.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "ingestion.ipynb"


@pytest.fixture(scope="module")
def notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def code_source(notebook) -> str:
    return "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"
    )


@pytest.fixture(scope="module")
def markdown_source(notebook) -> str:
    return "\n".join(
        "".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "markdown"
    )


def test_every_code_cell_parses(code_source):
    ast.parse(code_source)


def test_the_notebook_calls_the_production_pipeline(code_source):
    assert "from bim_rag.pipeline_structured import ifc_to_db" in code_source
    assert "ifc_to_db(" in code_source


def test_the_notebook_contains_no_second_manifest_implementation(code_source):
    """It may READ and DISPLAY a manifest; it may not BUILD one.

    `build_semantic_manifest` / `generate_manifest` / `write_manifest` are the
    production builder's entrypoints. Calling any of them here would mean the
    notebook can produce an artifact by a path ingestion never takes.
    """
    for builder_symbol in ("build_semantic_manifest", "generate_manifest", "write_manifest"):
        assert builder_symbol not in code_source, (
            f"the notebook calls {builder_symbol} directly; it must obtain the "
            "manifest through ifc_to_db() instead"
        )

    # Reading it back for verification is not only allowed but required.
    assert "read_manifest" in code_source


def test_the_notebook_exposes_the_semantic_generation_result(code_source):
    """§2.1: display the path, model id, fingerprint, counts, and validation."""
    for field in (
        "manifest_path",
        "manifest_content_hash",
        "manifest_semantic_record_count",
        "manifest_estimated_tokens",
        "manifest_validated",
        "source_model_id",
    ):
        assert field in code_source, f"the notebook never displays {field}"


def test_the_notebook_verifies_all_four_readiness_artifacts(code_source):
    assert "def verify_model_readiness" in code_source

    # database rows
    assert "ifc_entities" in code_source
    # vectors
    assert "rag_documents" in code_source
    # semantic manifest, matched on the CURRENT fingerprint
    assert "manifest_path(" in code_source
    assert "fingerprint_matches" in code_source
    # viewer artifact
    assert ".frag" in code_source


def test_readiness_reports_every_problem_rather_than_the_first(code_source):
    """One run must tell the user everything that is missing."""
    assert "problems" in code_source
    assert "problems.append" in code_source


def test_the_notebook_documents_idempotency(markdown_source):
    lowered = markdown_source.lower()

    assert "idempotent" in lowered
    assert "semantic" in lowered


def test_the_notebook_ends_with_a_single_run_cell(notebook):
    """One argument, one cell — the documented one-run path."""
    last = "".join(notebook["cells"][-1]["source"]).strip()

    assert last.startswith("result = run_full_ingestion(")
    assert last.count("\n") == 0
