"""Read-only compatibility of one managed target's on-disk role bindings.

Source contract: Codex rust-v0.162.0-alpha.17.2, commit 740e5af33c71225640e0c1c1555c514c2c93ab74,
agent-roles/src/{loader,discovery,agent_role_config}.rs and core/src/agent/role.rs.
This is not evidence of the live Host's loaded config-layer stack. When several
possible definitions disagree, refuse rather than guess its trust/priority state.
"""
from pathlib import Path
import tomllib


class ProfileUnknown(ValueError):
    pass


def _read(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProfileUnknown(f"cannot parse role/config file {path}") from exc


def _identity(value: dict, hint: str | None = None) -> str | None:
    name = value.get("name")
    if name is None:
        return hint
    if not isinstance(name, str):
        return None
    return name.strip() or hint


def _binding(value: dict, path: Path) -> tuple:
    # Native role.rs extracts direct model/effort, not ConfigToml profile/profiles.
    # features/skills reduce capabilities; they cannot replace these selections.
    # Native owns all other metadata/config validation. Do not rebuild its parser
    # or make unrelated user extensions an additional managed dispatch gate.
    for key in ("model", "model_reasoning_effort"):
        if key in value and (not isinstance(value[key], str) or not value[key].strip()):
            raise ProfileUnknown(f"invalid target {key} in {path}")
    return value.get("model"), value.get("model_reasoning_effort")


def check(root: Path, home: Path, target: str, selection: dict, *, cwd: str | None = None) -> str:
    """Empty on compatible observed bindings; diagnostic on conflict or UNKNOWN.

    TOML name is identity, including config_file remapping and legacy name hints.
    Equivalent outcomes across possible layers need no invented priority. The
    Native configured/default effort remains untouched when spawn omits it.
    """
    try:
        root = root.resolve()
        folders = [home]
        current = Path(cwd).resolve() if cwd is not None else root
        if current != root and root not in current.parents and current not in root.parents:
            raise ProfileUnknown("spawn cwd is outside the selected project")
        # Exact task navigation can select a nested repository from a parent
        # native workspace. Its child repository profiles are not loaded by
        # that Host; inspect the actual cwd layer rather than inventing one.
        boundary = current if current in root.parents else root
        folders.extend(parent / ".codex" for parent in (current, *current.parents)
                       if parent == boundary or boundary in parent.parents)
        candidates = []
        for folder in dict.fromkeys(folders):
            declared_files = set()
            config_path = folder / "config.toml"
            if config_path.exists():
                agents = _read(config_path).get("agents", {})
                # Native warns and skips an invalid agents section for this
                # layer, then still discovers files in its agents/ directory
                # and continues through other layers.
                for hint, entry in (agents.items() if isinstance(agents, dict) else ()):
                    if not isinstance(entry, dict):
                        continue  # Native agents settings are not role declarations.
                    file = entry.get("config_file")
                    if file is None:
                        continue  # Native merges a missing file from lower layers.
                    if not isinstance(file, str) or not file:
                        if hint == target:
                            raise ProfileUnknown(f"invalid target config_file in {config_path}")
                        continue
                    path = Path(file)
                    if not path.is_absolute():
                        path = folder / path
                    try:
                        value = _read(path)
                    except ProfileUnknown:
                        if hint == target:
                            raise
                        continue
                    name = _identity(value, hint)
                    if name == target:
                        candidates.append(_binding(value, path))
                    declared_files.add(path.absolute())
            directory = folder / "agents"
            if directory.exists():
                for path in sorted(directory.rglob("*.toml")):
                    if path.absolute() in declared_files:
                        continue
                    try:
                        value = _read(path)
                    except ProfileUnknown:
                        continue  # Native ignores malformed discovered definitions.
                    if _identity(value) == target:
                        candidates.append(_binding(value, path))
        if not candidates:
            raise ProfileUnknown(f"no verifiable definition of {target}")
        outcomes = set()
        for model, effort in candidates:
            for field, fixed in (("model", model), ("reasoning_effort", effort)):
                selected = selection.get(field)
                if fixed is not None and selected is not None and fixed != selected:
                    return f"THALIRIS_ROLE_PROFILE_BINDING_CONFLICT: target {target} fixes {field}={fixed}, conflicting with selected {selected}; no reservation."
            outcomes.add((model or selection.get("model"), effort or selection.get("reasoning_effort")))
        if len(outcomes) != 1:
            raise ProfileUnknown(f"same-name target definitions disagree for {target}; effective layer priority is unverified")
    except (OSError, ValueError, TypeError) as exc:
        return f"THALIRIS_ROLE_PROFILE_BINDING_UNKNOWN: {exc}; no reservation; live Host binding remains UNKNOWN."
    return ""
