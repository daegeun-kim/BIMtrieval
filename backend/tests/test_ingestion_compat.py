"""backend/src/ingestion/* re-exports the existing bim_rag ingestion code
(tasks/task04.md item 11: "existing ingestion code continues working from
its current location"). These are identity checks, not reimplementations."""

from __future__ import annotations


def test_entities_shim_reexports_ifc_parser():
    from ingestion import entities as shim

    import bim_rag.ifc_parser as canonical

    assert shim.extract_canonical_json is canonical.extract_canonical_json
    assert shim.file_fingerprint is canonical.file_fingerprint
    assert shim.scan_model is canonical.scan_model
    assert shim.EXTRACTION_VERSION == canonical.EXTRACTION_VERSION


def test_relationships_shim_reexports_rel_parser():
    from ingestion import relationships as shim

    import bim_rag.rel_parser as canonical

    assert shim.extract_relationship_canonical_json is canonical.extract_relationship_canonical_json
    assert shim.extract_member_rows is canonical.extract_member_rows
    assert shim.resolve_members is canonical.resolve_members


def test_embeddings_shim_is_lazy_and_resolves_to_stage2_embed():
    from ingestion.embeddings import get_run_vector_phase

    fn = get_run_vector_phase()

    import bim_rag.stage2_embed as canonical

    assert fn is canonical.run_vector_phase
