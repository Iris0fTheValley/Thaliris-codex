"""Explicit retrieval of Controller procedures; never a child injection."""
from pathlib import Path
import hashlib
import os
import re
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
        f"If that response is truncated, retrieve the complete copy with `{runner} controller-instructions --resident`. " \
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


def resident_digest(runner: str) -> tuple[str, int, str]:
    """Return the exact resident guidance and its stable content digest."""
    content = resident(runner)
    encoded = content.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(encoded), content


def delivered_resident(runner: str) -> str:
    """Wrap the full guidance with boundaries that expose truncated output."""
    digest, byte_count, content = resident_digest(runner)
    return (
        "<!-- THALIRIS CONTROLLER GUIDANCE BEGIN -->\n"
        f"{content}\n"
        f"<!-- THALIRIS CONTROLLER GUIDANCE END sha256={digest} utf8_bytes={byte_count} -->\n"
    )


def guidance_delivery_fields(runner: str, acknowledged_sha256: str | None = None) -> dict[str, object]:
    """Include current guidance unless its exact complete digest was acknowledged.

    The digest is a rendering hint only. It grants no task, session, Host, or
    control authority, and no delivery state is persisted between invocations.
    """
    digest, byte_count, content = resident_digest(runner)
    valid_acknowledgement = (
        isinstance(acknowledged_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", acknowledged_sha256) is not None
    )
    matched = valid_acknowledgement and acknowledged_sha256 == digest
    fields: dict[str, object] = {
        "controller_guidance_delivery": "OMITTED_ACKNOWLEDGED" if matched else "INCLUDED",
        "controller_guidance_sha256": digest,
        "controller_guidance_utf8_bytes": byte_count,
    }
    if matched:
        return fields
    if acknowledged_sha256 is None:
        fields["controller_guidance_delivery_reason"] = "NO_PRIOR_DIGEST"
    elif not valid_acknowledgement:
        fields["controller_guidance_delivery_reason"] = "INVALID_DIGEST"
    else:
        fields["controller_guidance_delivery_reason"] = "GUIDANCE_CHANGED"
    fields["controller_guidance"] = (
        "<!-- THALIRIS CONTROLLER GUIDANCE BEGIN -->\n"
        f"{content}\n"
        f"<!-- THALIRIS CONTROLLER GUIDANCE END sha256={digest} utf8_bytes={byte_count} -->\n"
    )
    return fields
