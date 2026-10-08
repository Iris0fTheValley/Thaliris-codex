"""Explicit retrieval of Controller procedures; never a child injection."""
from pathlib import Path

from . import roles


def render(runner: str = "<installed pinned runner>") -> str:
    source = Path(__file__).with_suffix(".md").read_text(encoding="utf-8")
    rows = "\n".join(
        f"| {role.replace('-', ' ').title()} | {roles.get_role(role).purpose or role} | "
        f"{roles.get_codex_binding(role).model or 'Host/user'}/{roles.get_codex_binding(role).reasoning_effort or 'selected'} |"
        for role in roles.role_choices() if role != "controller"
    )
    return source.replace("@RUNNER@", runner).replace("@ROLE_ROWS@", rows)
