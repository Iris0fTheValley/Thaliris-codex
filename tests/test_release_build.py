from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest
from thaliris_codex import release_identity as identity


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root):
    git(root, "add", ".")
    git(root, "-c", "user.name=Release fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "Release fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def release_sources(tmp_path, monkeypatch):
    core = tmp_path / "core"
    adapter = tmp_path / "adapter"
    bundle = tmp_path / "bundle"
    for directory in (core, adapter):
        directory.mkdir()
        git(directory, "init", "-q")
    (core / "core.py").write_text("# fixture")
    core_commit = commit(core)
    (adapter / "release").mkdir()
    (adapter / "release/core.lock.json").write_text(json.dumps({"repository": identity.CORE_REPOSITORY, "commit": core_commit}))
    (adapter / "scripts").mkdir()
    (adapter / "scripts/thaliris-bootstrap.py").write_text("# independently selected fixture bootstrap")
    adapter_commit = commit(adapter)
    git(adapter, "tag", "vtest")
    bundle.mkdir()
    (bundle / "thaliris-0.4.6-py3-none-any.whl").write_bytes(b"already built core fixture")
    (bundle / "thaliris_codex-0.4.6-py3-none-any.whl").write_bytes(b"already built adapter fixture")
    spec = importlib.util.spec_from_file_location("release_builder", Path(__file__).resolve().parents[1] / "scripts/build-release-manifest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", adapter)
    monkeypatch.setattr(sys, "argv", ["build-release-manifest", "--bundle", str(bundle), "--core", str(core), "--tag", "vtest"])
    return module, adapter, core, bundle, adapter_commit, core_commit


def test_release_builder_binds_final_archives_exact_pairing_and_tag(release_sources):
    module, _adapter, _core, bundle, adapter_commit, core_commit = release_sources
    module.main()
    raw = (bundle / "release.json").read_bytes()
    manifest = identity.load(raw, identity.sha256(raw))
    assert manifest["adapter_commit"] == adapter_commit
    assert manifest["core_commit"] == core_commit
    assert manifest["release"] == "vtest"
    for name, artifact in manifest["artifacts"].items():
        assert artifact["sha256"] == identity.sha256((bundle / artifact["filename"]).read_bytes())
    assert identity.sha256(raw) + "  release.json\n" in (bundle / "SHA256SUMS").read_text()


@pytest.mark.parametrize("defect", ["dirty_adapter", "dirty_core", "core_pairing", "tag"])
def test_release_builder_refuses_false_source_provenance(release_sources, defect):
    module, adapter, core, _bundle, _adapter_commit, _core_commit = release_sources
    if defect == "dirty_adapter":
        (adapter / "scripts/thaliris-bootstrap.py").write_text("# uncommitted source")
    elif defect == "dirty_core":
        (core / "core.py").write_text("# uncommitted source")
    elif defect == "core_pairing":
        (core / "core.py").write_text("# different immutable Core")
        commit(core)
    else:
        (adapter / "scripts/thaliris-bootstrap.py").write_text("# source newer than release tag")
        commit(adapter)
    with pytest.raises(ValueError, match="uncommitted|authoritative release pairing|release tag"):
        module.main()


def _workflow_job(source: str, name: str) -> str:
    match = re.search(rf"(?ms)^  {re.escape(name)}:\s*\n(.*?)(?=^  [A-Za-z0-9_-]+:|\Z)", source)
    assert match is not None, f"workflow job {name!r} is missing"
    return match.group(1)


def _workflow_needs(job: str) -> set[str]:
    match = re.search(r"(?m)^    needs:\s*(?:\[([^\]]*)\]|([A-Za-z0-9_-]+))\s*$", job)
    if match is None:
        return set()
    names = match.group(1) if match.group(1) is not None else match.group(2)
    return {item.strip() for item in names.split(",") if item.strip()}


def test_release_build_and_publish_are_transitively_gated_by_source_ci():
    root = Path(__file__).resolve().parents[1]
    release = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    source = _workflow_job(release, "source-validation")
    assert re.search(r"(?m)^    uses:\s*\.\/.github/workflows/ci\.yml\s*$", source)
    assert "with:" not in source  # Release validation uses CI's reviewed core lock.
    assert re.search(r"(?m)^  workflow_call:\s*$", ci)
    assert re.search(
        r"(?ms)^  workflow_call:\s*\n    inputs:\s*\n      core_ref:\s*\n        .*?required:\s*false\s*\n        type:\s*string\s*\n        default:\s*['\"]{2}\s*$",
        ci,
    )
    assert "os.environ.get('COMPATIBILITY_REF') or json.loads(Path('release/core.lock.json').read_bytes())['commit']" in ci

    jobs = {name: _workflow_job(release, name) for name in ("source-validation", "build", "gate", "publish")}
    dependencies = {name: _workflow_needs(job) for name, job in jobs.items()}

    def depends_on(job: str, prerequisite: str, seen: set[str] | None = None) -> bool:
        seen = set() if seen is None else seen
        if job in seen:
            return False
        seen.add(job)
        return prerequisite in dependencies[job] or any(
            depends_on(parent, prerequisite, seen) for parent in dependencies[job]
        )

    for name in ("build", "gate", "publish"):
        assert depends_on(name, "source-validation"), f"{name} can run without successful source CI"
        assert not re.search(r"(?m)^    if:.*(?:always|failure|cancelled)\s*\(", jobs[name]), (
            f"{name} overrides dependency success semantics"
        )
        assert not re.search(r"(?m)^    continue-on-error:\s*true\s*$", jobs[name]), (
            f"{name} treats a failed prerequisite as successful"
        )
