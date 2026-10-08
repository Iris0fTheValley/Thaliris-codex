"""Explicit retrieval of Controller procedures; never a child injection."""
from pathlib import Path

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
}


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
    return "# Controller procedure index\n\nRetrieve only the procedure needed for the next operation. " \
        "Retrieval grants no authority.\n\n" + "\n".join(
            f"- {title}: `{runner} controller-instructions --section {name}`"
            for name, title in SECTIONS.items()
        ) + "\n"
