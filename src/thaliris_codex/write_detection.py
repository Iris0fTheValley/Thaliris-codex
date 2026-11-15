"""Broad, deny-only detection of commands that write to the working tree.

This is a lexical heuristic, not a sandbox. It is used ONLY where a write is
already disallowed (readonly actors, ``parallel_readonly`` and other non-write
role children, fenced actors). Callers must never use it to refuse an
authorized writer; those sites keep the narrower legacy pattern.

The scan is command-aware instead of substring-based so that read commands that
merely mention a write word (``rg "rm -rf" docs``, ``git log --grep add``) are
not flagged. A command is flagged when any shell segment (split on unquoted
``; | & newline ( ) { }``) starts with a mutating command, a mutating Git
subcommand, a package install, an in-place editor, a PowerShell write cmdlet or
a script one-liner (``python -c`` / ``node -e``) that writes a file. Shell
arrays (``command`` lists of argv strings) are scanned element by element, and a
shell wrapper (``bash -lc``, ``powershell -Command``, ``cmd /c``) is unwrapped.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

_MAX_DEPTH = 4
_SEPARATORS = frozenset("\r\n;|&(){}")

_WRITE_COMMANDS = frozenset({
    "rm", "rmdir", "mv", "cp", "ln", "touch", "tee", "mkdir", "md", "del", "erase", "rd", "ren", "move", "copy",
    "xcopy", "robocopy", "chmod", "chown", "truncate", "patch",
    # PowerShell aliases of New-/Remove-/Move-/Copy-/Rename-Item.
    "ni", "ri", "mi", "cpi", "rni",
})
_POWERSHELL_WRITE_CMDLETS = frozenset({
    "out-file", "tee-object", "set-content", "add-content", "clear-content", "new-item", "remove-item", "move-item",
    "copy-item", "rename-item", "set-itemproperty", "new-itemproperty", "remove-itemproperty", "rename-itemproperty",
    "export-csv", "export-clixml", "export-alias", "set-acl",
})
_PREFIX_COMMANDS = frozenset({"sudo", "doas", "command", "exec", "time", "nohup", "nice", "builtin", "call", "env",
                              "xargs", "stdbuf", "timeout"})
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "fish", "pwsh", "powershell", "cmd"})
_SHELL_SCRIPT_FLAGS = frozenset({"-c", "-lc", "-ic", "-cl", "-command", "-commandwithargs", "/c", "/k"})
_PYTHON = re.compile(r"python[\d.]*|py|pypy[\d.]*")
_NODE = frozenset({"node", "nodejs", "bun", "deno"})
_NODE_SCRIPT_FLAGS = frozenset({"-e", "--eval", "-p", "--print", "eval"})
_PACKAGE_MANAGERS = frozenset({"npm", "pnpm", "yarn", "bun", "pip", "pip3", "uv", "poetry"})
_PACKAGE_WRITES = frozenset({"install", "add", "remove", "ci", "sync", "uninstall", "i", "update", "upgrade"})

_GIT_VALUE_OPTIONS = frozenset({"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"})
_GIT_WRITES = frozenset({
    "add", "restore", "clean", "rm", "mv", "merge", "rebase", "cherry-pick", "revert", "am", "pull", "switch",
    "apply", "commit", "reset", "checkout",
})
_GIT_WORKTREE_WRITES = frozenset({"add", "remove", "move", "prune", "lock", "unlock", "repair"})
_GIT_BRANCH_WRITE_FLAGS = ("-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy", "-f", "--force",
                           "-u", "--set-upstream-to", "--unset-upstream", "--edit-description")
_GIT_BRANCH_LIST_FLAGS = ("-l", "--list", "-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose", "--contains",
                          "--no-contains", "--merged", "--no-merged", "--points-at", "--show-current",
                          "--format", "--sort", "--column", "--no-column", "-i", "--ignore-case")
_GIT_TAG_WRITE_FLAGS = ("-d", "--delete", "-a", "-s", "-u", "-f", "--force", "-m", "-F", "-e")
_GIT_TAG_LIST_FLAGS = ("-l", "--list", "-n", "--contains", "--no-contains", "--points-at", "--merged",
                       "--no-merged", "--verify", "-v", "--format", "--sort", "--column", "-i", "--ignore-case")

_SED_IN_PLACE = re.compile(r"-[nEsrzu]*i\S*|--in-place(?:=.*)?")
_PERL_IN_PLACE = re.compile(r"-[pnlaw0-9]*i\S*")
_MODE = r"""[rRbBuU]*\\?['"][rbtU+]*[wax][rbtU+]*\\?['"]"""
_PY_WRITE = re.compile(
    r"\bopen\s*\(\s*(?:[^,()]|\([^()]*\))+,\s*(?:mode\s*=\s*)?" + _MODE
    + r"|\bmode\s*=\s*" + _MODE
    + r"|\.open\s*\(\s*" + _MODE
    + r"|\bO_(?:WRONLY|RDWR|CREAT|APPEND|TRUNC)\b"
    + r"|\.(?:write_text|write_bytes|unlink|mkdir|rmdir|touch|rename)\s*\("
    + r"|\bshutil\."
    + r"|\bos\.(?:remove|removedirs|rename|renames|replace|makedirs|mkdir|rmdir|unlink|truncate|symlink|link|chmod|chown)\b"
)
_NODE_WRITE = re.compile(
    r"\bfs\w*(?:\.promises)?\.(?:write|rm|unlink|rename|mkdir|copyFile|appendFile|rmdir|cp|truncate|symlink|link|chmod)\w*"
    r"|\.(?:writeFile|appendFile|writeFileSync|appendFileSync|rmSync|unlinkSync|renameSync|mkdirSync|copyFileSync)\b"
)
_DOTNET_WRITE = re.compile(
    r"(?i)\[(?:System\.)?IO\.File\]::\s*(?:\w*Write\w*|Append\w*|Delete|Move|Copy|Create\w*|Replace|Open|SetAttributes)\b"
    r"|\[(?:System\.)?IO\.Directory\]::\s*\w+"
)


def _name(token: str) -> str:
    base = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for suffix in (".exe", ".cmd", ".bat", ".com", ".ps1"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def _segments(text: str) -> list[list[tuple[str, bool]]]:
    """Quote-aware split into shell segments of ``(token, quoted)`` pairs."""
    segments: list[list[tuple[str, bool]]] = []
    tokens: list[tuple[str, bool]] = []
    buffer: list[str] = []
    started = quoted = False
    quote = ""
    index = 0

    def flush_token() -> None:
        nonlocal buffer, started, quoted
        if started:
            tokens.append(("".join(buffer), quoted))
        buffer, started, quoted = [], False, False

    while index < len(text):
        char = text[index]
        if quote:
            if char == quote:
                quote = ""
            elif char == "\\" and quote == '"' and text[index + 1:index + 2] == '"':
                buffer.append('"')
                index += 1
            else:
                buffer.append(char)
        elif char in "\"'":
            quote, started, quoted = char, True, True
        elif char in ("\\", "`") and text[index + 1:index + 2] in ("\r", "\n"):
            # Line continuation joins the next line to this command.
            flush_token()
            index += 2 if text[index + 1:index + 3] == "\r\n" else 1
        elif char in _SEPARATORS:
            flush_token()
            if tokens:
                segments.append(tokens[:])
                tokens.clear()
        elif char.isspace():
            flush_token()
        else:
            buffer.append(char)
            started = True
        index += 1
    flush_token()
    if tokens:
        segments.append(tokens)
    return segments


def _skip_prefixes(tokens: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """Drop wrappers, env assignments and their options so the real command leads."""
    index = 0
    while index < len(tokens):
        value, quoted = tokens[index]
        if not quoted and re.fullmatch(r"[A-Za-z_]\w*=.*", value):
            index += 1
        elif not quoted and _name(value) in _PREFIX_COMMANDS:
            index += 1
            while index < len(tokens) and not tokens[index][1] and (
                    tokens[index][0].startswith("-") or tokens[index][0].isdigit()
                    or re.fullmatch(r"[A-Za-z_]\w*=.*", tokens[index][0])):
                index += 1
        else:
            break
    return tokens[index:]


def _positionals(args: Sequence[str]) -> list[str]:
    return [value for value in args if not value.startswith("-")]


def _has_flag(args: Sequence[str], flags: Sequence[str]) -> bool:
    for arg in args:
        for flag in flags:
            if arg == flag or flag.startswith("--") and arg.startswith(flag + "=") or flag == "-n" and arg.startswith("-n"):
                return True
    return False


def _git_writes(args: list[str]) -> bool:
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in _GIT_VALUE_OPTIONS else 1
    if index >= len(args):
        return False
    sub, rest = args[index].lower(), args[index + 1:]
    if sub in _GIT_WRITES:
        return True
    if sub == "stash":
        positional = _positionals(rest)
        return not positional or positional[0].lower() not in {"list", "show"}
    if sub == "worktree":
        positional = _positionals(rest)
        return bool(positional) and positional[0].lower() in _GIT_WORKTREE_WRITES
    if sub in {"branch", "tag"}:
        write_flags = _GIT_BRANCH_WRITE_FLAGS if sub == "branch" else _GIT_TAG_WRITE_FLAGS
        list_flags = _GIT_BRANCH_LIST_FLAGS if sub == "branch" else _GIT_TAG_LIST_FLAGS
        if _has_flag(rest, write_flags):
            return True
        return bool(_positionals(rest)) and not _has_flag(rest, list_flags)
    return False


def _package_writes(name: str, args: list[str]) -> bool:
    positional = _positionals(args)
    if name == "yarn" and not positional:
        return not any(arg in {"--version", "-v", "--help", "-h"} for arg in args)
    return any(value.lower() in _PACKAGE_WRITES for value in positional[: 3 if name == "uv" else 2])


def _segment_writes(tokens: list[tuple[str, bool]], text: str, depth: int, *, argv: bool = False) -> bool:
    for value, quoted in tokens[:1] if argv else tokens:
        if not quoted and value.strip("{}();").lower() in _POWERSHELL_WRITE_CMDLETS:
            return True
    tokens = _skip_prefixes(tokens)
    if not tokens:
        return False
    head, args = _name(tokens[0][0].lstrip("$!@")), [value for value, _ in tokens[1:]]
    if head in _WRITE_COMMANDS or head in _POWERSHELL_WRITE_CMDLETS:
        return True
    if head in _SHELLS:
        lowered = [arg.lower() for arg in args]
        for position, arg in enumerate(lowered):
            if arg in _SHELL_SCRIPT_FLAGS:
                return depth < _MAX_DEPTH and _text_writes(" ".join(args[position + 1:]), depth + 1)
        return False
    if head == "git":
        return _git_writes(args)
    if head == "sed":
        return any(_SED_IN_PLACE.fullmatch(arg) for arg in args)
    if head == "perl":
        return any(_PERL_IN_PLACE.fullmatch(arg) for arg in args)
    if head == "find":
        if "-delete" in args:
            return True
        for position, arg in enumerate(args):
            if arg in {"-exec", "-execdir", "-ok", "-okdir"} and position + 1 < len(args):
                if _segment_writes([(value, False) for value in args[position + 1:]], text, depth):
                    return True
        return False
    if head in _PACKAGE_MANAGERS and _package_writes(head, args):
        return True
    if head == "uv" and "run" in args:
        return _segment_writes([(value, False) for value in args[args.index("run") + 1:]], text, depth)
    # Script runners are found at any position (``uv run python -c``); only
    # unquoted names and flags count, so searching for the words is not a hit.
    for position, (value, quoted) in enumerate(tokens):
        if quoted:
            continue
        name = _name(value)
        following = [(v, q) for v, q in tokens[position + 1:] if argv or not q]
        if _PYTHON.fullmatch(name):
            flags = [v for v, _ in following]
            if "-m" in flags and flags.index("-m") + 1 < len(flags) and _name(flags[flags.index("-m") + 1]) in {"pip", "uv"}:
                if _package_writes("pip", flags[flags.index("-m") + 2:]):
                    return True
            if any(flag == "-" or flag.startswith("-c") for flag in flags) or "<<" in text:
                if _PY_WRITE.search(text):
                    return True
        elif name in _NODE:
            flags = [v for v, _ in following]
            if any(flag in _NODE_SCRIPT_FLAGS for flag in flags) or "<<" in text:
                if _NODE_WRITE.search(text):
                    return True
    return False


def _text_writes(text: str, depth: int = 0) -> bool:
    if _DOTNET_WRITE.search(text):
        return True
    return any(_segment_writes(segment, text, depth) for segment in _segments(text))


def broad_write(command: str | Sequence[str]) -> bool:
    """True when the shell command (string or argv list) obviously writes."""
    if isinstance(command, str):
        return _text_writes(command)
    argv = [str(item) for item in command]
    if not argv:
        return False
    joined = " ".join(argv)
    if _DOTNET_WRITE.search(joined):
        return True
    # An argv list is one command and keeps its element boundaries; a shell
    # wrapper element is unwrapped (``["bash", "-lc", "rm x"]``). Only the
    # program name is matched against PowerShell cmdlets, not the arguments.
    return _segment_writes([(item, False) for item in argv], joined, 0, argv=True)
