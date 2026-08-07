"""Documentation links and stale references (Tasks 39, 40, 41).

Offline: reads Markdown off disk. No database, no OpenAI, no network — external
URLs are deliberately NOT fetched, because a gate that depends on someone else's
uptime is a gate that fails for reasons unrelated to this repository.

What this catches is the thing a reviewer notices immediately and an author
never does: a README that points at a file the repository no longer has.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: `[text](target)` — the trailing `#anchor`, if any, is not resolved.
_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+?)(?:#[^)]*)?\)")
#: HTML comments do not render, so a link inside one cannot be broken. The
#: README parks its screenshot block in one until the images exist.
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def _markdown_files() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    paths = {_REPO_ROOT / name for name in listed}
    # Files created but not yet staged still have to be correct.
    paths |= set(_REPO_ROOT.glob("*.md"))
    paths |= set((_REPO_ROOT / "docs").glob("*.md"))
    paths |= set((_REPO_ROOT / "evaluation").glob("*.md"))
    return sorted(p for p in paths if p.is_file())


def _rendered(path: Path) -> str:
    """The file with HTML comments blanked out.

    Blanked rather than deleted, so reported line numbers still match the file
    a reader will open — a checker that points at the wrong line wastes exactly
    the time it was meant to save.
    """
    text = path.read_text(encoding="utf-8")
    return _HTML_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)


@pytest.fixture(scope="module")
def markdown_files() -> list[Path]:
    files = _markdown_files()
    assert len(files) > 20, "expected the repository's Markdown to be discovered"
    return files


def test_every_relative_link_resolves(markdown_files):
    broken = []
    for path in markdown_files:
        for lineno, line in enumerate(_rendered(path).splitlines(), 1):
            for target in _LINK.findall(line):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                if not (path.parent / target).resolve().exists():
                    rel = path.relative_to(_REPO_ROOT).as_posix()
                    broken.append(f"{rel}:{lineno} -> {target}")
    assert broken == [], "broken relative links:\n  " + "\n  ".join(broken)


def test_no_document_points_at_something_this_session_removed(markdown_files):
    """Stale names outlive the thing they name, and only a reader notices.

    `tasks/`, `specs/spec_v012` and `CHANGELOG.md` are exempt: recording what was
    removed is precisely their job, and a changelog that cannot name a deleted
    file is useless.
    """
    removed = {
        "Start BIM RAG.lnk": "launcher removed in Task 35",
        "ifc_original": "IFC folder moved to ifc/ in Task 34",
        "bim-pipeline": "broken entry point removed in Task 34",
        "workflow.md": "consolidated into README in Task 39",
        "PROJECT_CONTEXT.md": "removed in Task 39",
        "CODEX.md": "consolidated into AGENTS.md in Task 39",
    }
    exempt = (
        "tasks/",
        "specs/spec_v012",
        "update_plan.md",
        "docs/images/",
        "CHANGELOG.md",
    )

    hits = []
    for path in markdown_files:
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel.startswith(exempt):
            continue
        for lineno, line in enumerate(_rendered(path).splitlines(), 1):
            # A line that explains a removal is allowed to name it. Matched on
            # stems, so "replaced"/"replacing" and "removed"/"removal" all count.
            lowered = line.lower()
            if any(
                stem in lowered for stem in ("remov", "replac", "supersed", "likewise", "previous")
            ):
                continue
            for name, why in removed.items():
                if name in line:
                    hits.append(f"{rel}:{lineno} mentions {name!r} ({why})")
    assert hits == [], "stale references:\n  " + "\n  ".join(hits)


def test_the_readme_references_no_image_that_does_not_exist():
    """A broken image is the one documentation defect nobody can miss.

    The screenshot block stays inside an HTML comment until the files land, so
    the rendered README never shows a broken-image icon.
    """
    readme = _REPO_ROOT / "README.md"
    for target in re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", _rendered(readme)):
        if target.startswith(("http://", "https://")):
            continue
        assert (readme.parent / target).exists(), f"README shows a missing image: {target}"


def test_the_screenshot_checklist_exists_for_whoever_captures_them():
    """The images are not published yet; the instructions for producing them are."""
    checklist = _REPO_ROOT / "docs" / "images" / "README.md"
    assert checklist.is_file()
    text = checklist.read_text(encoding="utf-8")
    for required in ("hero.png", "floor-plan.png", "explanation.png"):
        assert required in text


def test_the_readme_is_the_current_project_name():
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# BIMtrieval")


def test_the_readme_covers_what_a_reader_needs_to_run_it(markdown_files):
    """Deep material may live in linked docs, but the README alone has to get
    the app running — otherwise the links are a scavenger hunt."""
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for required in (
        "docker compose up --build",  # quick start
        "cp .env.example .env",  # configuration
        "bim-db-init",  # database setup
        "bim-import",  # ingestion
        "docker compose down",  # shutdown
        "npm run dev",  # manual setup
        "poetry run uvicorn",  # manual setup
    ):
        assert required in readme, f"README omits {required!r}"


def test_the_readme_documents_no_upload_path():
    """IFC import is local by design. Documenting an upload would be fiction."""
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "no browser or api upload" in readme


def test_the_readme_states_its_limitations():
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    prose = " ".join(readme.split())
    assert "## What this is and is not" in readme
    for admission in (
        "Fast",  # ~25 s median
        "Multi-user",  # no auth
        "Benchmarked against a baseline",  # no comparison arm
        "Geometry-aware",  # no clash detection
    ):
        assert f"**{admission}" in prose or f"**{admission}.**" in prose, admission
