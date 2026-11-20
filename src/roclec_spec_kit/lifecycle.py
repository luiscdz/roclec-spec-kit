"""Feature selection and guarded lifecycle changes shared by all agent surfaces."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re

from .config import Project
from .workflow import Spec, State, _check_ready, _check_spec, check_coverage, task_errors, tasks_for, section


class LifecycleError(ValueError):
    pass


def resolve_spec(project: Project, state: State, target: str | None) -> Spec:
    if not target:
        path = project.root / ".roclec/feature.json"
        try:
            target = json.loads(path.read_text(encoding="utf-8"))["spec"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise LifecycleError("select a spec ID or run `roclec use NNN` first") from exc
    if not isinstance(target, str):
        raise LifecycleError("invalid saved selection; run `roclec use NNN` to replace it")
    aid = None
    match = re.fullmatch(r"(.+)-(A[1-9]\d*)", target)
    if match:
        target, aid = match.groups()
    matches = [spec for spec in state.specs if target in {spec.id, spec.name}]
    if len(matches) != 1:
        raise LifecycleError(f"spec {target!r} is missing or ambiguous")
    spec = matches[0]
    if aid and aid not in spec.amendments:
        raise LifecycleError(f"unknown amendment {aid}")
    return replace(spec, amendment_id=aid)


def select_spec(project: Project, spec: Spec) -> None:
    path = project.root / ".roclec/feature.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "spec": spec.target}, indent=2) + "\n", encoding="utf-8")
    if (project.root / ".specify").is_dir():
        (project.root / ".specify/feature.json").write_text(
            json.dumps({"feature_directory": f"specs/{spec.name}", "amendment": spec.amendment_id}, indent=2) + "\n", encoding="utf-8")


def implementation_errors(project: Project, state: State, spec: Spec) -> list[str]:
    errors = _check_ready(project, spec)
    for filename in ("plan.md", "tasks.md"):
        path = spec.path / filename
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            errors.append(f"implementation needs nonempty {filename}")
    errors.extend(task_errors(project, spec, required=True))
    for component in spec.work_components:
        if component not in state.membership.get(spec.target, {}):
            errors.append(f"missing {component} release assignment")
    if spec.amendment_id:
        for component, version in state.membership.get(spec.target, {}).items():
            if any(r.component == component and r.version == version and r.status != "planning" for r in state.releases):
                if spec.amendments[spec.amendment_id].open_tasks(component):
                    errors.append(f"{component} amendment release is not planning")
    return list(dict.fromkeys(errors))


def transition_errors(project: Project, state: State, spec: Spec, target: str) -> list[str]:
    if spec.amendment_id:
        return ["amendments keep their original spec done; complete amendment tasks instead"]
    allowed = {
        "draft": {"clarified", "deferred"}, "clarified": {"ready", "deferred"},
        "ready": {"in-progress", "deferred"}, "in-progress": {"done"},
        "deferred": {"draft"}, "done": set(),
    }
    if target == spec.status:
        return list(state.errors)
    if target not in allowed.get(spec.status, set()):
        return [f"cannot transition {spec.status} to {target}"]
    errors = list(state.errors)
    if target == "clarified" and "[NEEDS CLARIFICATION" in spec.body:
        errors.append("unresolved clarification marker")
    if target == "clarified":
        candidate = Spec(spec.path, {**spec.meta, "status": target}, spec.body, spec.parse_errors)
        errors.extend(_check_spec(project, candidate))
    if target in {"ready", "in-progress", "done"}:
        errors.extend(_check_ready(project, spec))
        plan = spec.path / "plan.md"
        if not plan.is_file() or not plan.read_text(encoding="utf-8").strip():
            errors.append("ready needs nonempty plan.md")
    if target in {"in-progress", "done"}:
        errors.extend(implementation_errors(project, state, spec))
    if target == "deferred" and state.membership.get(spec.name):
        errors.append("remove planned release membership before deferring")
    if target == "done":
        body = (spec.path / "tasks.md").read_text(encoding="utf-8") if (spec.path / "tasks.md").exists() else ""
        if re.search(r"^- \[ \]", body, re.M):
            errors.append("done needs every task checked")
        done_spec = Spec(spec.path, {**spec.meta, "status": "done"}, spec.body, spec.parse_errors)
        errors.extend(check_coverage(project, State([done_spec], state.releases, state.membership, [])))
    return list(dict.fromkeys(errors))


def inspect_spec(project: Project, state: State, spec: Spec, component: str | None = None) -> dict:
    artifacts = {name: str(spec.path / name) for name in ("spec.md", "ux.md", "plan.md", "tasks.md")}
    ready_errors = list(dict.fromkeys([*_check_spec(project, spec), *_check_ready(project, spec)]))
    release_errors = list(dict.fromkeys([*state.errors, *implementation_errors(project, state, spec)]))
    if spec.amendment_id:
        next_skill = "roclec-release" if release_errors else ("roclec-implement" if spec.amendments[spec.amendment_id].open_tasks() else "roclec-converge")
    elif spec.status == "draft":
        next_skill = "roclec-clarify"
    elif spec.status == "deferred":
        next_skill = None
    elif spec.status == "done":
        next_skill = "roclec-release" if any(r.status == "planning" and spec.name in r.specs for r in state.releases) else None
    elif spec.status == "clarified" and any(project.components[c].user_facing for c in spec.components if c in project.components) and not (spec.path / "ux.md").is_file():
        next_skill = "roclec-ux"
    elif ready_errors and any("prototype" in error for error in ready_errors):
        next_skill = "roclec-prototype"
    elif not (spec.path / "plan.md").is_file() or spec.status == "clarified":
        next_skill = "roclec-plan"
    elif not (spec.path / "tasks.md").is_file() or task_errors(project, spec, required=True):
        next_skill = "roclec-tasks"
    elif release_errors:
        next_skill = "roclec-release" if all("release assignment" in error for error in release_errors) else "roclec-analyze"
    elif spec.status == "in-progress" and not re.search(r"^- \[ \]", (spec.path / "tasks.md").read_text(encoding="utf-8"), re.M):
        next_skill = "roclec-converge"
    else:
        next_skill = "roclec-implement"
    from .reviews import review_state
    rows = tasks_for(spec)
    if not spec.amendment_id:
        rows = [row for row in rows if not re.search(r"\[A\d+\]", row[2])]
    candidates = [c for c, settings in project.components.items() if Path.cwd().resolve().is_relative_to(settings.repo)]
    if component and component not in spec.work_components:
        raise LifecycleError("component is not in the selected scope")
    if component is None and len(candidates) > 1:
        raise LifecycleError("multiple components share this repository; pass --component")
    component = component or (candidates[0] if candidates else None)
    reviews = {c: review_state(project, spec, c) for c in spec.work_components}
    open_tasks = {c: [{"id": tid, "text": text} for mark, tid, text in rows if mark == " " and f"[{c}]" in text]
                  for c in spec.work_components}
    relevant = [r for c, r in reviews.items() if component is None or c == component]
    if spec.status in {"in-progress", "done"} and not any(open_tasks.values()):
        if any(r["enabled"] and r["state"] in {"missing", "incomplete", "stale"} for r in relevant):
            next_skill = "roclec-reviewer"
        elif any(r["enabled"] and r["state"] == "changes-needed" for r in relevant):
            next_skill = "roclec-implement"
    amendments = {aid: {"title": a.title, "components": a.components, "open_tasks": a.open_tasks(),
                           "releases": state.membership.get(spec.name + "-" + aid, {})}
                  for aid, a in spec.amendments.items()}
    next_target = spec.id + ("-" + spec.amendment_id if spec.amendment_id else "")
    selection_required = []
    if spec.status == "done" and not spec.amendment_id:
        active = [aid for aid, a in spec.amendments.items() if a.open_tasks(component) and (component is None or component in a.components)]
        if len(active) == 1:
            selected = replace(spec, amendment_id=active[0])
            next_target = spec.id + "-" + active[0]
            next_skill = "roclec-release" if implementation_errors(project, state, selected) else "roclec-implement"
        elif active:
            selection_required = [spec.id + "-" + aid for aid in active]
            next_skill = None
    context = None
    if component:
        component_rows = [r for r in rows if f"[{component}]" in r[2]]
        dependency_ids = {tid for _, _, text in component_rows for tid in re.findall(r"\bT\d+\b", text)}
        context = {"component": component, "in_scope": component in spec.work_components,
                   "open_tasks": open_tasks.get(component, []),
                   "acceptance_ids": sorted({ac for _, _, text in component_rows for ac in re.findall(r"\[" + re.escape(spec.id) + r"/(AC-\d{2,})\]", text)}),
                   "dependencies": [{"id": tid, "text": text} for _, tid, text in rows if tid in dependency_ids],
                   "decisions_and_deviations": {name: section(spec.body, name)
                                                for name in ("Decisions", "Changed During Implementation")},
                   "review": reviews.get(component), "release": state.membership.get(spec.target, {}).get(component)}
    return {"project": str(project.root), "spec": spec.target, "status": spec.status,
            "artifacts": artifacts, "releases": state.membership.get(spec.target, {}),
            "errors": list(state.errors),
            "ready_gate": ready_errors, "implementation_gate": release_errors,
            "next_skill": next_skill, "component": component, "session_context": context,
            "open_tasks": open_tasks, "amendments": amendments, "reviews": reviews,
            "next_target": next_target, "selection_required": selection_required}
