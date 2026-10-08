"""Explicit retrieval of Controller procedures; never a child injection."""
from pathlib import Path
import os
import shlex

from . import roles

SECTIONS = {
    "startup": "Startup and admission",
    "authority": "Persistent authority",
    "task-recovery": "Task recovery",
    "host-maintenance": "Host maintenance",
    "routing": "Routing, selected context, evidence and acceptance",
    "handoff": "Handoff and operational acceptance",
    "workstreams": "Workstream endpoints and review",
    "durable": "Durable retrieval and knowledge admission",
    "completion": "Native completion and closure",
    "diagnosis": "Causal diagnosis and acceptance",
}

# Frequency belongs to the canonical Controller layer, not to shared child prompts.
RESIDENT_SECTIONS = tuple(name for name in SECTIONS if name not in {"task-recovery", "host-maintenance"})


def runner_command(path: Path, *, platform: str | None = None) -> str:
    """Quote a selected runner for the platform's documented shell syntax."""
    if (platform or os.name) == "nt":
        return "& '" + str(path).replace("'", "''") + "'"
    return shlex.quote(str(path))


def render(runner: str = "<installed pinned runner>", *, section: str | None = None) -> str:
    source = Path(__file__).with_suffix(".md").read_text(encoding="utf-8")
    rows = "\n".join(
        f"| {role.replace('-', ' ').title()} | {roles.get_role(role).purpose or role} | "
        f"{roles.get_codex_binding(role).model or 'Host/user'}/{roles.get_codex_binding(role).reasoning_effort or 'selected'} |"
        for role in roles.role_choices() if role != "controller"
    )
    rendered = source.replace("@RUNNER@", runner).replace("@ROLE_ROWS@", rows)
    if section is None:
        return rendered
    heading = "## " + SECTIONS[section] + "\n"
    selected = rendered.split(heading, 1)[1].split("\n## ", 1)[0]
    return heading + selected


def index(runner: str) -> str:
    return "# Controller procedure index\n\nNormal guidance is delivered in the required bootstrap response. " \
        "Retrieve recovery/maintenance when needed, or an exact section when context is missing. " \
        "Retrieval grants no authority.\n\n" + "\n".join(
            f"- {title}: `{runner} controller-instructions --section {name}`"
            for name, title in SECTIONS.items()
        ) + "\n"


def resident(runner: str) -> str:
    """High-frequency guidance available directly without a procedure lookup."""
    return "## Thaliris owning Controller\n\n" + "\n\n".join(
        render(runner, section=name).strip() for name in RESIDENT_SECTIONS
    ) + "\n"
