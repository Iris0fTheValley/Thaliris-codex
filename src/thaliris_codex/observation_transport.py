"""Lossless inline task-observe data across native shell/argv boundaries.

This is transport within the existing operation, never an authority source.
Only a literal JSON object is encoded; executable shell syntax stays visible.
"""
from __future__ import annotations

import base64
import binascii
import json

PREFIX = "utf8-base64:"
OBSERVATION_OPTION = "--observation-json"
# The one inline-JSON option each direct operation accepts. Controller writes
# use the generic --json; a readonly child keeps --observation-json.
INLINE_OPTIONS = {
    "task-observe": OBSERVATION_OPTION,
    "task-judge": "--json",
    "task-evidence-register": "--json",
    "task-update": "--json",
}


class UnsupportedShellQuote(ValueError):
    """The original shell syntax cannot safely be normalized."""


def decode(value: str) -> object:
    if value.startswith(PREFIX):
        try:
            value = base64.b64decode(value[len(PREFIX):], altchars=b"-_", validate=True).decode("utf-8")
        except (ValueError, UnicodeError, binascii.Error) as exc:
            raise ValueError("invalid task-observe inline UTF-8 transport") from exc
    return json.loads(value)


def literal_object_argument(command: str, *, powershell: bool, option: str = OBSERVATION_OPTION) -> str | None:
    """Replace one single-quoted JSON argument, preserving every other byte.

    The caller must independently prove the trusted standalone task-observe
    route. Read literal shell words, including PowerShell doubled apostrophes
    and POSIX adjacent quoted fragments. Expansions are never evaluated or
    hidden. Malformed/legacy native-escaped JSON retains its original path.
    """
    # PowerShell treats smart quotes as delimiters, including inside an ASCII
    # quoted string. Our deliberately small reader only understands ASCII
    # quotes. Refuse the whole inline command rather than hide syntax that the
    # original shell would execute. POSIX keeps these characters as data.
    if powershell and option in command and any(
            "\u2018" <= char <= "\u201f" for char in command):
        raise UnsupportedShellQuote("use JSON Unicode escapes for PowerShell smart quotes")
    words: list[tuple[str, int, int]] = []
    index = 0
    while index < len(command):
        if command[index].isspace():
            index += 1
            continue
        start = index
        value = []
        while index < len(command) and not command[index].isspace():
            char = command[index]
            if char in "'\"":
                quote = char
                index += 1
                while index < len(command):
                    char = command[index]
                    if char == quote:
                        if powershell and quote == "'" and command[index:index + 2] == "''":
                            value.append("'")
                            index += 2
                            continue
                        index += 1
                        break
                    if quote == '"' and (char in "$`" or char == "\\" and command[index:index + 2] == '\\"'):
                        return None
                    value.append(char)
                    index += 1
                else:
                    return None
            else:
                if char in "$`;&|<>()" or char == "\\" and not powershell:
                    return None
                value.append(char)
                index += 1
        words.append(("".join(value), start, index))
    options = [i for i, (word, _, _) in enumerate(words) if word == option]
    if len(options) != 1 or options[0] + 1 >= len(words):
        return None
    value, start, end = words[options[0] + 1]
    if command[start] != "'":
        return None
    try:
        body = json.loads(value)
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    try:
        encoded = PREFIX + base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    except UnicodeError:
        return None
    return command[:start] + encoded + command[end:]
