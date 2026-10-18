"""Build metadata for already-built final wheels; never rebuild in a gate."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from thaliris_codex import release_identity as identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    lock = json.loads((ROOT / "release/core.lock.json").read_bytes())
    def commit(path):
        return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
    for path in (ROOT, args.core):
        if subprocess.check_output(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
            raise ValueError("release source checkout contains uncommitted tracked changes")
    if commit(args.core) != lock["commit"] or lock["repository"] != identity.CORE_REPOSITORY:
        raise ValueError("Core checkout differs from authoritative release pairing")
    adapter_commit = commit(ROOT)
    tag_commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", args.tag + "^{commit}"], text=True).strip()
    if tag_commit != adapter_commit:
        raise ValueError("release tag differs from Adapter source commit")
    artifacts = {}
    for name, pattern in (("core", "thaliris-*.whl"), ("adapter", "thaliris_codex-*.whl")):
        wheels = list(args.bundle.glob(pattern))
        if len(wheels) != 1:
            raise ValueError("release requires one final wheel per distribution")
        path = wheels[0]
        artifacts[name] = {"filename": path.name, "sha256": identity.sha256(path.read_bytes()),
            "url": f"https://github.com/{identity.REPOSITORY}/releases/download/{args.tag}/{path.name}"}
    value = {"format": identity.FORMAT, "repository": identity.REPOSITORY, "release": args.tag,
        "adapter_commit": adapter_commit, "core_commit": lock["commit"],
        "compatibility": identity.COMPATIBILITY, "artifacts": artifacts}
    identity.validate(value)
    (args.bundle / "release.json").write_bytes(identity.canonical(value))
    (args.bundle / "thaliris-bootstrap.py").write_bytes((ROOT / "scripts/thaliris-bootstrap.py").read_bytes())
    checksums = "".join(identity.sha256(path.read_bytes()) + "  " + path.name + "\n"
                        for path in sorted(args.bundle.iterdir()) if path.is_file() and path.name != "SHA256SUMS")
    (args.bundle / "SHA256SUMS").write_text(checksums, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
