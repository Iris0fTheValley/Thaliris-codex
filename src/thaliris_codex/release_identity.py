"""Release identity and installed archive provenance; versions are descriptive."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

FORMAT = "thaliris-codex-release-v1"
REPOSITORY = "Iris0fTheValley/Thaliris-codex"
CORE_REPOSITORY = "Iris0fTheValley/Thaliris"
COMPATIBILITY = {"python": ">=3.11", "maintenance": "thaliris-host-maintenance-v1",
                 "runtime": "thaliris-installed-runtime-v1", "adapter_protocol": 9,
                 "managed_hook_abi": "thaliris-hook-abi-10", "core_state_schema": 7}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def validate(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {
            "format", "repository", "release", "adapter_commit", "core_commit", "compatibility", "artifacts"}:
        raise ValueError("invalid release manifest structure")
    if value["format"] != FORMAT or value["repository"] != REPOSITORY:
        raise ValueError("unsupported release repository or format")
    if not isinstance(value["release"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value["release"]):
        raise ValueError("invalid release identity")
    for key in ("adapter_commit", "core_commit"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[0-9a-f]{40}", value[key]):
            raise ValueError("release requires full source commits")
    if value["compatibility"] != COMPATIBILITY:
        raise ValueError("unsupported release protocol/ABI compatibility")
    artifacts = value["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != {"adapter", "core"}:
        raise ValueError("release requires exact Core and Adapter artifacts")
    for name, artifact in artifacts.items():
        if not isinstance(artifact, dict) or set(artifact) != {"filename", "sha256", "url"}:
            raise ValueError("invalid release artifact")
        filename = artifact["filename"]
        prefix = "thaliris_codex-" if name == "adapter" else "thaliris-"
        if (not isinstance(filename, str) or not filename.startswith(prefix) or
                not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", filename)):
            raise ValueError("invalid release wheel filename")
        if not isinstance(artifact["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]):
            raise ValueError("invalid release wheel SHA-256")
        expected = f"https://github.com/{REPOSITORY}/releases/download/{value['release']}/{filename}"
        if artifact["url"] != expected:
            raise ValueError("artifact URL differs from selected repository/release identity")
    return value


def load(raw: bytes, expected_sha256: str) -> dict:
    # The expected digest comes from outside the manifest. A digest claimed by
    # the download itself supplies neither release selection nor authenticity.
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or sha256(raw) != expected_sha256:
        raise ValueError("externally selected release manifest SHA-256 mismatch")
    return validate(json.loads(raw))


def binding(raw: bytes, expected_sha256: str) -> dict:
    manifest = load(raw, expected_sha256)
    if canonical(manifest) != raw:
        raise ValueError("release manifest must use canonical encoding")
    return {"manifest_sha256": expected_sha256, "manifest": manifest}


def validate_binding(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"manifest_sha256", "manifest"}:
        raise ValueError("invalid complete release binding")
    manifest = validate(value["manifest"])
    if sha256(canonical(manifest)) != value["manifest_sha256"]:
        raise ValueError("release binding requires canonical manifest bytes")
    return manifest


def validate_selected(selected: dict, runtime: dict) -> None:
    """Bind BOTH installed archive hashes, already covered by runtime manifest."""
    manifest = validate_binding(selected["release_binding"])
    if selected["source_pin"] != "sha256:" + manifest["artifacts"]["adapter"]["sha256"]:
        raise ValueError("release Adapter pin differs from selected runtime")
    from .runtime_identity import _safe_file
    site = Path(runtime["package_dir"]).parent
    for name, distribution in (("adapter", "thaliris_codex"), ("core", "thaliris")):
        metadata = list(site.glob(distribution + "-*.dist-info/direct_url.json"))
        if len(metadata) != 1:
            raise ValueError(f"release {name} lacks unambiguous archive provenance")
        path = _safe_file(metadata[0])
        direct = json.loads(path.read_bytes())
        if direct.get("archive_info", {}).get("hashes", {}).get("sha256") != manifest["artifacts"][name]["sha256"]:
            raise ValueError(f"release {name} archive differs from installed provenance")
