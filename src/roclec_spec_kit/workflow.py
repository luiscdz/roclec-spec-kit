"""Deterministic spec, release and generated-view checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
import subprocess

from .config import Project

STATUSES = ("draft", "clarified", "ready", "in-progress", "done", "deferred")
ACTIVE = {"ready", "in-progress", "done"}
VERSION_RE = re.compile(r"v\d+\.\d+(?:\.\d+)?$")
SPEC_DIR_RE = re.compile(r"(\d{3,})-[a-z0-9]+(?:-[a-z0-9]+)*$")
AC_RE = re.compile(r"\*\*(AC-\d{2,})\*\*")
TASK_RE = re.compile(r"^- \[([ xX])\] (T\d+)\b(.*)$", re.M)
FUT_RE = re.compile(r"FUT-\d{3,}$")
TEST_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".kt", ".go", ".rs"}
SKIP_DIRS = {".git", ".venv", "node_modules", "build", "dist", ".gradle", ".next", "target"}


@dataclass(frozen=True)
class Spec:
    path: Path
    meta: dict[str, object]
    body: str

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def id(self) -> str:
        return str(self.meta.get("id", ""))

    @property
    def components(self) -> list[str]:
        value = self.meta.get("components", [])
        return value if isinstance(value, list) else []

    @property
    def status(self) -> str:
        return str(self.meta.get("status", ""))


@dataclass(frozen=True)
class Release:
    path: Path
    component: str
    version: str
    title: str
    status: str
    started: str
    released: str
    specs: list[str]


@dataclass
class State:
    specs: list[Spec]
    releases: list[Release]
    membership: dict[str, dict[str, str]]
    errors: list[str]


def parse_front_matter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    meta: dict[str, object] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip() if value.startswith(('"', "'")) else value.split(" #", 1)[0].strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [part.strip().strip("\"'") for part in value[1:-1].split(",") if part.strip()]
        elif value.startswith('"'):
            try:
                meta[key.strip()] = json.loads(value)
            except json.JSONDecodeError:
                meta[key.strip()] = value.strip('"')
        else:
            meta[key.strip()] = value.strip("'")
    return meta, text[end + 5 :]


def load_specs(project: Project) -> list[Spec]:
    if not project.specs.exists():
        return []
    result = []
    for folder in sorted(path for path in project.specs.iterdir() if path.is_dir()):
        source = folder / "spec.md"
        if source.exists():
            meta, body = parse_front_matter(source.read_text(encoding="utf-8"))
        else:
            meta, body = {}, ""
        result.append(Spec(folder, meta, body))
    return result


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _check_ready(project: Project, spec: Spec) -> list[str]:
    errors = []
    if "[NEEDS CLARIFICATION" in spec.body:
        errors.append("unresolved clarification marker")
    acs = AC_RE.findall(spec.body)
    if not acs:
        errors.append("no AC-NN acceptance criteria")
    if len(acs) != len(set(acs)):
        errors.append("duplicate acceptance criterion id")
    if any(project.components[name].user_facing for name in spec.components if name in project.components):
        if not (spec.path / "ux.md").is_file():
            errors.append("user-facing spec needs ux.md")
        if not list((spec.path / "prototype").glob("*.html")):
            errors.append("user-facing spec needs prototype/*.html")
    return errors


def _check_spec(project: Project, spec: Spec) -> list[str]:
    errors = []
    if not (spec.path / "spec.md").is_file():
        return ["missing spec.md"]
    if not SPEC_DIR_RE.fullmatch(spec.name):
        errors.append("directory must be NNN-slug")
    for field in ("id", "title", "status", "components", "effort", "origin", "created"):
        if not spec.meta.get(field):
            errors.append(f"missing front matter {field}")
    if spec.id != spec.name.split("-", 1)[0]:
        errors.append("id does not match directory")
    if spec.status not in STATUSES:
        errors.append(f"unknown status {spec.status!r}")
    if not spec.components:
        errors.append("components must be a nonempty list")
    if len(spec.components) != len(set(spec.components)):
        errors.append("duplicate component")
    for name in spec.components:
        if name not in project.components:
            errors.append(f"unknown component {name}")
    if "version" in spec.meta or "versions" in spec.meta:
        errors.append("release membership belongs in version files")
    origin = str(spec.meta.get("origin", ""))
    if origin and origin != "direct" and not FUT_RE.fullmatch(origin):
        errors.append("origin must be direct or FUT-NNN")
    created = spec.meta.get("created")
    if created and not _valid_date(str(created)):
        errors.append("created must be YYYY-MM-DD")
    if spec.status in ACTIVE:
        errors.extend(_check_ready(project, spec))
    if spec.status in {"in-progress", "done"}:
        for filename in ("plan.md", "tasks.md"):
            if not (spec.path / filename).is_file():
                errors.append(f"{spec.status} needs {filename}")
    tasks = spec.path / "tasks.md"
    if tasks.is_file():
        found = TASK_RE.findall(tasks.read_text(encoding="utf-8"))
        tags = {f"[{name}]" for name in (*spec.components, "specs")}
        for marker, task_id, rest in found:
            if not any(tag in rest for tag in tags):
                errors.append(f"{task_id} has no configured component tag")
            if spec.status == "done" and marker == " ":
                errors.append(f"{task_id} is open in a done spec")
    return errors


def _check_future(project: Project, specs: list[Spec]) -> list[str]:
    future = project.root / "FUTURE.md"
    archive = project.root / "roadmap/fut-archive.md"
    live = re.findall(r"^## (FUT-\d{3,})\b", future.read_text(encoding="utf-8"), re.M) if future.exists() else []
    retired = re.findall(r"^\|\s*(FUT-\d{3,})\s*\|", archive.read_text(encoding="utf-8"), re.M) if archive.exists() else []
    errors = []
    for identifier in set(live):
        if live.count(identifier) > 1:
            errors.append(f"{identifier} appears twice in FUTURE.md")
        if identifier in retired:
            errors.append(f"{identifier} is live and archived")
    for identifier in set(retired):
        if retired.count(identifier) > 1:
            errors.append(f"{identifier} appears twice in fut-archive.md")
    for spec in specs:
        if spec.meta.get("origin") in live:
            errors.append(f"{spec.name}: origin {spec.meta['origin']} is still live in FUTURE.md")
    return errors


def _release_field(body: str, name: str) -> str:
    match = re.search(rf"^\*\*{re.escape(name)}:\*\*\s*(.*)$", body, re.M)
    return match.group(1).strip() if match else ""


def _load_releases(project: Project, specs: list[Spec]) -> tuple[list[Release], dict[str, dict[str, str]], list[str]]:
    errors: list[str] = []
    by_name = {spec.name: spec for spec in specs}
    membership: dict[str, dict[str, str]] = {spec.name: {} for spec in specs}
    releases: list[Release] = []
    for component in project.components:
        folder = project.releases / component
        if not folder.is_dir():
            errors.append(f"roadmap/releases/{component} is missing")
            continue
        for path in sorted(folder.glob("v*.md")):
            relative = path.relative_to(project.root)
            if not VERSION_RE.fullmatch(path.stem):
                errors.append(f"{relative}: invalid version name")
                continue
            body = path.read_text(encoding="utf-8")
            heading = re.search(r"^# ([a-z][a-z0-9-]*) (v\d+\.\d+(?:\.\d+)?) — (.+)$", body, re.M)
            if not heading or heading.group(1) != component or heading.group(2) != path.stem:
                errors.append(f"{relative}: heading must be '# {component} {path.stem} — title'")
                continue
            status = _release_field(body, "Status")
            started = _release_field(body, "Started")
            released = _release_field(body, "Released")
            if status not in {"planning", "released"}:
                errors.append(f"{relative}: Status must be planning or released")
            if not _valid_date(started):
                errors.append(f"{relative}: Started must be YYYY-MM-DD")
            if status == "released" and not _valid_date(released):
                errors.append(f"{relative}: Released must be YYYY-MM-DD")
            if status == "planning" and released not in {"—", "-"}:
                errors.append(f"{relative}: planning release cannot have a Released date")
            section = re.search(r"^## Specs\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
            names = re.findall(r"^- \[[^]]+\]\(\.\./\.\./\.\./specs/([^/]+)/spec\.md\)$", section.group(1), re.M) if section else []
            listed = [line for line in section.group(1).splitlines() if line.startswith("- ")] if section else []
            if not names or len(names) != len(listed):
                errors.append(f"{relative}: Specs needs valid links")
            if len(names) != len(set(names)):
                errors.append(f"{relative}: duplicate spec link")
            release = Release(path, component, path.stem, heading.group(3), status, started, released, names)
            releases.append(release)
            for name in names:
                spec = by_name.get(name)
                if spec is None:
                    errors.append(f"{relative}: unknown spec {name}")
                    continue
                if component not in spec.components:
                    errors.append(f"{relative}: {name} does not target {component}")
                if spec.status == "deferred":
                    errors.append(f"{relative}: deferred spec {name}")
                if status == "released" and spec.status != "done":
                    errors.append(f"{relative}: released spec {name} is not done")
                previous = membership[name].get(component)
                if previous:
                    errors.append(f"{name}: assigned to {component} {previous} and {path.stem}")
                else:
                    membership[name][component] = path.stem
    for spec in specs:
        if spec.status in {"in-progress", "done"}:
            for component in spec.components:
                if component in project.components and component not in membership[spec.name]:
                    errors.append(f"{spec.name}: missing {component} release assignment")
    return releases, membership, errors


def scan(project: Project) -> State:
    specs = load_specs(project)
    errors = [f"{spec.name}: {error}" for spec in specs for error in _check_spec(project, spec)]
    ids: dict[str, str] = {}
    for spec in specs:
        if spec.id in ids:
            errors.append(f"{spec.name}: id {spec.id} also used by {ids[spec.id]}")
        ids[spec.id] = spec.name
    releases, membership, release_errors = _load_releases(project, specs)
    errors.extend(release_errors)
    errors.extend(_check_future(project, specs))
    return State(specs, releases, membership, errors)


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version[1:].split("."))


def render_index(component: str, releases: list[Release]) -> str:
    rows = sorted((r for r in releases if r.component == component), key=lambda r: version_key(r.version))
    released = [r.version for r in rows if r.status == "released"]
    lines = [f"# {component} releases", "", "> Generated by `roclec check --write`. Edit version files instead.", "", "## Current release", "", released[-1] if released else "—", "", "| Version | Title | Status | Released |", "| ------- | ----- | ------ | -------- |"]
    lines += [f"| [{r.version}]({r.version}.md) | {r.title} | {r.status} | {r.released} |" for r in rows]
    return "\n".join(lines) + "\n"


def render_roadmap(state: State) -> str:
    lines = ["# Roadmap", "", "> Generated by `roclec check --write`. Edit specs and version files instead.", ""]
    groups = [("In progress", {"in-progress"}), ("Ready", {"ready"}), ("Specifying", {"draft", "clarified"}), ("Deferred", {"deferred"}), ("Done", {"done"})]
    for heading, statuses in groups:
        lines += [f"## {heading}", ""]
        rows = [spec for spec in state.specs if spec.status in statuses]
        if not rows:
            lines += ["—", ""]
            continue
        lines += ["| Spec | Components | Releases |", "| ---- | ---------- | -------- |"]
        for spec in rows:
            releases = ", ".join(f"[{component} {version}](releases/{component}/{version}.md)" for component, version in sorted(state.membership[spec.name].items())) or "—"
            lines.append(f"| [{spec.id} — {spec.meta.get('title', '')}](../specs/{spec.name}/spec.md) | {', '.join(spec.components)} | {releases} |")
        lines.append("")
    return "\n".join(lines)


def generated_views(project: Project, state: State) -> dict[Path, str]:
    views = {project.root / "roadmap/ROADMAP.md": render_roadmap(state)}
    for component in project.components:
        views[project.releases / component / "INDEX.md"] = render_index(component, state.releases)
    return views


def stale_views(project: Project, state: State) -> list[str]:
    return [f"{path.relative_to(project.root)} is missing or stale (run roclec check --write)" for path, expected in generated_views(project, state).items() if not path.is_file() or path.read_text(encoding="utf-8") != expected]


def write_views(project: Project, state: State) -> None:
    for path, contents in generated_views(project, state).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")


def check_coverage(project: Project, state: State) -> list[str]:
    corpus: dict[str, str] = {}
    for component, settings in project.components.items():
        if not settings.repo.is_dir():
            continue
        chunks = []
        for path in settings.repo.rglob("*"):
            relative = path.relative_to(settings.repo)
            if SKIP_DIRS.intersection(relative.parts) or not path.is_file() or path.suffix not in TEST_EXTENSIONS:
                continue
            is_test = bool({"test", "tests", "__tests__"}.intersection(relative.parts)) or bool(re.search(r"(?:^test_|_test\.|\.test\.|\.spec\.|Tests?\.)", path.name))
            if is_test:
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
        corpus[component] = "\n".join(chunks)
    errors = []
    for spec in state.specs:
        if spec.status != "done":
            continue
        for component in spec.components:
            if component not in corpus:
                errors.append(f"{spec.name}: no configured repo for coverage in {component}")
                continue
            for ac in sorted(set(AC_RE.findall(spec.body))):
                if f"[{spec.id}/{ac}]" not in corpus[component]:
                    errors.append(f"{spec.name}: {component} test does not cite [{spec.id}/{ac}]")
    return errors


def check_immutable(project: Project, base_ref: str) -> list[str]:
    """Compare already released files against a Git base revision."""
    if re.fullmatch(r"0{40}", base_ref):
        return []
    listing = subprocess.run(["git", "ls-tree", "-r", "--name-only", base_ref, "--", "roadmap/releases"], cwd=project.root, capture_output=True, text=True)
    if listing.returncode:
        return [f"cannot inspect Git base {base_ref}: {listing.stderr.strip()}"]
    errors = []
    for relative in listing.stdout.splitlines():
        path = Path(relative)
        if len(path.parts) != 4 or path.parts[:2] != ("roadmap", "releases") or path.parts[2] not in project.components or not VERSION_RE.fullmatch(path.stem):
            continue
        previous = subprocess.run(["git", "show", f"{base_ref}:{relative}"], cwd=project.root, capture_output=True)
        if previous.returncode:
            errors.append(f"cannot read {relative} from {base_ref}")
            continue
        if _release_field(previous.stdout.decode("utf-8"), "Status") != "released":
            continue
        current = project.root / path
        if not current.is_file() or current.read_bytes() != previous.stdout:
            errors.append(f"{relative}: released file changed after publication")
    return errors
