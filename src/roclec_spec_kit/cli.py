"""Command line interface for project-local Roclec workflows."""

from __future__ import annotations

import argparse
from datetime import date
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from .config import CONFIG_PATH, LINK_PATH, ConfigError, NAME_RE, Project, load_project, render_config
from .external_skills import SkillLockError, ensure_design_lock, read_lock, restore_external_skills
from .workflow import (SPEC_DIR_RE, VERSION_RE, Spec, _check_ready, _check_spec,
                       check_coverage, check_immutable, scan, stale_views, write_views)


class UsageError(ValueError):
    pass


def _project(args: argparse.Namespace) -> Project:
    return load_project(Path(args.project or "."))


def _spec(state, target: str) -> Spec:
    matches = [s for s in state.specs if s.name == target or s.id == target]
    if len(matches) != 1:
        raise UsageError(f"spec {target!r} is missing or ambiguous")
    return matches[0]


def _install_skills(root: Path) -> list[Path]:
    changes: list[tuple[Path, str]] = []
    assets = files("roclec_spec_kit").joinpath("assets/skills")
    for skill in ("roclec-coordinator", "roclec-implement"):
        source = assets.joinpath(skill, "SKILL.md").read_text(encoding="utf-8")
        for host in (".agents", ".claude"):
            target = root / host / "skills" / skill / "SKILL.md"
            if target.exists() and "<!-- managed by roclec-spec-kit -->" not in target.read_text(encoding="utf-8"):
                raise UsageError(f"Will not overwrite unmanaged skill: {target}")
            changes.append((target, source))
    for target, source in changes:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    return [target for target, _ in changes]


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
        for skill in ("roclec-coordinator", "roclec-implement"):
            target = root / host / "skills" / skill / "SKILL.md"
            if target.exists() and "<!-- managed by roclec-spec-kit -->" not in target.read_text(encoding="utf-8"):
                raise UsageError(f"Will not overwrite unmanaged skill: {target}")
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
    added = ensure_design_lock(root) if args.user_facing else []
    print(f"Initialized {args.name} at {root}")
    if added:
        print(f"Pinned design skills: {', '.join(added)}. Run `roclec skills --restore` to install them.")
    print(f"Edit {config} and run `roclec check`.")
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
    for path in _install_skills(destination):
        print(f"installed {path.relative_to(destination)} in {destination}")
    if link_text:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.write_text(link_text, encoding="utf-8")
        print(f"linked {destination} to {project.root}")
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
    assets = files("roclec_spec_kit").joinpath("assets/speckit")
    preset = assets.joinpath("presets/roclec")
    extension = assets.joinpath("extensions/roclec")
    commands = []
    if (project.root / ".specify/presets/roclec").exists():
        commands.append(["specify", "preset", "remove", "roclec"])
    commands.extend([
        ["specify", "preset", "add", "--dev", str(preset)],
        ["specify", "extension", "add", "--dev", str(extension), "--force"],
    ])
    for command in commands:
        result = subprocess.run(command, cwd=project.root)
        if result.returncode:
            raise UsageError(f"spec-kit installation failed: {' '.join(command)}")
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
    folder.mkdir(parents=True)
    metadata = ", ".join(components)
    (folder / "spec.md").write_text(
        f"---\nid: {spec_id}\ntitle: {json.dumps(args.title)}\nstatus: draft\ncomponents: [{metadata}]\neffort: TBD\norigin: direct\ncreated: {date.today().isoformat()}\n---\n\n"
        "# Feature\n\n## Context\n\n## Requirements\n\n## Acceptance Criteria\n\n"
        "[NEEDS CLARIFICATION: define testable AC-NN scenarios before marking ready.]\n\n"
        "## Decisions\n\n| Decision | Rejected alternative | Reason |\n| -------- | -------------------- | ------ |\n",
        encoding="utf-8",
    )
    write_views(project, scan(project))
    print(f"created {folder.relative_to(project.root)}/spec.md")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    project = _project(args)
    state = scan(project)
    errors: list[str] = []
    if args.gate or args.release_gate:
        spec = _spec(state, args.gate or args.release_gate)
        errors = [f"{spec.name}: {error}" for error in _check_spec(project, spec)]
        if args.gate:
            errors += [f"{spec.name}: {error}" for error in _check_ready(project, spec) if f"{spec.name}: {error}" not in errors]
            if str(spec.meta.get("effort", "")) in {"", "TBD"}:
                errors.append(f"{spec.name}: effort must be estimated")
        else:
            if spec.status not in {"ready", "in-progress"}:
                errors.append(f"{spec.name}: status must be ready or in-progress")
            for component in spec.components:
                if component not in state.membership.get(spec.name, {}):
                    errors.append(f"{spec.name}: missing {component} release assignment")
            errors += [error for error in state.errors if error not in errors]
    else:
        errors = list(state.errors)
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


def cmd_release_plan(args: argparse.Namespace) -> int:
    project = _project(args)
    path = _release_path(project, args.component, args.version)
    state = scan(project)
    specs = [_spec(state, target) for target in args.specs]
    if len({spec.name for spec in specs}) != len(specs):
        raise UsageError("a spec was listed twice")
    for spec in specs:
        if args.component not in spec.components:
            raise UsageError(f"{spec.name} does not target {args.component}")
        if spec.status == "deferred":
            raise UsageError(f"{spec.name} is deferred")
        current = state.membership.get(spec.name, {}).get(args.component)
        if current and current != args.version:
            raise UsageError(f"{spec.name} is already assigned to {args.component} {current}")
    links = [f"- [{spec.id} — {spec.meta.get('title', spec.name)}](../../../specs/{spec.name}/spec.md)" for spec in specs]
    if path.exists():
        body = path.read_text(encoding="utf-8")
        if re.search(r"^\*\*Status:\*\*\s*released\s*$", body, re.M):
            raise UsageError("released version files are immutable")
        marker = "## Specs\n"
        if marker not in body:
            raise UsageError(f"{path} has no ## Specs section")
        additions = [link for spec, link in zip(specs, links) if state.membership.get(spec.name, {}).get(args.component) != args.version]
        if not additions:
            print("all specs were already assigned")
            return 0
        body = body.replace(marker, marker + "\n" + "\n".join(additions) + "\n", 1)
    else:
        title = args.title or f"Release {args.version}"
        body = (f"# {args.component} {args.version} — {title}\n\n"
                f"**Status:** planning\n**Started:** {date.today().isoformat()}\n**Released:** —\n\n"
                "## Specs\n\n" + "\n".join(links) + "\n\n"
                "## Release criteria\n\n- Define publication and compatibility criteria here.\n\n"
                "## Release Notes\n\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    updated = scan(project)
    if not updated.errors:
        write_views(project, updated)
    print(f"planned {path.relative_to(project.root)}")
    for error in updated.errors:
        print(f"ERROR {error}")
    return 1 if updated.errors else 0


def cmd_release_close(args: argparse.Namespace) -> int:
    project = _project(args)
    path = _release_path(project, args.component, args.version)
    state = scan(project)
    release = next((r for r in state.releases if r.path == path), None)
    if release is None:
        raise UsageError(f"release {args.component} {args.version} does not exist or is invalid")
    if release.status != "planning":
        raise UsageError("release is already closed")
    if state.errors:
        raise UsageError("fix `roclec check` errors before closing a release")
    by_name = {spec.name: spec for spec in state.specs}
    unfinished = [name for name in release.specs if by_name[name].status != "done"]
    if unfinished:
        raise UsageError(f"specs are not done: {', '.join(unfinished)}")
    body = path.read_text(encoding="utf-8")
    notes = re.search(r"^## Release Notes\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    if not notes or not notes.group(1).strip():
        raise UsageError("write Release Notes before closing")
    body = re.sub(r"^\*\*Status:\*\* planning$", "**Status:** released", body, count=1, flags=re.M)
    body = re.sub(r"^\*\*Released:\*\* —$", f"**Released:** {date.today().isoformat()}", body, count=1, flags=re.M)
    path.write_text(body, encoding="utf-8")
    write_views(project, scan(project))
    print(f"closed {path.relative_to(project.root)}")
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
    check = sub.add_parser("check", help="validate specs, releases and generated views")
    check.add_argument("--write", action="store_true", help="regenerate roadmap and release indexes")
    check.add_argument("--gate", metavar="SPEC", help="check readiness before planning")
    check.add_argument("--release-gate", metavar="SPEC", help="check release assignment before implementation")
    check.add_argument("--coverage", action="store_true", help="check done AC references in component tests")
    check.add_argument("--immutable-base", metavar="REF", help="compare released files to Git base")
    check.set_defaults(func=cmd_check)
    release = sub.add_parser("release", help="manage component releases")
    release_sub = release.add_subparsers(dest="release_command", required=True)
    plan = release_sub.add_parser("plan", help="assign specs to a planned release")
    plan.add_argument("component")
    plan.add_argument("version")
    plan.add_argument("specs", nargs="+")
    plan.add_argument("--title")
    plan.set_defaults(func=cmd_release_plan)
    close = release_sub.add_parser("close", help="close a release after publication")
    close.add_argument("component")
    close.add_argument("version")
    close.set_defaults(func=cmd_release_close)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, SkillLockError, UsageError, OSError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
