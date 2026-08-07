"""The user-owned-key and data-locality policy is real, not just documented (Task 38).

Offline: reads repository files. No database, no OpenAI, no container.

Every claim in `docs/self-hosting.md` that a reader has to take on trust is
checked here against the thing it describes. A security policy that lives only
in prose drifts from the implementation silently, and the drift is discovered by
whoever gets hurt by it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def prod_compose() -> dict:
    return yaml.safe_load((_REPO_ROOT / "compose.prod.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def base_compose() -> dict:
    return yaml.safe_load((_REPO_ROOT / "compose.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The key is the user's, and the browser never touches it
# ---------------------------------------------------------------------------


def test_the_frontend_never_handles_an_api_key():
    """The frontend talks to the local backend and nothing else.

    Collecting a key in the browser — even the user's own — teaches people to
    paste API keys into web pages, and puts the key somewhere it can leak. Only
    the backend calls OpenAI.
    """
    frontend_src = _REPO_ROOT / "frontend" / "src"
    offenders = []
    for path in frontend_src.rglob("*.ts*"):
        text = path.read_text(encoding="utf-8")
        if "OPENAI_API_KEY" in text or "openai.com" in text:
            offenders.append(path.relative_to(_REPO_ROOT).as_posix())
    assert offenders == []


def test_only_the_backend_service_receives_the_key(base_compose):
    services = base_compose["services"]
    receiving = [
        name for name, svc in services.items() if "OPENAI_API_KEY" in (svc.get("environment") or {})
    ]
    assert receiving == ["backend"]


def test_a_missing_key_is_a_supported_state_not_a_startup_failure(base_compose):
    """`:-` default, so an unset key yields empty rather than refusing to start.

    The app must remain inspectable without a key: viewer, catalog and floor
    plans work, and answering reports what is missing.
    """
    assert base_compose["services"]["backend"]["environment"]["OPENAI_API_KEY"] == (
        "${OPENAI_API_KEY:-}"
    )


# ---------------------------------------------------------------------------
# No secret reaches an image
# ---------------------------------------------------------------------------


def test_the_build_context_excludes_env_files_and_user_models():
    ignore = (_REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    entries = {line.strip() for line in ignore}
    assert ".env" in entries
    assert "ifc/" in entries
    assert "*.ifc" in entries


def test_no_dockerfile_copies_an_env_file_or_a_model():
    for dockerfile in (_REPO_ROOT / "docker").glob("*.Dockerfile"):
        text = dockerfile.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("COPY", "ADD")):
                assert ".env" not in stripped, f"{dockerfile.name}: {stripped}"
                assert ".ifc" not in stripped, f"{dockerfile.name}: {stripped}"


def test_no_committed_deployment_file_contains_a_credential_shaped_string():
    import re

    pattern = re.compile(r"sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}")
    paths = [
        _REPO_ROOT / "compose.yaml",
        _REPO_ROOT / "compose.prod.yaml",
        _REPO_ROOT / ".env.example",
        *(_REPO_ROOT / "docker").glob("*"),
    ]
    for path in paths:
        if path.is_file():
            assert not pattern.search(path.read_text(encoding="utf-8")), path.name


# ---------------------------------------------------------------------------
# The production profile is actually hardened
# ---------------------------------------------------------------------------


def test_production_requires_database_credentials_instead_of_defaulting(prod_compose):
    """`:?` not `:-`. A production database must never come up on a password
    that is published in a public Git repository."""
    env = prod_compose["services"]["db"]["environment"]
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        assert env[name].startswith("${" + name + ":?"), f"{name} has a default"


def test_the_application_containers_are_hardened(prod_compose):
    for name in ("backend", "frontend"):
        service = prod_compose["services"][name]
        assert service["read_only"] is True, name
        assert service["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in service["security_opt"], name
        assert service["restart"] == "always", name
        assert service["deploy"]["resources"]["limits"]["memory"], name


def test_developer_diagnostics_are_off_in_production(prod_compose):
    env = prod_compose["services"]["backend"]["environment"]
    assert env["ENABLE_DEV_ENDPOINTS"] == "false"
    assert env["BIM_RAG_TRACE"] == "0"


def test_the_overlay_only_extends_the_base_stack(prod_compose, base_compose):
    """A production profile that introduces new services is a second stack, and
    a second stack drifts from the one people actually test."""
    assert set(prod_compose["services"]) <= set(base_compose["services"])


def test_nothing_is_published_beyond_localhost(base_compose):
    for name, service in base_compose["services"].items():
        for mapping in service.get("ports") or []:
            assert str(mapping).startswith("127.0.0.1:"), f"{name} publishes {mapping}"


def test_the_database_is_not_published_at_all(base_compose):
    assert not base_compose["services"]["db"].get("ports")


def test_user_ifc_files_are_mounted_read_only(base_compose):
    """The import container must not be able to modify a source model."""
    mounts = base_compose["services"]["import"]["volumes"]
    ifc_mount = next(m for m in mounts if m.startswith("./ifc:"))
    assert ifc_mount.endswith(":ro")


# ---------------------------------------------------------------------------
# The documented boundary
# ---------------------------------------------------------------------------


def test_self_hosting_docs_state_the_public_repo_versus_your_instance_boundary():
    text = (_REPO_ROOT / "docs" / "self-hosting.md").read_text(encoding="utf-8")
    prose = " ".join(text.split())
    assert "There is no hosted demo, and this is a decision rather than an omission" in prose
    assert "BIMtrieval has **no** authentication" in prose or "no authentication" in prose
    assert "your own key" in prose


# ---------------------------------------------------------------------------
# Image boundaries (see docs/container-boundaries.md)
# ---------------------------------------------------------------------------


def test_no_user_data_directory_is_copied_into_any_image():
    """IFC models, embeddings, artifacts and manifests stay on the user's disk.

    An image is pushed, pulled, cached and shared. A building model baked into
    one is somebody's property travelling somewhere nobody intended, and a
    database dump in a layer is a breach with a version tag.
    """
    forbidden = ("ifc/", "model_assets", "model_semantics", ".env", "pgdata")
    for dockerfile in (_REPO_ROOT / "docker").glob("*.Dockerfile"):
        for line in dockerfile.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("COPY", "ADD")) and "--from=" not in stripped:
                for name in forbidden:
                    assert name not in stripped, f"{dockerfile.name}: {stripped}"


def test_the_build_context_excludes_generated_artifacts():
    entries = {
        line.strip()
        for line in (_REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    }
    for required in ("model_assets/", "model_semantics/", "ifc/", "*.ifc", ".env"):
        assert required in entries, f".dockerignore is missing {required!r}"


def test_ingestion_is_explicit_and_never_starts_with_up(base_compose):
    """`docker compose up` must not ingest anything. Parsing a 170 MB model is
    expensive and writes to the corpus; it happens because someone asked."""
    assert base_compose["services"]["import"]["profiles"] == ["tools"]


def test_no_service_watches_a_directory_or_auto_imports(base_compose):
    for name, service in base_compose["services"].items():
        command = str(service.get("command", "")) + str(service.get("entrypoint", ""))
        assert "watch" not in command.lower(), name


def test_schema_setup_uses_the_light_image_not_the_ingestion_one(base_compose):
    """Setup runs on every `up`. On the ingestion image that meant pulling
    2.3 GB to execute a handful of DDL statements."""
    setup = base_compose["services"]["setup"]
    assert setup["build"]["dockerfile"] == "docker/dbinit.Dockerfile"
    assert base_compose["services"]["import"]["build"]["dockerfile"] == (
        "docker/ingestion.Dockerfile"
    )
    # Schema setup neither reads an IFC nor writes an artifact.
    assert not setup.get("volumes")


def test_the_dbinit_image_cannot_regain_the_heavy_stack():
    """Installed with --no-deps and an explicit dependency list, so ingestion's
    dependency list growing cannot silently re-add IfcOpenShell or torch."""
    text = (_REPO_ROOT / "docker" / "dbinit.Dockerfile").read_text(encoding="utf-8")
    assert "--no-deps ./ingestion" in text
    for heavy in ("ifcopenshell", "torch", "sentence-transformers"):
        assert f"pip install {heavy}" not in text


def test_db_init_imports_without_ifcopenshell_torch_or_transformers():
    """The load-bearing assertion behind the split image.

    If a future edit makes db_admin.init_db reach a heavy dependency, this fails
    here in the offline gate rather than at `docker compose up`.
    """
    import subprocess
    import sys

    probe = (
        "import sys\n"
        "for m in ('ifcopenshell', 'torch', 'sentence_transformers'):\n"
        "    sys.modules[m] = None\n"
        "sys.path.insert(0, r'%s')\n"
        "import bim_rag.db_admin.init_db\n"
        "import bim_rag.db_admin.migrations as g\n"
        "assert g.discover(), 'no migrations found'\n"
        "print('ok')\n"
    ) % (_REPO_ROOT / "ingestion" / "src")

    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert result.returncode == 0, (
        "db-init's import chain reaches a heavy dependency:\n" + result.stderr[-1500:]
    )


def test_the_backend_image_keeps_the_query_embedding_runtime():
    """RAG needs it. A smaller backend image that cannot answer semantic
    questions would be a smaller image and a worse product."""
    text = (_REPO_ROOT / "docker" / "backend.Dockerfile").read_text(encoding="utf-8")
    assert "torch" in text
    assert "sentence-transformers" in text
    # From the CPU index: the container must run without the owner's GPU.
    assert "download.pytorch.org/whl/cpu" in text


def test_model_weights_are_cached_in_a_volume_not_baked_in(base_compose):
    backend = base_compose["services"]["backend"]
    assert any("hfcache" in str(v) for v in backend["volumes"])
    text = (_REPO_ROOT / "docker" / "backend.Dockerfile").read_text(encoding="utf-8")
    # Downloading weights at build time would put them in a layer.
    assert "snapshot_download" not in text
    assert "SentenceTransformer(" not in text


def test_the_container_validation_fixture_is_small_and_ours():
    """Validate the container path with this, not a licensed building model."""
    fixture = _REPO_ROOT / "frontend" / "tests" / "fixtures" / "smoke-wall.ifc"
    assert fixture.is_file()
    assert fixture.stat().st_size < 50_000, "the validation fixture must stay tiny"

    boundaries = (_REPO_ROOT / "docs" / "container-boundaries.md").read_text(encoding="utf-8")
    assert "smoke-wall.ifc" in boundaries
