"""Reader-side model of the v002 semantic manifest (task26 §5).

Public surface:

    from app.query.semantic.manifest_v002 import (
        ManifestV002, get_manifest_v002, ManifestV002UnavailableError,
        build_binder_projection, projection_json,
    )
"""

from app.query.semantic.manifest_v002.loader import (
    ManifestV002UnavailableError,
    clear_manifest_v002_cache,
    get_manifest_v002,
)
from app.query.semantic.manifest_v002.projection import (
    BinderProjection,
    build_binder_projection,
)
from app.query.semantic.manifest_v002.schema import (
    COVERAGE_CHECKED_ABSENT,
    COVERAGE_PRESENT_COMPLETE,
    COVERAGE_PRESENT_PARTIAL,
    NON_QUERYABLE_COVERAGE,
    Applicability,
    Capability,
    DerivedFloors,
    FloorBand,
    ManifestV002,
    Profile,
    StoreyRecord,
    Traversal,
    parse_manifest_v002,
)

__all__ = [
    "Applicability",
    "BinderProjection",
    "COVERAGE_CHECKED_ABSENT",
    "COVERAGE_PRESENT_COMPLETE",
    "COVERAGE_PRESENT_PARTIAL",
    "Capability",
    "DerivedFloors",
    "FloorBand",
    "ManifestV002",
    "ManifestV002UnavailableError",
    "NON_QUERYABLE_COVERAGE",
    "Profile",
    "StoreyRecord",
    "Traversal",
    "build_binder_projection",
    "clear_manifest_v002_cache",
    "get_manifest_v002",
    "parse_manifest_v002",
]
