"""Explicit, bounded project flow: parse, validate, evaluate and render ``.roclec/flow.toml``.

Pure module: no writes, no kernel state. Public API (stable):

* ``FLOW_PATH``, ``DEFAULT_VIEW``, ``STAGES`` (canonical order), ``HOOKS``, ``DECISION_STAGES``
* ``parse(raw: bytes, root: Path | None = None) -> dict``: decode + validate. The result is
  normalized (defaults filled, ``stages`` a list in canonical order) and carries ``"warnings"``
  (issue dicts, code ``FLOW_CRITERION_UNUSED``). ``root`` enables the agent-binding file check.
* ``load(root: Path) -> dict``: read ``root/FLOW_PATH`` (``FLOW_MISSING`` when absent).
* ``point(flow, name) -> dict | None``: checkpoint of a stage or hook name (``None`` if undeclared).
* ``evaluate(flow, name, evaluations, *, outcome, kind=None) -> list``: check criteria evaluations of a
  decision. With ``kind``, the approve point evaluates ``approve_criteria(flow, kind)``. A rejection cites at
  least one ``not-met`` criterion only when the point declares criteria.
* ``SUBJECT_POINTS``: decision point of each rejectable subject type.
* ``render(flow, profile_data, learning=None, skills=None) -> bytes``: generated Markdown view with a
  managed-view header. The stage table, criteria and diagram come from the flow alone; a "Knowledge
  skills" section lists the registered skill references the kernel passes (``skills``: ``[{id, path,
  components}]``) with the stages each applies to, derived from the flow's stage ``skills`` (a skill no
  stage lists applies to every stage); it is omitted when there are none, so such a view keeps its
  earlier bytes. A "Flow learning" section follows, projected by the kernel from records (``learning``,
  see ``LEARNING_KEYS``; ``None`` is a project without records). Rendering sorts every list it receives
  except flow revisions, which keep the decision order the caller gives.
* ``view_status(flow, profile_data, existing, learning=None, skills=None) -> "current"|"stale"|"missing"|"edited"``.
* ``RETRO_PATH``: project-owned retrospective the view links to (seeded, never generated).
* ``CHANGE_KINDS``, ``CHORE``: change kinds; ``kind_stages(flow, kind)`` lists the stages a kind passes
  through (``None`` when the flow does not enable it) and ``approve_criteria(flow, kind)`` the criteria
  its approval evaluates. Only ``[kinds.chore]`` is declarable: its stages must contain
  ``CHORE_REQUIRED``, may add ``CHORE_OPTIONAL`` and its ``criteria`` replace the approve checkpoint's.

Every failure is a ``model.ModelError`` with exit code 2 unless noted.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

from .config import FINDING_SEVERITIES
from .model import ModelError, need, sha, text

FLOW_PATH = ".roclec/flow.toml"
DEFAULT_VIEW = "docs/flow.md"
RETRO_PATH = "docs/flow-retro.md"
STAGES = ("foundation", "define", "approve", "design", "plan", "implement", "verify", "review",
          "integrate", "release")
HOOKS = {"pre-implement": "implement", "pre-integrate": "integrate", "handoff": "release"}
DECISION_STAGES = ("foundation", "approve", "design")
OPTIONAL_CHECKPOINT = tuple(HOOKS.values())
FORBIDDEN_CHECKPOINT = tuple(s for s in STAGES if s not in DECISION_STAGES + OPTIONAL_CHECKPOINT)
ON_REJECT = ("revise", "cancel", "defer")
EVIDENCE = ("required", "optional")
STATUSES = ("met", "not-met", "n/a")
# change approve/reject change -> approve; foundation agree/reject adr|reference -> foundation; prototypes -> design.
SUBJECT_POINTS = {"change": "approve", "adr": "foundation", "reference": "foundation", "prototype": "design"}
# Learning data the kernel projects for the view (TL.6):
# revisions [{decision, flow, actor, reason, futs: [{id, scope, finding}]}] in decision order;
# open_futs [{id, status, finding}]; rejections [{stage, subject, entity, consequence, open, decision}];
# findings [{severity, status, count}]; sessions [{role, stage, count}].
LEARNING_KEYS = ("revisions", "open_futs", "rejections", "findings", "sessions")
FINDING_STATUSES = ("open", "still-open", "fixed", "accepted", "deferred", "invalid")
# Change kinds. Evolution, fix and refactor pass every stage; a chore (no observable behavior) only those
# its project agreed under [kinds.chore]: never define, design or release, review only when listed.
CHORE = "chore"
CHANGE_KINDS = ("evolution", "fix", "refactor", CHORE)
CHORE_REQUIRED = ("approve", "plan", "implement", "verify", "integrate")
CHORE_OPTIONAL = ("review",)

ROLE_RE = re.compile(r"[a-z][a-z0-9-]*\Z")
RESERVED_RE = re.compile(r"roclec-[a-z]+\Z")
CRITERION_RE = re.compile(r"CR-[0-9]{3,}\Z")
SKILL_RE = re.compile(r"[a-z][a-z0-9-]*\Z")  # Same shape as a reference ID.
HEADER_RE = re.compile(rb"<!-- roclec-managed-view sha256=([0-9a-f]{64}) -->\Z")


def _fail(code, message, entity, remediation, **context):
    raise ModelError(code, message, exit_code=2, entity=entity, path=FLOW_PATH,
                     remediation=remediation, **context)


def _need(condition, message, entity, remediation, **context):
    if not condition:
        _fail("FLOW_INVALID", message, entity, remediation, **context)


def _table(value, entity, allowed, required=()):
    _need(isinstance(value, dict), f"{entity} must be a table", entity, f"Write {entity} as a TOML table.")
    unknown = sorted(set(value) - set(allowed))
    _need(not unknown, f"Unknown key(s) in {entity}: {', '.join(unknown)}", entity,
          f"Use only: {', '.join(allowed)}.", expected=list(allowed), actual=unknown)
    missing = [key for key in required if key not in value]
    _need(not missing, f"Missing key(s) in {entity}: {', '.join(missing)}", entity,
          f"Add: {', '.join(missing)}.", expected=list(required), actual=sorted(value))
    return value


def _relative_path(value, entity, suffix=None):
    ok = (isinstance(value, str) and value.strip() == value and value and "\\" not in value
          and "\x00" not in value and not value.startswith("/") and not re.match(r"[A-Za-z]:", value))
    parts = value.split("/") if ok else []
    ok = ok and all(p not in ("", ".", "..") for p in parts)
    _need(ok, f"{entity} must be a project-relative path without '..', absolute or backslash parts",
          entity, "Use a path like docs/name.md relative to the project root.", actual=value)
    if suffix:
        _need(value.endswith(suffix), f"{entity} must end with {suffix}", entity,
              f"Use a {suffix} path.", actual=value)
    return value


def _unique_list(value, entity, pattern=None, item="item"):
    _need(isinstance(value, list), f"{entity} must be a list", entity, f"Write {entity} as a TOML array.")
    _need(len(value) == len(set(map(str, value))), f"{entity} has duplicates", entity,
          "List each entry once.", actual=value)
    for entry in value:
        _need(isinstance(entry, str) and (pattern is None or pattern.match(entry)),
              f"Invalid {item} in {entity}", entity,
              f"Each {item} must match {pattern.pattern.rstrip('Z').rstrip(chr(92))}." if pattern else "Use strings.",
              actual=entry)
    return list(value)


def _binding(root, name):
    return (root / ".claude" / "agents" / f"{name}.md").is_file() or \
        (root / ".codex" / "agents" / f"{name}.toml").is_file()


def validate(data, root: Path | None = None):
    """Validate decoded TOML; return ``(normalized, warnings)``."""
    from .agents import contracts
    builtin = tuple(contracts())
    _table(data, "flow", ("schema", "view", "roles", "criteria", "stages", "kinds"), ("schema", "stages"))
    _need(type(data["schema"]) is int and data["schema"] == 1, "Unsupported flow schema", "schema",
          "Set schema = 1.", expected=1, actual=data["schema"])
    view = _relative_path(data.get("view", DEFAULT_VIEW), "view", ".md")
    # Hidden top-level folders (.roclec/, .claude/, .codex/, .agents/, .specify/...) belong to Roclec,
    # its installer or other tools; a generated document there would collide with their writers.
    _need(not view.startswith("."), "view must not be under a hidden folder such as .roclec/ or .claude/", "view",
          f"Use a path such as {DEFAULT_VIEW}.", actual=view)
    # Other writers own these paths: capability views and the root instruction blocks.
    _need(not view.startswith("specs/capabilities/") and view not in ("AGENTS.md", "CLAUDE.md"),
          "view collides with a file Roclec generates for another purpose", "view",
          f"Use a path such as {DEFAULT_VIEW}.", actual=view)

    roles = {}
    for name, row in _items(data.get("roles", {}), "roles"):
        entity = f"roles.{name}"
        _need(ROLE_RE.match(name), f"Invalid role name {name}", entity, "Use [a-z][a-z0-9-]*.")
        _need(name not in builtin and not RESERVED_RE.match(name),
              f"Role {name} reuses a built-in or reserved Roclec name", entity,
              f"Rename it; built-in roles are {', '.join(builtin)} and roclec-* is reserved.")
        row = _table(row, entity, ("kind", "description"), ("kind",))
        _need(row["kind"] in ("human", "agent"), "kind must be human or agent", f"{entity}.kind",
              'Set kind = "human" or "agent".', actual=row["kind"])
        if "description" in row:
            _need(text(row["description"]), "description must be nonempty text", f"{entity}.description",
                  "Write a short description or remove it.")
        if row["kind"] == "agent" and root is not None:
            _need(_binding(root, name), f"Agent role {name} has no host binding", entity,
                  f"Create .claude/agents/{name}.md or .codex/agents/{name}.toml, or use kind = \"human\".")
        roles[name] = dict(row)
    humans = {n for n, r in roles.items() if r["kind"] == "human"}
    agents = {n for n, r in roles.items() if r["kind"] == "agent"}

    criteria = {}
    for cid, row in _items(data.get("criteria", {}), "criteria"):
        entity = f"criteria.{cid}"
        _need(CRITERION_RE.match(cid), f"Invalid criterion id {cid}", entity, "Use CR-NNN (three or more digits).")
        row = _table(row, entity, ("text",), ("text",))
        _need(text(row["text"]), "text must be nonempty", f"{entity}.text", "Write the criterion text.")
        criteria[cid] = row["text"]

    declared = _items(data["stages"], "stages")
    names = [n for n, _ in declared]
    unknown = [n for n in names if n not in STAGES]
    _need(not unknown, f"Unknown stage(s): {', '.join(unknown)}", f"stages.{unknown[0] if unknown else ''}",
          f"Stages are fixed: {', '.join(STAGES)}.", expected=list(STAGES), actual=names)
    missing = [s for s in STAGES if s not in names]
    _need(not missing, f"Mandatory gate missing: {', '.join(missing)}", f"stages.{missing[0] if missing else ''}",
          f"Declare every stage: {', '.join(STAGES)}.", expected=list(STAGES), actual=names)
    by_name = dict(declared)

    stages, used = [], set()
    for name in STAGES:
        entity = f"stages.{name}"
        row = _table(by_name[name], entity, ("description", "ai", "reason", "role", "deliverables",
                                              "session_evidence", "skills", "checkpoint"),
                     ("description", "ai", "role"))
        _need(text(row["description"]), "description must be nonempty text", f"{entity}.description",
              "Describe what the stage does.")
        _need(isinstance(row["ai"], bool), "ai must be true or false", f"{entity}.ai", "Set ai = true or false.")
        if row["ai"]:
            _need("reason" not in row, "reason is only allowed when ai = false", f"{entity}.reason",
                  "Remove reason or set ai = false.")
        else:
            _need(text(row.get("reason")), "ai = false requires a reason", f"{entity}.reason",
                  "Explain why a person must perform this stage.")
        _need(name != "approve" or row["ai"] is False, "approve must have ai = false", f"{entity}.ai",
              "Only a person approves; set ai = false.")
        role = row["role"]
        _need(isinstance(role, str), "role must be a role name", f"{entity}.role", "Name a declared or built-in role.")
        if row["ai"]:
            _need(role in builtin or role in agents, f"AI stage role {role} is not a built-in or declared agent role",
                  f"{entity}.role", f"Use one of {', '.join(builtin)} or declare [roles.{role}] with kind = \"agent\".")
        else:
            _need(role in humans, f"Human stage role {role} is not a declared human role", f"{entity}.role",
                  f"Declare [roles.{role}] with kind = \"human\".")
        deliverables = _unique_list(row.get("deliverables", []), f"{entity}.deliverables", item="path")
        for path in deliverables:
            _relative_path(path, f"{entity}.deliverables")
        evidence = row.get("session_evidence", "optional")
        _need(evidence in EVIDENCE, "session_evidence must be required or optional", f"{entity}.session_evidence",
              'Use "required" or "optional".', actual=evidence)
        # Only an AI stage produces an agent session; a person's stage is attributed by its decisions.
        _need(row["ai"] or evidence != "required", "session_evidence = \"required\" needs ai = true",
              f"{entity}.session_evidence", 'Remove session_evidence or set it to "optional"; '
              "a stage with ai = false produces no agent session.", actual=evidence)
        skills = _unique_list(row.get("skills", []), f"{entity}.skills", SKILL_RE, "skill name")
        result = dict(name=name, description=row["description"], ai=row["ai"], role=role,
                      deliverables=deliverables, session_evidence=evidence, skills=skills)
        if not row["ai"]:
            result["reason"] = row["reason"]
        checkpoint = row.get("checkpoint")
        if name in DECISION_STAGES:
            _need(checkpoint is not None, f"Stage {name} requires a human checkpoint", f"{entity}.checkpoint",
                  'Add checkpoint = { decider = "<human role>", criteria = [], on_reject = "revise" }.')
        if name in FORBIDDEN_CHECKPOINT:
            _need(checkpoint is None, f"Stage {name} cannot declare a checkpoint", f"{entity}.checkpoint",
                  "Remove the checkpoint; this stage has no human decision point.")
        if checkpoint is not None:
            ent = f"{entity}.checkpoint"
            checkpoint = _table(checkpoint, ent, ("decider", "criteria", "on_reject"), ("decider", "on_reject"))
            _need(isinstance(checkpoint["decider"], str) and checkpoint["decider"] in humans, "decider must be a declared human role", f"{ent}.decider",
                  "Declare the decider under [roles] with kind = \"human\".", actual=checkpoint["decider"])
            _need(checkpoint["on_reject"] in ON_REJECT, "on_reject must be revise, cancel or defer",
                  f"{ent}.on_reject", f"Use one of {', '.join(ON_REJECT)}.", actual=checkpoint["on_reject"])
            # Handoff decides an immutable integration record: only a deferral to a follow-up change applies.
            _need(name != "release" or checkpoint["on_reject"] == "defer", "The handoff checkpoint can only defer",
                  f"{ent}.on_reject", 'Set on_reject = "defer"; QA findings go to a follow-up change captured as a FUT.',
                  actual=checkpoint["on_reject"])
            cited = _unique_list(checkpoint.get("criteria", []), f"{ent}.criteria", CRITERION_RE, "criterion id")
            undefined = [c for c in cited if c not in criteria]
            _need(not undefined, f"Undefined criterion: {', '.join(undefined)}", f"{ent}.criteria",
                  "Define it under [criteria.<ID>] or remove it.", actual=undefined)
            used.update(cited)
            result["checkpoint"] = dict(decider=checkpoint["decider"], criteria=cited,
                                        on_reject=checkpoint["on_reject"])
        stages.append(result)

    kinds = {}
    for name, row in _items(data.get("kinds", {}), "kinds"):
        entity = f"kinds.{name}"
        _need(name == CHORE, f"Kind {name} cannot be declared", entity,
              f"Only [kinds.{CHORE}] is declarable; {', '.join(k for k in CHANGE_KINDS if k != CHORE)} pass every stage.",
              expected=[CHORE], actual=name)
        row = _table(row, entity, ("stages", "criteria"), ("stages",))
        listed = _unique_list(row["stages"], f"{entity}.stages", item="stage name")
        allowed = CHORE_REQUIRED + CHORE_OPTIONAL
        extra = [s for s in listed if s not in allowed]
        _need(not extra, f"A chore cannot pass through: {', '.join(extra)}", f"{entity}.stages",
              f"A chore has no observable behavior: use {', '.join(CHORE_REQUIRED)} and optionally "
              f"{', '.join(CHORE_OPTIONAL)}; work that needs define, design or release is an evolution.",
              expected=list(allowed), actual=listed)
        absent = [s for s in CHORE_REQUIRED if s not in listed]
        _need(not absent, f"A chore must pass through: {', '.join(absent)}", f"{entity}.stages",
              f"List {', '.join(CHORE_REQUIRED)}.", expected=list(CHORE_REQUIRED), actual=listed)
        result = dict(stages=[s for s in STAGES if s in listed])
        if "criteria" in row:
            cited = _unique_list(row["criteria"], f"{entity}.criteria", CRITERION_RE, "criterion id")
            undefined = [c for c in cited if c not in criteria]
            _need(not undefined, f"Undefined criterion: {', '.join(undefined)}", f"{entity}.criteria",
                  "Define it under [criteria.<ID>] or remove it.", actual=undefined)
            used.update(cited)
            result["criteria"] = cited
        kinds[name] = result

    warnings = [ModelError("FLOW_CRITERION_UNUSED", f"Criterion {cid} is not cited by any checkpoint",
                           entity=f"criteria.{cid}", path=FLOW_PATH,
                           remediation="Cite it in a checkpoint or remove it.").issue | {"severity": "warning"}
                for cid in sorted(criteria) if cid not in used]
    flow = dict(schema=1, view=view, roles=roles, criteria=criteria, stages=stages)
    if kinds:
        flow["kinds"] = kinds  # Omitted when none: earlier flows keep their normalized shape.
    return flow, warnings


def kind_stages(flow, kind):
    """Stages a change of `kind` passes through, in canonical order; None when the flow does not enable it."""
    need(kind in CHANGE_KINDS, "INVALID_INPUT", "Unknown change kind", exit_code=2,
         expected=list(CHANGE_KINDS), actual=kind)
    if kind != CHORE:
        return list(STAGES)
    declared = flow.get("kinds", {}).get(CHORE)
    return list(declared["stages"]) if declared else None


def approve_criteria(flow, kind):
    """Criteria an approval (or rejection) of a change of `kind` evaluates; a chore's may replace approve's."""
    declared = flow.get("kinds", {}).get(kind) if kind == CHORE else None
    if declared and "criteria" in declared:
        return list(declared["criteria"])
    checkpoint = point(flow, "approve")
    return list(checkpoint["criteria"]) if checkpoint else []


def require_kind(flow, kind, entity=None):
    """CHANGE_KIND_DISABLED unless the flow lets changes of `kind` through; returns its stages."""
    stages = kind_stages(flow, kind)
    if stages is None:
        raise ModelError("CHANGE_KIND_DISABLED", f"The project flow does not enable {kind} changes", exit_code=2,
                         entity=entity, path=FLOW_PATH, expected=f"[kinds.{kind}]",
                         remediation=f"Add [kinds.{kind}] with stages = {list(CHORE_REQUIRED)} to {FLOW_PATH}, "
                                     "agree the flow again (`roclec foundation agree --ref flow`), or classify "
                                     "the work as an evolution, fix or refactor.")
    return stages


def _items(value, entity):
    _need(isinstance(value, dict), f"{entity} must be a table", entity, f"Write [{entity}.<name>] tables.")
    return sorted(value.items()) if entity != "stages" else list(value.items())


def parse(raw: bytes, root: Path | None = None) -> dict:
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        _fail("FLOW_INVALID", f"{FLOW_PATH} is not valid UTF-8 TOML: {error}", "flow",
              f"Fix the syntax of {FLOW_PATH} or restore it with `roclec skills`.")
    flow, warnings = validate(data, root)
    flow["warnings"] = warnings
    return flow


def load(root: Path) -> dict:
    path = Path(root) / FLOW_PATH
    if not path.is_file():
        raise ModelError("FLOW_MISSING", f"{FLOW_PATH} does not exist", exit_code=2, path=FLOW_PATH,
                         entity="flow", remediation="Run `roclec skills` to seed the default flow.")
    return parse(path.read_bytes(), Path(root))


def point(flow, name):
    stage = HOOKS.get(name, name)
    if stage not in DECISION_STAGES + OPTIONAL_CHECKPOINT:
        _fail("FLOW_INVALID", f"Unknown decision point {name}", "point",
              f"Use one of: {', '.join(DECISION_STAGES + OPTIONAL_CHECKPOINT + tuple(HOOKS))}.")
    for row in flow["stages"]:
        if row["name"] == stage:
            return row.get("checkpoint")
    return None


def evaluate(flow, name, evaluations, *, outcome, kind=None):
    checkpoint = point(flow, name)
    expected = sorted(checkpoint["criteria"]) if checkpoint else []
    if name == "approve" and kind is not None:
        expected = sorted(approve_criteria(flow, kind))
    need(isinstance(evaluations, list) and all(isinstance(r, dict) for r in evaluations), "INVALID_INPUT",
         "evaluations must be a list of objects", exit_code=2)
    rows = []
    for row in evaluations:
        need(set(row) <= {"id", "status", "reason"} and {"id", "status"} <= set(row) and isinstance(row["id"], str)
             and row["status"] in STATUSES and ("reason" not in row or isinstance(row["reason"], str)),
             "INVALID_INPUT", "Each evaluation needs id and status (met|not-met|n/a) and an optional reason",
             exit_code=2, actual=row)
        need(row["status"] != "n/a" or text(row.get("reason")), "CRITERIA_REASON_REQUIRED",
             f"Criterion {row['id']} is n/a and needs a reason", exit_code=2, entity=row["id"],
             remediation="Explain why the criterion does not apply.")
        rows.append({k: v for k, v in row.items() if k != "reason" or text(v)})
    actual = sorted(r["id"] for r in rows)
    need(actual == expected, "CRITERIA_MISMATCH",
         f"Evaluations must cover exactly the criteria declared for {name}", exit_code=2, entity=name,
         expected=expected, actual=actual,
         remediation="Evaluate every declared criterion once" + (", and no others." if expected else
                                                               "; this point declares none."))
    need(outcome in ("approved", "rejected"), "INVALID_INPUT", "outcome must be approved or rejected", exit_code=2)
    failing = [r["id"] for r in rows if r["status"] == "not-met"]
    if outcome == "approved":
        need(not failing, "CRITERIA_NOT_MET", f"Cannot approve with not-met criteria: {', '.join(failing)}",
             exit_code=2, entity=name, actual=failing, remediation="Reject, or revise until the criteria are met.")
    else:
        # A point without criteria can still be rejected; its evaluation is then the empty list.
        need(failing or not expected, "CRITERIA_REQUIRED", "A rejection must cite at least one not-met criterion", exit_code=2,
             entity=name, expected=expected, remediation="Mark the unmet criterion as not-met with its reason.")
    return sorted(rows, key=lambda r: r["id"])


def _cell(value):
    return str(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def _model(row, flow, profile_data):
    if flow["roles"].get(row["role"], {}).get("kind") == "human" or not row["ai"]:
        return "—"
    pinned = (profile_data or {}).get("agents", {}).get(row["role"], {})
    pairs = [f"{host} `{pinned[host]}`" for host in sorted(pinned)]
    return ", ".join(pairs) if pairs else "session model"


def _body(flow, profile_data, learning=None, knowledge=None):
    lines = ["# Project flow", "",
             f"Generated from `{FLOW_PATH}` by `roclec views --write`. Do not edit by hand.", "",
             "| Step | Stage | Description | AI | Role | Skills and model | Deliverables | Human checkpoint | Criteria | On reject |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    hook_of = {stage: hook for hook, stage in HOOKS.items()}
    for number, row in enumerate(flow["stages"], 1):
        cp = row.get("checkpoint")
        ai = "yes" if row["ai"] else f"no: {row['reason']}"
        extra = ", ".join(f"`{s}`" for s in row["skills"])
        skills = (extra + "<br>" if extra else "") + _model(row, flow, profile_data)
        deliverables = ", ".join(f"`{d}`" for d in row["deliverables"]) or "—"
        if cp:
            hook = f" ({hook_of[row['name']]})" if row["name"] in hook_of else ""
            cells = [cp["decider"] + hook, ", ".join(cp["criteria"]) or "—", cp["on_reject"]]
        else:
            cells = ["—", "—", "—"]
        values = [number, row["name"], row["description"], ai, row["role"], skills, deliverables, *cells]
        lines.append("| " + " | ".join(_cell(v) for v in values) + " |")
    lines += ["", "## Criteria", "", "| ID | Text |", "| --- | --- |"]
    lines += [f"| {cid} | {_cell(t)} |" for cid, t in sorted(flow["criteria"].items())] or ["| — | — |"]
    lines += ["", "## Diagram", "", "```mermaid", "flowchart LR"]
    for number, row in enumerate(flow["stages"], 1):
        marks = (" [person]" if not row["ai"] else "") + (" [checkpoint]" if row.get("checkpoint") else "")
        lines.append(f'  S{number}["{number}. {row["name"]}{marks}"]')
    lines.append("  " + " --> ".join(f"S{n}" for n in range(1, len(flow["stages"]) + 1)))
    lines += ["  classDef person fill:#fde68a,stroke:#92400e;", "  classDef checkpoint stroke:#1d4ed8,stroke-width:3px;"]
    people = [f"S{n}" for n, r in enumerate(flow["stages"], 1) if not r["ai"]]
    checks = [f"S{n}" for n, r in enumerate(flow["stages"], 1) if r.get("checkpoint")]
    if people:
        lines.append(f"  class {','.join(people)} person;")
    if checks:
        lines.append(f"  class {','.join(checks)} checkpoint;")
    lines += ["```", ""]
    if flow.get("kinds"):
        lines += _kinds(flow) + [""]
    if knowledge:
        lines += _skills(flow, knowledge) + [""]
    lines += _learning(flow, learning or {}) + [""]
    return "\n".join(lines).encode("utf-8")


def _kinds(flow):
    """Change kinds with a reduced lane (only a chore today), shown only when the flow declares one."""
    every = ", ".join(STAGES)
    lines = ["## Change kinds", "",
             f"Evolution, fix and refactor pass every stage ({every}). A chore has no observable behavior "
             "(scaffolding, tooling, configuration, dependency bumps): it cannot cite, add, change or retire "
             "capabilities, requirements or acceptance criteria and never joins a release. Anything a user or "
             "client could observe is an evolution. Foundation stays a prerequisite of every component.", ""]
    rows = []
    for name, row in sorted(flow["kinds"].items()):
        criteria = row.get("criteria", (point(flow, "approve") or {}).get("criteria", []))
        rows.append([name, ", ".join(row["stages"]), ", ".join(s for s in STAGES if s not in row["stages"] and s != "foundation"),
                     ", ".join(criteria) or "—"])
    return lines + _rows(("Kind", "Stages", "Skipped", "Approve criteria"), rows)


def _link(target, view):
    """Relative Markdown link from the view's folder to a project-relative target."""
    base, parts = view.split("/")[:-1], target.split("/")
    common = 0
    while common < len(base) and common < len(parts) - 1 and base[common] == parts[common]:
        common += 1
    return "/".join([".."] * (len(base) - common) + parts[common:])


def _rows(headings, rows):
    lines = ["| " + " | ".join(headings) + " |", "| " + " | ".join("---" for _ in headings) + " |"]
    return lines + ["| " + " | ".join(row) + " |" for row in rows]


def _skills(flow, skills):
    """Registered knowledge skills (TK.6): where each applies, then the skills each stage's brief lists."""
    every = [row["name"] for row in flow["stages"]]
    listed = {}
    for row in flow["stages"]:
        for name in row["skills"]:
            listed.setdefault(name, []).append(row["name"])
    rows = sorted(skills, key=lambda s: s["id"])
    lines = ["## Knowledge skills", "",
             "Registered skill references (`roclec reference add <id> --role skill`). A skill applies to its components "
             "at the stages whose `skills` list it, or at every stage when no stage lists it. "
             "`roclec inspect --change CHG-ID` gives each role this list with its fingerprints.", ""]
    lines += _rows(("Skill", "Path", "Components", "Stages"),
                   [[f"`{s['id']}`", f"[{_cell(s['path'])}]({_link(s['path'], flow['view'])})",
                     ", ".join(sorted(s["components"])), ", ".join(listed[s["id"]]) if s["id"] in listed else "every stage"]
                    for s in rows])
    lines += ["", "### Skills by stage", ""]
    by_stage = [[stage, "<br>".join(f"`{s['id']}` ({', '.join(sorted(s['components']))})" for s in rows
                                    if stage in listed.get(s["id"], every))]
                for stage in every]
    lines += _rows(("Stage", "Skills (components)"), [row for row in by_stage if row[1]])
    return lines


def _learning(flow, data):
    """Counts and lists derived from records; no scores or judgments, no generation timestamps."""
    none = "None recorded."
    order = {name: index for index, name in enumerate(STAGES)}
    lines = ["## Flow learning", "",
             "Derived from the project records by `roclec views --write`. Counts and lists only.", ""]

    lines += ["### Flow revisions", "",
              "Agreements of the process reference in decision order, with the process FUTs each one addresses.", ""]
    revisions = [[f"`{r['decision']}`", f"`{r['flow']}`", _cell(r["actor"]), _cell(r["reason"]),
                  "<br>".join(_cell(f"{f['id']} ({f.get('scope') or '—'}): {f.get('finding') or '—'}")
                              for f in sorted(r["futs"], key=lambda f: f["id"])) or "—"]
                 for r in data.get("revisions", [])]
    lines += _rows(("Decision", "Flow sha256", "Actor", "Reason", "Process FUTs addressed"), revisions) if revisions else [none]

    lines += ["", "### Open process FUTs", "", "Process FUTs captured or under evaluation that no flow agreement cites.", ""]
    futs = [[f["id"], f["status"], _cell(f["finding"])] for f in sorted(data.get("open_futs", []), key=lambda f: f["id"])]
    lines += _rows(("FUT", "Status", "Finding"), futs) if futs else [none]

    lines += ["", "### Rejections by stage", ""]
    rejections = sorted(data.get("rejections", []),
                        key=lambda r: (order.get(r["stage"], len(order)), r["stage"], r["entity"], r["subject"], r["decision"]))
    if rejections:
        stages = sorted({r["stage"] for r in rejections}, key=lambda s: (order.get(s, len(order)), s))
        lines += _rows(("Stage", "Rejections", "Open"),
                       [[s, str(sum(r["stage"] == s for r in rejections)),
                         str(sum(r["stage"] == s and r["open"] for r in rejections))] for s in stages])
        lines += [""] + _rows(("Stage", "Subject", "Entity", "Consequence", "State", "Decision"),
                              [[r["stage"], _cell(r["subject"]), _cell(r["entity"]), r["consequence"],
                                "open" if r["open"] else "closed", f"`{r['decision']}`"] for r in rejections])
    else:
        lines.append(none)

    lines += ["", "### Findings by severity and status", ""]
    counts = {(f["severity"], f["status"]): f["count"] for f in data.get("findings", []) if f["count"]}
    if counts:
        severities = list(FINDING_SEVERITIES) + sorted({s for s, _ in counts} - set(FINDING_SEVERITIES))
        statuses = list(FINDING_STATUSES) + sorted({s for _, s in counts} - set(FINDING_STATUSES))
        lines += _rows(("Severity", *statuses),
                       [[severity, *(str(counts.get((severity, status), 0)) for status in statuses)]
                        for severity in severities])
    else:
        lines.append(none)

    lines += ["", "### Stages with ai = false", ""]
    people = [[row["name"], row["role"], _cell(row["reason"])] for row in flow["stages"] if not row["ai"]]
    lines += _rows(("Stage", "Role", "Reason"), people) if people else [none]

    lines += ["", "### Agent sessions by role and stage", ""]
    sessions = {}
    for row in data.get("sessions", []):
        key = (row["role"], row["stage"])
        sessions[key] = sessions.get(key, 0) + row["count"]
    if sessions:
        columns = sorted({stage for _, stage in sessions}, key=lambda s: (order.get(s, len(order)), s))
        lines += _rows(("Role", *columns), [[role, *(str(sessions.get((role, stage), 0)) for stage in columns)]
                                            for role in sorted({role for role, _ in sessions})])
    else:
        lines.append(none)

    lines += ["", "### Retrospective", "",
              "What the records cannot show (what did not work as expected, what would change with a larger team, "
              f"which AI-use decisions to revisit) belongs in the project-owned [{RETRO_PATH}]({_link(RETRO_PATH, flow['view'])})."]
    return lines


def render(flow, profile_data, learning=None, skills=None) -> bytes:
    body = _body(flow, profile_data, learning, skills)
    return f"<!-- roclec-managed-view sha256={sha(body)} -->\n".encode() + body


def view_status(flow, profile_data, existing, learning=None, skills=None):
    if existing is None:
        return "missing"
    header, _, body = existing.partition(b"\n")
    match = HEADER_RE.match(header)
    if not match or match.group(1).decode() != sha(body):
        return "edited"
    return "current" if existing == render(flow, profile_data, learning, skills) else "stale"
