"""Canonical agent role contracts shipped in assets/agents/ (M-28).

A contract is host- and model-neutral. Host bindings are generated from it at
installation time; the optional ``[agents.<role>]`` profile table only selects
a model per host for that binding.
"""
from __future__ import annotations

from functools import cache
from importlib.resources import files
import tomllib

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
