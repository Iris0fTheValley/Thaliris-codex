"""Render tracked instruction artifacts; never install or alter local control state.

Run with the source packages on PYTHONPATH and Python -B. --check reports drift.
Tracked native TOMLs are source review fixtures, not live Host installation or
project admission exemptions. Untracked profiles/control state are preserved.
"""
from pathlib import Path
import argparse
import subprocess

from thaliris_codex import codex_adapter, controller_instructions, roles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--core-root", type=Path, help="also sync the Core repository managed AGENTS span")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    outputs = {
        "AGENTS.md": codex_adapter.render_managed(),
        "docs/thaliris-controller.md": controller_instructions.render(),
        "docs/thaliris-role-packs.md": codex_adapter.render_role_packs(),
    }
    drift = []
    for name, expected in outputs.items():
        path = root / name
        current = path.read_text(encoding="utf-8")
        if name == "AGENTS.md":
            # Preserve any user text outside the existing valid managed span.
            span = codex_adapter._managed_span(current, "AGENTS.md")
            if span is None:
                raise ValueError("tracked AGENTS managed span missing")
            expected = current[:span[0]] + expected.rstrip("\n") + current[span[1]:]
        if current != expected:
            drift.append(name)
            if not args.check:
                path.write_text(expected, encoding="utf-8", newline="\n")
    tracked = set(subprocess.check_output(["git", "-C", str(root), "ls-files", "--", ".codex/agents"], text=True).splitlines())
    for name, (model, effort, role) in roles.agent_profiles().items():
        relative = f".codex/agents/{name}"
        if relative not in tracked:
            continue
        path = root / relative
        expected = codex_adapter._agent_profile(name[:-5], role, model, effort)
        if path.read_bytes() != expected:
            drift.append(relative)
            if not args.check:
                path.write_bytes(expected)
    if args.core_root is not None:
        # Shared semantics are authored in Core; this adapter reference is a copy.
        source = args.core_root / "docs/thaliris-routing-protocol.md"
        path = root / "docs/thaliris-routing-protocol.md"
        expected = source.read_bytes()
        if path.read_bytes() != expected:
            drift.append("docs/thaliris-routing-protocol.md")
            if not args.check:
                path.write_bytes(expected)
        path = args.core_root / "AGENTS.md"
        current = path.read_text(encoding="utf-8")
        span = codex_adapter._managed_span(current, "Core AGENTS.md")
        if span is None:
            raise ValueError("Core managed span missing")
        expected = current[:span[0]] + codex_adapter.render_managed().rstrip("\n") + current[span[1]:]
        if current != expected:
            drift.append("Core AGENTS.md")
            if not args.check:
                path.write_text(expected, encoding="utf-8", newline="\n")
    print("instruction artifacts: " + (", ".join(drift) if drift else "current"))
    return int(args.check and bool(drift))


if __name__ == "__main__":
    raise SystemExit(main())
