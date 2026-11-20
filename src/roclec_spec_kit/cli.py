"""Command line interface for project-local Roclec workflows."""

from __future__ import annotations

import argparse
from datetime import date
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from .config import CONFIG_PATH, LINK_PATH, ConfigError, NAME_RE, Project, load_project, render_config
from .external_skills import SkillLockError, ensure_design_lock, read_lock, restore_external_skills
from .lifecycle import LifecycleError, implementation_errors, inspect_spec, resolve_spec, select_spec, transition_errors
from .adapter import AdapterError, install_speckit
from .workflow import (SPEC_DIR_RE, VERSION_RE, STATUSES, Spec, _check_ready, _check_spec,
                       check_coverage, check_immutable, release_criteria_errors, scan, stale_views, write_views,
                       section, tasks_for, version_key, git_commit, _release_field)


class UsageError(ValueError):
    pass


MANAGED_START = "<!-- roclec-spec-kit:begin -->"
MANAGED_END = "<!-- roclec-spec-kit:end -->"


def _assets():
    # Explicit schema-1 regression oracle, never used by the public schema-2 CLI.
    return files("roclec_spec_kit").joinpath("assets/legacy")


def _skill_names() -> list[str]:
    return sorted(path.name for path in _assets().joinpath("skills").iterdir() if path.is_dir())


def _project(args: argparse.Namespace) -> Project:
    return load_project(Path(args.project or "."))


def _spec(state, target: str) -> Spec:
    matches = [s for s in state.specs if s.name == target or s.id == target]
    if len(matches) != 1:
        raise UsageError(f"spec {target!r} is missing or ambiguous")
    return matches[0]


def _template(project: Project, kind: str, **values: str) -> str:
    path = project.root / ".roclec/templates" / f"{kind}-template.md"
    body = path.read_text(encoding="utf-8")
    for key, value in values.items():
        body = body.replace("{{" + key + "}}", value)
    return body


def _skill_changes(root: Path) -> list[tuple[Path, str]]:
    changes = []
    def visit(source, relative):
        for item in source.iterdir():
            if item.is_dir():
                visit(item, relative / item.name)
            else:
                body = item.read_text(encoding="utf-8")
                for host in (".agents", ".claude"):
                    target = root / host / "skills" / relative / item.name
                    if target.exists() and "<!-- managed by roclec-spec-kit -->" not in target.read_text(encoding="utf-8"):
                        raise UsageError(f"Will not overwrite unmanaged skill asset: {target}")
                    changes.append((target, body))
    for name in _skill_names():
        visit(_assets().joinpath("skills", name), Path(name))
    return changes


def _install_skills(root: Path) -> list[Path]:
    changes = _skill_changes(root)
    for target, body in changes:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return [target for target, _ in changes]


def _check_agent_files(root: Path) -> None:
    for filename in ("AGENTS.md", "CLAUDE.md"):
        path = root / filename
        if path.exists():
            body = path.read_text(encoding="utf-8")
            if body.count(MANAGED_START) != body.count(MANAGED_END) or body.count(MANAGED_START) > 1:
                raise UsageError(f"Malformed Roclec section in {path}")
    for relative in (".roclec/workflow.md", ".roclec/run"):
        path = root / relative
        if path.exists() and "managed by roclec-spec-kit" not in path.read_text(encoding="utf-8"):
            raise UsageError(f"Will not overwrite unmanaged file: {path}")


def _install_agent_files(root: Path, project_root: Path) -> None:
    instructions = _assets().joinpath("project/agent-instructions.md").read_text(encoding="utf-8").strip()
    block = f"{MANAGED_START}\n{instructions}\n{MANAGED_END}"
    for filename in ("AGENTS.md", "CLAUDE.md"):
        path = root / filename
        body = path.read_text(encoding="utf-8") if path.exists() else ""
        if MANAGED_START in body:
            before, remainder = body.split(MANAGED_START, 1)
            _, after = remainder.split(MANAGED_END, 1)
            updated = before + block + after
        else:
            updated = body.rstrip() + ("\n\n" if body.strip() else "") + block + "\n"
        path.write_text(updated, encoding="utf-8")
    workflow = root / ".roclec/workflow.md"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(_assets().joinpath("project/workflow.md").read_text(encoding="utf-8"), encoding="utf-8")
    if root == project_root:
        ignore = root / ".gitignore"
        contents = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
        additions = [entry for entry in (".venv/", ".roclec/feature.json", ".specify/feature.json") if entry not in contents.splitlines()]
        if additions:
            ignore.write_text(contents.rstrip() + "\n\n# Roclec local runtime and worktree selection\n" + "\n".join(additions) + "\n", encoding="utf-8")
    # Seed project-owned templates and constitution once; package refreshes preserve customization.
    if root == project_root:
        templates = root / ".roclec/templates"
        templates.mkdir(exist_ok=True)
        for source in _assets().joinpath("templates").iterdir():
            target = templates / source.name
            if not target.exists():
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        constitution = root / ".roclec/constitution.md"
        if not constitution.exists() and not (root / ".specify/memory/constitution.md").exists():
            constitution.write_text(_assets().joinpath("templates/constitution-template.md").read_text(encoding="utf-8"), encoding="utf-8")
    notices = root / ".roclec/notices"
    notices.mkdir(exist_ok=True)
    for source in _assets().joinpath("notices").iterdir():
        (notices / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    relative = os.path.relpath(project_root, root)
    runner = root / ".roclec/run"
    runner.write_text(
        "#!/bin/sh\n# managed by roclec-spec-kit\nset -eu\n"
        "repo_root=$(CDPATH= cd -- \"$(dirname -- \"$0\")/..\" && pwd)\n"
        f"project_relative={shlex.quote(relative)}\n"
        "project_root=$(CDPATH= cd -- \"$repo_root/$project_relative\" && pwd)\n"
        "if [ -x \"$project_root/.venv/bin/roclec\" ]; then exec \"$project_root/.venv/bin/roclec\" \"$@\"; fi\n"
        "if [ -x \"$repo_root/.venv/bin/roclec\" ]; then exec \"$repo_root/.venv/bin/roclec\" \"$@\"; fi\n"
        "if command -v roclec >/dev/null 2>&1; then exec roclec \"$@\"; fi\n"
        "echo 'Roclec CLI is missing. Install roclec-spec-kit in the project .venv.' >&2\nexit 127\n",
        encoding="utf-8",
    )
    runner.chmod(runner.stat().st_mode | 0o111)


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    config = root / CONFIG_PATH
    if config.exists():
        raise UsageError(f"{config} already exists")
    components: dict[str, tuple[str, bool]] = {}
    for entry in args.component or ["app=."]:
        if "=" not in entry:
            raise UsageError("--component must be NAME=REPO_PATH")
        name, repo = entry.split("=", 1)
        if not NAME_RE.fullmatch(name) or not repo or Path(repo).is_absolute() or name in components:
            raise UsageError(f"invalid or duplicate component {entry!r}")
        components[name] = (repo, name in args.user_facing)
    for name in args.user_facing:
        if name not in components:
            raise UsageError(f"--user-facing references unknown component {name}")
    # Preflight all managed paths before creating any files.
    managed = [config, root / "roadmap/ROADMAP.md", *(root / "roadmap/releases" / name / "INDEX.md" for name in components)]
    if any(path.exists() for path in managed):
        raise UsageError("project already has Roclec-managed files; init will not overwrite them")
    for host in (".agents", ".claude"):
        for skill in _skill_names():
            target = root / host / "skills" / skill / "SKILL.md"
            if target.exists() and "<!-- managed by roclec-spec-kit -->" not in target.read_text(encoding="utf-8"):
                raise UsageError(f"Will not overwrite unmanaged skill: {target}")
    _skill_changes(root)
    _check_agent_files(root)
    if args.user_facing and (root / "skills-lock.json").exists():
        read_lock(root)
    root.mkdir(parents=True, exist_ok=True)
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(render_config(args.name, components), encoding="utf-8")
    (root / "specs").mkdir(exist_ok=True)
    if not (root / "FUTURE.md").exists():
        (root / "FUTURE.md").write_text("# Future ideas\n\n", encoding="utf-8")
    archive = root / "roadmap/fut-archive.md"
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text("# Archived future ideas\n\n| ID | Outcome | Spec |\n| -- | ------- | ---- |\n", encoding="utf-8")
    for name in components:
        (root / "roadmap/releases" / name).mkdir(parents=True, exist_ok=True)
    project = load_project(root)
    write_views(project, scan(project))
    _install_skills(root)
    _install_agent_files(root, root)
    added = ensure_design_lock(root) if args.user_facing else []
    print(f"Initialized {args.name} at {root}")
    if added:
        print(f"Pinned design skills: {', '.join(added)}. Run `roclec skills --restore` to install them.")
    print(f"Edit {config} and run `./.roclec/run check`. Agent workflow: {root / '.roclec/workflow.md'}.")
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    project = _project(args)
    destination = Path(args.into).resolve() if args.into else project.root
    if args.restore:
        read_lock(destination)
    link = destination / LINK_PATH
    link_text = ""
    if destination != project.root:
        if destination not in {settings.repo for settings in project.components.values()}:
            raise UsageError("--into must name a repo configured in project.toml")
        if not destination.is_dir():
            raise UsageError(f"configured repo does not exist: {destination}")
        if (destination / CONFIG_PATH).exists():
            raise UsageError(f"{destination} already has its own Roclec project")
        relative = os.path.relpath(project.root, destination)
        link_text = f"schema = 1\nproject_root = {json.dumps(relative)}\n"
        if link.exists() and link.read_text(encoding="utf-8") != link_text:
            raise UsageError(f"Will not overwrite an existing Roclec link: {link}")
    _check_agent_files(destination)
    _skill_changes(destination)
    if destination == project.root and any(component.user_facing for component in project.components.values()):
        added = ensure_design_lock(destination)
        if added:
            print(f"Pinned design skills: {', '.join(added)}. Run `roclec skills --restore` to install them.")
    for path in _install_skills(destination):
        print(f"installed {path.relative_to(destination)} in {destination}")
    if link_text:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.write_text(link_text, encoding="utf-8")
        print(f"linked {destination} to {project.root}")
    _install_agent_files(destination, project.root)
    if args.restore:
        names = restore_external_skills(destination)
        print(f"restored {len(names)} external skill(s) from {destination / 'skills-lock.json'}")
    return 0


def cmd_speckit_install(args: argparse.Namespace) -> int:
    project = _project(args)
    if not (project.root / ".specify").is_dir():
        raise UsageError("initialize spec-kit here first with `specify init --here`")
    if not shutil.which("specify"):
        raise UsageError("`specify` CLI is not installed")
    install_speckit(project)
    print("installed Roclec spec-kit preset and extension")
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    project = _project(args)
    if not SPEC_DIR_RE.fullmatch(args.name):
        raise UsageError("spec name must be NNN-slug")
    components = args.component or list(project.components)
    for name in components:
        if name not in project.components:
            raise UsageError(f"unknown component {name}")
    state = scan(project)
    spec_id = args.name.split("-", 1)[0]
    if any(spec.id == spec_id or spec.name == args.name for spec in state.specs):
        raise UsageError(f"spec id {spec_id} is already used")
    folder = project.specs / args.name
    if folder.exists():
        raise UsageError(f"{folder} already exists")
    metadata = ", ".join(components)
    body = _template(project, "spec", ID=spec_id, TITLE=args.title,
        TITLE_JSON=json.dumps(args.title), COMPONENTS=metadata, DATE=date.today().isoformat())
    folder.mkdir(parents=True)
    (folder / "spec.md").write_text(body, encoding="utf-8")
    state = scan(project)
    select_spec(project, _spec(state, spec_id))
    write_views(project, state)
    print(f"created {folder.relative_to(project.root)}/spec.md")
    return 0


def cmd_use(args: argparse.Namespace) -> int:
    project = _project(args)
    spec = resolve_spec(project, scan(project), args.spec)
    select_spec(project, spec)
    print(f"selected {spec.target}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    project = _project(args)
    state = scan(project)
    data = inspect_spec(project, state, resolve_spec(project, state, args.spec), component=args.component)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"{data['spec']}: {data['status']}\nNext skill: {data['next_skill'] or 'none'}")
        for error in data["errors"]:
            print(f"ERROR {error}")
    return 0


def cmd_artifact(args: argparse.Namespace) -> int:
    project = _project(args)
    state = scan(project)
    spec = resolve_spec(project, state, args.spec)
    target = spec.path / ("checklists/requirements.md" if args.kind == "checklist" else f"{args.kind}.md")
    if target.exists():
        raise UsageError(f"will not overwrite {target}")
    if args.kind == "plan" and spec.status not in {"clarified", "ready"}:
        raise UsageError("clarify the spec before creating a plan")
    if args.kind == "tasks" and spec.status not in {"ready", "in-progress"}:
        raise UsageError("complete the ready plan before creating tasks")
    if args.kind == "plan" and _check_ready(project, spec):
        raise UsageError("pass the ready gate before creating a plan")
    if args.kind == "tasks" and not (spec.path / "plan.md").is_file():
        raise UsageError("create plan.md before tasks")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_template(project, args.kind, ID=spec.id, TITLE=str(spec.meta.get("title", "")), DATE=date.today().isoformat()), encoding="utf-8")
    select_spec(project, spec)
    print(f"created {target}")
    return 0


def cmd_transition(args: argparse.Namespace) -> int:
    project = _project(args)
    state = scan(project)
    spec = resolve_spec(project, state, args.spec)
    errors = transition_errors(project, state, spec, args.status)
    if errors:
        raise UsageError("; ".join(errors))
    path = spec.path / "spec.md"
    body = path.read_text(encoding="utf-8")
    head, tail = body[4:].split("\n---\n", 1)
    head = re.sub(r"^status:.*$", f"status: {args.status}", head, flags=re.M)
    path.write_text("---\n" + head + "\n---\n" + tail, encoding="utf-8")
    select_spec(project, spec)
    write_views(project, scan(project))
    print(f"{spec.name}: {spec.status} -> {args.status}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    project = _project(args)
    state = scan(project)
    from .product import product_errors
    errors: list[str] = []
    if args.gate or args.release_gate:
        spec = resolve_spec(project, state, args.gate or args.release_gate)
        errors = [f"{spec.name}: {error}" for error in _check_spec(project, spec)]
        if args.gate:
            errors += [f"{spec.name}: {error}" for error in _check_ready(project, spec) if f"{spec.name}: {error}" not in errors]
        else:
            if spec.status not in {"ready", "in-progress"} and not (spec.status == "done" and spec.amendment_id):
                errors.append(f"{spec.name}: status must be ready or in-progress")
            errors += [f"{spec.name}: {error}" for error in implementation_errors(project, state, spec)]
            errors += [error for error in state.errors if error not in errors]
        errors = list(dict.fromkeys(errors))
    else:
        errors = list(state.errors) + product_errors(project)
        if args.coverage:
            errors += check_coverage(project, state)
        if args.immutable_base:
            errors += check_immutable(project, args.immutable_base)
        if not errors and args.write:
            write_views(project, state)
            print("generated roadmap and release indexes")
        elif not args.write:
            errors += stale_views(project, state)
    for error in errors:
        print(f"ERROR {error}")
    print(f"{len(state.specs)} specs checked, {len(errors)} errors")
    return 1 if errors else 0


def _release_path(project: Project, component: str, version: str) -> Path:
    if component not in project.components:
        raise UsageError(f"unknown component {component}")
    if not VERSION_RE.fullmatch(version):
        raise UsageError("version must be vMAJOR.MINOR or vMAJOR.MINOR.PATCH")
    return project.releases / component / f"{version}.md"


def _publish_candidate(project: Project, path: Path, body: str) -> int:
    """Validate the proposed release and views before writing any consumer file."""
    state = scan(project, {path: body})
    if state.errors:
        raise UsageError("; ".join(state.errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    write_views(project, state)
    print(f"updated {path.relative_to(project.root)}")
    return 0


def _release_body(project: Project, args) -> tuple[Path, str]:
    path = _release_path(project, args.component, args.version)
    if path.exists():
        body = path.read_text(encoding="utf-8")
        if _release_field(body, "Status") != "planning":
            raise UsageError("released version files are immutable")
        if args.kind is not None and args.kind != (_release_field(body, "Kind") or "release"):
            raise UsageError("cannot change existing release kind")
        if args.base_tag and args.base_tag != _release_field(body, "Base tag"):
            raise UsageError("cannot change existing Base tag")
        return path, body
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", args.version):
        raise UsageError("new versions must be vX.Y.Z")
    if args.title is not None and (not args.title.strip() or any(c in args.title for c in "\r\n")):
        raise UsageError("release title must be a nonempty single line")
    kind = args.kind or "release"
    if kind == "release" and version_key(args.version)[2] != 0:
        raise UsageError("normal release requires Z = 0")
    if kind in {"hotfix", "bugfix"} and not args.base_tag:
        raise UsageError("hotfix/bugfix requires --base-tag")
    published = [r for r in scan(project).releases if r.component == args.component and r.status == "released"]
    if kind == "release" and published:
        previous = max(version_key(r.version) for r in published)
        current = version_key(args.version)
        if current[:2] <= previous[:2] or (current[0] > previous[0] and current[1] != 0):
            raise UsageError("normal release must increase X or Y and reset subordinate numbers")
    body = (f"# {args.component} {args.version} — {args.title or 'Release ' + args.version}\n\n"
            f"**Status:** planning\n**Kind:** {kind}\n**Started:** {date.today().isoformat()}\n**Released:** —\n"
            + (f"**Base tag:** {args.base_tag}\n" if args.base_tag else "") +
            "\n## Specs\n\n—\n\n## Amendments\n\n—\n\n## Fixes\n\n—\n\n"
            "## Release criteria\n\n- [ ] RC-01 Define publication and compatibility criteria here.\n\n## Release Notes\n\n")
    return path, body


def _append_release(body: str, heading: str, lines: list[str]) -> str:
    old = section(body, heading)
    existing = [line for line in old.splitlines() if line.strip() not in {"", "—", "-"}]
    existing.extend(line for line in lines if line not in existing)
    content = "\n".join(existing) or "—"
    replacement = f"## {heading}\n\n{content}\n\n"
    if re.search(rf"^## {heading}[ \t]*$", body, re.M):
        return re.sub(rf"^## {heading}[ \t]*\n.*?(?=^## |\Z)", lambda _: replacement, body, count=1, flags=re.M | re.S)
    return body.rstrip() + "\n\n" + replacement


def cmd_release_plan(args: argparse.Namespace) -> int:
    project = _project(args)
    path, body = _release_body(project, args)
    state = scan(project)
    scopes = [resolve_spec(project, state, target) for target in args.specs]
    if not scopes:
        raise UsageError("release plan needs at least one spec or amendment; use release fix for corrections")
    if len({s.target for s in scopes}) != len(scopes):
        raise UsageError("a spec or amendment was listed twice")
    for spec in scopes:
        if args.component not in spec.work_components or spec.status == "deferred":
            raise UsageError(f"{spec.target} does not target {args.component} or is deferred")
        current = state.membership.get(spec.target, {}).get(args.component)
        if current and current != args.version:
            raise UsageError(f"{spec.target} is already assigned to {args.component} {current}")
        if spec.amendment_id:
            a = spec.amendments[spec.amendment_id]
            label, heading = f"{spec.id} {a.id} — {a.title}", "Amendments"
        else:
            label, heading = f"{spec.id} — {spec.meta.get('title', spec.name)}", "Specs"
        body = _append_release(body, heading, [f"- [{label}](../../../specs/{spec.name}/spec.md)"])
    return _publish_candidate(project, path, body)


def cmd_release_fix(args: argparse.Namespace) -> int:
    project = _project(args)
    path, body = _release_body(project, args)
    label = "No spec"
    if args.spec != "-":
        spec = resolve_spec(project, scan(project), args.spec)
        if spec.status != "done" or spec.amendment_id or args.component not in spec.components:
            raise UsageError("fix requires a done spec targeting this component")
        label = f"[{spec.id}](../../../specs/{spec.name}/spec.md)"
    if not args.description.strip() or any(c in args.description for c in "\r\n"):
        raise UsageError("fix description must be a nonempty single line")
    reference = args.reference or ""
    if reference and not re.fullmatch(r"[0-9a-f]{7,40}|https://[^\s)]+/pull/\d+", reference):
        raise UsageError("fix reference must be a commit SHA or PR URL")
    suffix = f" (`{reference}`)" if reference and not reference.startswith("https://") else (f" ({reference})" if reference else "")
    body = _append_release(body, "Fixes", [f"- {label} — {args.description}{suffix}"])
    return _publish_candidate(project, path, body)


def cmd_release_close(args: argparse.Namespace) -> int:
    project = _project(args)
    path = _release_path(project, args.component, args.version)
    state = scan(project)
    release = next((r for r in state.releases if r.path == path), None)
    if release is None or release.status != "planning":
        raise UsageError("release does not exist or is already closed")
    if state.errors:
        raise UsageError("; ".join(state.errors))
    by_name = {s.name: s for s in state.specs}
    if any(by_name[name].status != "done" for name in release.specs):
        raise UsageError("specs are not done")
    for target in release.amendments:
        spec = resolve_spec(project, state, target)
        if spec.amendments[spec.amendment_id].open_tasks(args.component):
            raise UsageError("amendment has open component tasks")
    errors = check_coverage(project, state, set(release.specs + release.amendments), args.component)
    if errors:
        raise UsageError("; ".join(errors))
    body = path.read_text(encoding="utf-8")
    errors = release_criteria_errors(body)
    if errors:
        raise UsageError("; ".join(errors))
    if not section(body, "Release Notes").strip():
        raise UsageError("write Release Notes before closing")
    modern = bool(_release_field(body, "Kind"))
    if modern or args.commit:
        repo = project.components[args.component].repo
        if not args.commit or not re.fullmatch(r"[0-9a-f]{7,40}", args.commit):
            raise UsageError("close requires --commit with the published commit SHA")
        commit = git_commit(repo, args.commit)
        tag = args.tag or args.version
        if not commit or tag != args.version:
            raise UsageError("invalid published commit or Tag must match version")
        if release.kind in {"hotfix", "bugfix"}:
            ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", "refs/tags/" + release.base_tag, commit], cwd=repo, capture_output=True)
            if ancestry.returncode:
                raise UsageError("published correction must descend from its Base tag")
        existing = git_commit(repo, "refs/tags/" + tag)
        if existing and existing != commit:
            raise UsageError("tag collision: existing tag points to another commit")
        for other in state.releases:
            if other.path != path and other.status == "released" and project.components[other.component].repo == repo and other.tag == tag and other.commit != commit:
                raise UsageError("tag collision between components sharing a repository")
        body = body.replace("## Specs", f"**Commit:** {commit}\n**Tag:** {tag}\n\n## Specs", 1)
    body = re.sub(r"^\*\*Status:\*\* planning$", "**Status:** released", body, count=1, flags=re.M)
    body = re.sub(r"^\*\*Released:\*\* —$", f"**Released:** {date.today().isoformat()}", body, count=1, flags=re.M)
    return _publish_candidate(project, path, body)


def cmd_product(args: argparse.Namespace) -> int:
    from .product import product_views, product_errors
    project = _project(args)
    views = product_views(project)  # preflight every source/output before any write
    if args.write:
        for path, body in views.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
    errors = product_errors(project)
    for error in errors:
        print(f"ERROR {error}")
    print(f"{len(views)} product views checked, {len(errors)} errors")
    return 1 if errors else 0


def cmd_review(args: argparse.Namespace) -> int:
    from .reviews import policy_path
    project = _project(args)
    spec = resolve_spec(project, scan(project), args.spec)
    path = policy_path(spec)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError as exc:
        raise UsageError("repair invalid review policy before changing it") from exc
    if not isinstance(data, dict) or not args.reason.strip():
        raise UsageError("review policy needs an object and a decision reason")
    key = spec.amendment_id or "original"
    previous = data.get(key, {})
    if not isinstance(previous, dict):
        raise UsageError("invalid review policy entry")
    history = previous.get("history", [])
    if not isinstance(history, list):
        raise UsageError("invalid review policy history")
    entry = {"enabled": args.action == "enable", "reason": args.reason, "date": date.today().isoformat()}
    data[key] = {**entry, "history": [*history, entry]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"review {args.action}: {spec.target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="roclec", description="Configurable spec and release workflow")
    parser.add_argument("--project", help="project root or a path inside it (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="install project-local configuration and skills")
    init.add_argument("path", nargs="?", default=".")
    init.add_argument("--name", required=True)
    init.add_argument("--component", action="append", help="NAME=REPO_PATH; repeat for each deployable unit")
    init.add_argument("--user-facing", action="append", default=[], metavar="NAME")
    init.set_defaults(func=cmd_init)
    skills = sub.add_parser("skills", help="refresh managed agent skills from this package version")
    skills.add_argument("--into", help="install skills into a configured code repo")
    skills.add_argument("--restore", action="store_true", help="also install pinned third-party skills from destination skills-lock.json")
    skills.set_defaults(func=cmd_skills)
    speckit = sub.add_parser("speckit", help="install the bundled spec-kit preset and extension")
    speckit.set_defaults(func=cmd_speckit_install)
    new = sub.add_parser("new", help="create a draft spec")
    new.add_argument("name", help="NNN-slug")
    new.add_argument("--title", required=True)
    new.add_argument("--component", action="append", help="target component; repeat as needed")
    new.set_defaults(func=cmd_new)
    use = sub.add_parser("use", help="select a feature in this worktree and sync optional spec-kit context")
    use.add_argument("spec")
    use.set_defaults(func=cmd_use)
    inspect = sub.add_parser("inspect", help="report persisted spec state, gates and one next skill")
    inspect.add_argument("spec", nargs="?")
    inspect.add_argument("--json", action="store_true")
    inspect.add_argument("--component", help="explicit component when repository ownership is ambiguous")
    inspect.set_defaults(func=cmd_inspect)
    artifact = sub.add_parser("artifact", help="create an artifact from the project's shared templates")
    artifact.add_argument("spec")
    artifact.add_argument("kind", choices=("plan", "tasks", "checklist"))
    artifact.set_defaults(func=cmd_artifact)
    transition = sub.add_parser("transition", help="change status after deterministic prerequisites pass")
    transition.add_argument("spec")
    transition.add_argument("status", choices=STATUSES)
    transition.set_defaults(func=cmd_transition)
    check = sub.add_parser("check", help="validate specs, releases and generated views")
    check.add_argument("--write", action="store_true", help="regenerate roadmap and release indexes")
    check.add_argument("--gate", metavar="SPEC", help="check readiness before planning")
    check.add_argument("--release-gate", metavar="SPEC", help="check release assignment before implementation")
    check.add_argument("--coverage", action="store_true", help="check done AC references in component tests")
    check.add_argument("--immutable-base", metavar="REF", help="compare released files to Git base")
    check.set_defaults(func=cmd_check)
    product = sub.add_parser("product", help="check optional generated component product views")
    product.add_argument("--write", action="store_true")
    product.set_defaults(func=cmd_product)
    review = sub.add_parser("review", help="record explicit independent review participation")
    review.add_argument("action", choices=("enable", "disable"))
    review.add_argument("spec")
    review.add_argument("--reason", required=True)
    review.set_defaults(func=cmd_review)
    release = sub.add_parser("release", help="manage component releases")
    release_sub = release.add_subparsers(dest="release_command", required=True)
    plan = release_sub.add_parser("plan", help="assign specs to a planned release")
    plan.add_argument("component")
    plan.add_argument("version")
    plan.add_argument("specs", nargs="+")
    plan.add_argument("--kind", choices=("release", "hotfix", "bugfix"))
    plan.add_argument("--base-tag")
    plan.add_argument("--title")
    plan.set_defaults(func=cmd_release_plan)
    fix = release_sub.add_parser("fix", help="record a correction in a planned release")
    fix.add_argument("component")
    fix.add_argument("version")
    fix.add_argument("spec")
    fix.add_argument("description")
    fix.add_argument("reference", nargs="?")
    fix.add_argument("--kind", choices=("release", "hotfix", "bugfix"))
    fix.add_argument("--base-tag")
    fix.add_argument("--title")
    fix.set_defaults(func=cmd_release_fix)
    close = release_sub.add_parser("close", help="close a release after publication")
    close.add_argument("component")
    close.add_argument("version")
    close.add_argument("--commit")
    close.add_argument("--tag")
    close.set_defaults(func=cmd_release_close)
    return parser


def legacy_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, SkillLockError, LifecycleError, AdapterError, UsageError, OSError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    """Public CLI: schema 3 only. The previous implementation is a regression oracle."""
    from .native_cli import main as native_main
    return native_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
