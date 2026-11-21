"""Canonical agent role contracts shipped in assets/agents/ (M-28).

A contract is host- and model-neutral. Host bindings are generated from it at
installation time; the optional ``[agents.<role>]`` profile table only selects
a model per host for that binding.
"""
from __future__ import annotations

from functools import cache
from importlib.resources import files
import json
import re
import tomllib

from .model import need

HOSTS = ("claude", "codex")


@cache
def contracts():
    """Return {role: {"meta": dict, "body": str}} for every shipped contract."""
    result = {}
    for item in sorted(files("roclec_spec_kit").joinpath("assets/agents").iterdir(), key=lambda p: p.name):
        if not item.name.endswith(".md"):
            continue
        _, front, body = item.read_text(encoding="utf-8").split("+++\n", 2)
        meta = tomllib.loads(front)
        result[meta["role"]] = {"meta": meta, "body": body}
    return result


def subagent_roles():
    """Roles that receive a generated host definition (the coordinator is the user's session)."""
    return tuple(role for role, contract in contracts().items() if contract["meta"]["binding"] == "subagent")


def binding_name(role):
    return f"roclec-{role}"


# Host bindings (TR.3) -------------------------------------------------------

MARKER = "<!-- managed by roclec-spec-kit -->"
# `roclec-<one lowercase word>` in a host's agents folder is Roclec's reserved
# managed namespace: a file there is pruned or rejected as edited only when an
# installation manifest records it. Hyphenated names such as a consumer's
# `roclec-dev-reviewer` fall outside it.
ROLE_NAME = re.compile(r"[a-z]+")
BINDING_PATH = re.compile(r"\.claude/agents/roclec-[a-z]+\.md|\.codex/agents/roclec-[a-z]+\.toml")
# Capability -> Claude Code tools, in output order. A key ending in "-" is a
# prefix. Bash serves both checks and the CLI that records evidence.
CLAUDE_TOOLS = (("read", ("Read", "Grep", "Glob")), ("edit-", ("Edit", "Write")),
                ("run-checks", ("Bash",)), ("record-evidence", ("Bash",)))
CLAUDE_ALWAYS = ("Skill",)  # Every role loads its skills through the host.
# Codex sandbox: read-only only for a role that can do nothing but read; the
# CLI writes records and runtime logs inside the workspace otherwise.
CODEX_READ_ONLY = frozenset({"read"})


def binding_path(role, host):
    return {"claude": f".claude/agents/{binding_name(role)}.md",
            "codex": f".codex/agents/{binding_name(role)}.toml"}[host]


def is_binding_path(relative):
    """Exact shape of a generated binding path, for roles past and present."""
    return BINDING_PATH.fullmatch(relative) is not None


def claude_tools(capabilities):
    tools = []
    for capability in capabilities:
        if not any(capability == key or (key.endswith("-") and capability.startswith(key)) for key, _ in CLAUDE_TOOLS):
            raise ValueError(f"No host tools mapped for capability {capability!r}")
    for key, names in CLAUDE_TOOLS:
        if any(capability == key or (key.endswith("-") and capability.startswith(key)) for capability in capabilities):
            tools.extend(name for name in names if name not in tools)
    return tools + [name for name in CLAUDE_ALWAYS if name not in tools]


def codex_sandbox(capabilities):
    return "read-only" if set(capabilities) == CODEX_READ_ONLY else "workspace-write"


def instructions(role):
    """The contract body, plus the one line it refers to as "the listed skills"."""
    contract = contracts()[role]
    marker, title, rest = contract["body"].split("\n", 2)
    if marker != MARKER or not title.startswith("# "):
        raise ValueError(f"Contract {role!r} must start with the managed marker and a title")
    skills = ", ".join(f"`{skill}`" for skill in contract["meta"]["skills"])
    return f"{marker}\n{title}\n\nSkills: {skills}.\n{rest}"


def _single_line(value, what):
    # Printable excludes C0/C1 controls and Unicode line/paragraph separators,
    # which YAML would otherwise read as breaks.
    need(isinstance(value, str) and bool(value) and value.isprintable(), "INVALID_INPUT",
         f"{what} must be a printable single line", exit_code=2, actual=value,
         remediation="Use a plain single-line name in [agents.<role>].")
    return value


def yaml_string(value):
    """Double-quoted YAML scalar; JSON escapes are a subset of YAML's."""
    return json.dumps(_single_line(value, "YAML value"), ensure_ascii=False)


def _toml_escape(value, *, multiline):
    out = []
    for c in value:
        if c in '"\\':
            out.append("\\" + c)
        elif c == "\n" and multiline:
            out.append(c)
        elif c == "\t":
            out.append(c)
        elif ord(c) < 32 or ord(c) == 127:
            out.append({"\n": "\\n", "\r": "\\r", "\b": "\\b", "\f": "\\f"}.get(c, f"\\u{ord(c):04X}"))
        else:
            out.append(c)
    return "".join(out)


def toml_string(value, *, multiline=False):
    """TOML basic string; the multi-line form starts with a trimmed newline so
    the value round-trips exactly, and escaping every quote keeps a run of
    three from closing it."""
    if multiline:
        return '"""\n' + _toml_escape(value, multiline=True) + '"""'
    return '"' + _toml_escape(value, multiline=False) + '"'


def claude_binding(role, model=None):
    meta = contracts()[role]["meta"]
    lines = ["---", f"name: {binding_name(role)}", f"description: {yaml_string(meta['description'])}",
             f"tools: {', '.join(claude_tools(meta['capabilities']))}"]
    if model is not None:
        lines.append(f"model: {yaml_string(_single_line(model, 'Agent model'))}")
    return ("\n".join([*lines, "---", "", ""]) + instructions(role)).encode("utf-8")


def codex_binding(role, model=None):
    meta = contracts()[role]["meta"]
    lines = ["# managed by roclec-spec-kit", f"name = {toml_string(binding_name(role))}",
             f"description = {toml_string(meta['description'])}"]
    if model is not None:
        lines.append(f"model = {toml_string(_single_line(model, 'Agent model'))}")
    lines += [f"sandbox_mode = {toml_string(codex_sandbox(meta['capabilities']))}",
              f"developer_instructions = {toml_string(instructions(role), multiline=True)}"]
    return ("\n".join(lines) + "\n").encode("utf-8")


def bindings(profile):
    """{relative path: bytes} for every subagent role on every host, using the
    profile's optional per-host model (omitted to inherit the session's)."""
    result = {}
    for role in subagent_roles():
        if not ROLE_NAME.fullmatch(role):
            raise ValueError(f"Role name {role!r} cannot form a managed binding path")
        result[binding_path(role, "claude")] = claude_binding(role, profile.agent_model(role, "claude"))
        result[binding_path(role, "codex")] = codex_binding(role, profile.agent_model(role, "codex"))
    return result
