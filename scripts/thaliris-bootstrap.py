#!/usr/bin/env python3
"""Standalone stdlib bootstrap for an externally selected Thaliris release.

Run with system Python 3.11+. No checkout, manual pip or manual venv is needed.
Trust this bootstrap separately before running it. The selected manifest digest
must come from a trusted external channel, never from the manifest itself.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen
import venv


def fetch(url: str, limit: int = 128 * 1024 * 1024) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("bootstrap downloads require credential-free HTTPS")
    with urlopen(url, timeout=60) as response:
        if urlsplit(response.url).scheme != "https":
            raise ValueError("bootstrap download redirected outside HTTPS")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("bootstrap download exceeds size limit")
    return raw


def bootstrap(arguments: list[str]) -> int:
    if sys.version_info < (3, 11):
        raise ValueError("bootstrap requires system Python 3.11+")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "install", "update", "repair", "uninstall", "status"])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--artifacts", type=Path, help="offline/staged bundle directory")
    args, rest = parser.parse_known_args(arguments)
    raw = (fetch(args.manifest, 1024 * 1024) if args.manifest.startswith("https://")
           else Path(args.manifest).read_bytes())
    if not re.fullmatch(r"[0-9a-f]{64}", args.manifest_sha256) or hashlib.sha256(raw).hexdigest() != args.manifest_sha256:
        raise ValueError("externally selected manifest SHA-256 mismatch")
    manifest = json.loads(raw)
    # The full schema is checked by the verified Adapter before candidate setup.
    # Before executing any package code, bound paths and BOTH archive hashes.
    if manifest.get("format") != "thaliris-codex-release-v1" or manifest.get("repository") != "Iris0fTheValley/Thaliris-codex":
        raise ValueError("unsupported release manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"core", "adapter"}:
        raise ValueError("bootstrap requires exact Core and Adapter archives")
    with tempfile.TemporaryDirectory(prefix="thaliris-bootstrap-") as temporary:
        stage = Path(temporary)
        (stage / "release.json").write_bytes(raw)
        wheels = []
        for name, artifact in artifacts.items():
            filename, expected = artifact["filename"], artifact["sha256"]
            prefix = "thaliris_codex-" if name == "adapter" else "thaliris-"
            if (not isinstance(filename, str) or not filename.startswith(prefix) or
                    not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", filename) or
                    not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
                raise ValueError("invalid bootstrap artifact identity")
            expected_url = f"https://github.com/Iris0fTheValley/Thaliris-codex/releases/download/{manifest.get('release')}/{filename}"
            if artifact["url"] != expected_url:
                raise ValueError("bootstrap artifact URL differs from selected release")
            data = (args.artifacts / filename).read_bytes() if args.artifacts else fetch(expected_url)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"bootstrap {name} archive SHA-256 mismatch")
            wheel = stage / filename
            wheel.write_bytes(data)
            wheels.append(wheel.as_uri() + "#sha256=" + expected)
        # ensurepip is used only in this disposable environment. It never lands
        # in the final runtime (runtime_setup uses with_pip=False).
        tools = stage / "tools"
        venv.EnvBuilder(with_pip=True, symlinks=False).create(tools)
        python = tools / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run([str(python), "-I", "-B", "-m", "pip", "--isolated", "install", "--no-deps", "--no-compile", *wheels],
                       check=True, stdout=sys.stderr)
        return subprocess.run([str(python), "-I", "-B", "-m", "thaliris_codex.release_manager", args.action,
            "--manifest", str(stage / "release.json"), "--manifest-sha256", args.manifest_sha256,
            "--artifacts", str(stage), *rest], check=False).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(bootstrap(sys.argv[1:]))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "loaded_host": "UNKNOWN"}))
        raise SystemExit(1)
