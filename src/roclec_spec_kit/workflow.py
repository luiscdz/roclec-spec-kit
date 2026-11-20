"""Deterministic spec, release and generated-view checks."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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


def visible_markdown(body: str) -> str:
    """Template examples in HTML comments are not actual requirements or tasks."""
    return re.sub(r"<!--.*?-->", "", body, flags=re.S)


@dataclass(frozen=True)
class Spec:
    path: Path
    meta: dict[str, object]
    body: str
    parse_errors: tuple[str, ...] = ()
    amendment_id: str | None = None

    @property
    def target(self) -> str:
        return self.name + ("-" + self.amendment_id if self.amendment_id else "")

    @property
    def work_components(self) -> list[str]:
        return self.amendments[self.amendment_id].components if self.amendment_id else self.components

    @property
    def amendments(self) -> dict[str, Amendment]:
        return parse_amendments(self)[0]

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
class Amendment:
    id: str
    title: str
    date: str
    components: list[str]
    acs: list[str]
    tasks: list[tuple[str, str, str]]

    def open_tasks(self, component: str | None = None) -> list[str]:
        return [identifier for mark, identifier, rest in self.tasks
                if mark == " " and (component is None or f"[{component}]" in rest or "[specs]" in rest)]


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
    amendments: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    kind: str = "release"
    base_tag: str = ""
    commit: str = ""
    tag: str = ""
    modern: bool = False


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
        raise ValueError("unclosed spec front matter")
    meta: dict[str, object] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key in meta:
            raise ValueError(f"duplicate front matter key {key}")
        value = value if value.startswith(('"', "'")) else value.split(" #", 1)[0].strip()
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
            try:
                meta, body = parse_front_matter(source.read_text(encoding="utf-8"))
                parse_errors = ()
            except ValueError as exc:
                meta, body, parse_errors = {}, "", (str(exc),)
        else:
            meta, body, parse_errors = {}, "", ()
        result.append(Spec(folder, meta, visible_markdown(body), parse_errors))
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
    effort = str(spec.meta.get("effort", "")).strip()
    if not effort or effort.upper() in {"TBD", "TODO"} or effort.startswith("["):
        errors.append("effort must be estimated")
    if any(project.components[name].user_facing for name in spec.components if name in project.components):
        if not (spec.path / "ux.md").is_file() or not (spec.path / "ux.md").read_text(encoding="utf-8").strip():
            errors.append("user-facing spec needs ux.md")
        references = spec.path / "prototype/references.md"
        targets = []
        if references.is_file():
            links = re.findall(r"\[[^]]*\]\(([^)]+\.html)\)", visible_markdown(references.read_text(encoding="utf-8")))
            if not links:
                errors.append("prototype references need HTML links")
            for link in links:
                target = (references.parent / link).resolve()
                if (not target.is_relative_to(project.specs.resolve()) or target.parent.name != "prototype"
                        or target.parent.parent == spec.path.resolve() or not target.is_file() or not target.stat().st_size):
                    errors.append(f"invalid reused prototype: {link}")
                    continue
                approval = target.parent / "review.md"
                if not approval.is_file() or not re.search(r"^\*\*Status:\*\* approved\s*$", visible_markdown(approval.read_text(encoding="utf-8")), re.M):
                    errors.append(f"reused prototype lacks original approval: {link}")
                targets.append(target)
        if not targets and not any(path.stat().st_size for path in (spec.path / "prototype").glob("*.html")):
            errors.append("user-facing spec needs prototype/*.html or approved references")
        review = spec.path / "prototype/review.md"
        if not review.is_file() or not re.search(r"^\*\*Status:\*\* approved\s*$", visible_markdown(review.read_text(encoding="utf-8")), re.M):
            errors.append("prototype needs user approval recorded in prototype/review.md")
    return errors


def section(body: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}[ \t]*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return match.group(1) if match else ""


def tasks_for(spec: Spec) -> list[tuple[str, str, str]]:
    path = spec.path / "tasks.md"
    rows = TASK_RE.findall(visible_markdown(path.read_text(encoding="utf-8"))) if path.is_file() else []
    if spec.amendment_id:
        rows = [t for t in rows if f"[{spec.amendment_id}]" in t[2]]
    return rows


def parse_amendments(spec: Spec) -> tuple[dict[str, Amendment], list[str]]:
    body = section(spec.body, "Amendments")
    headings = list(re.finditer(r"^### (A[1-9]\d*) — (.+) \((\d{4}-\d{2}-\d{2})\)$", body, re.M))
    errors = []
    if len(headings) != len(re.findall(r"^### ", body, re.M)):
        errors.append("invalid amendment heading; use ### A1 — title (YYYY-MM-DD)")
    result = {}
    claimed = set()
    rows = tasks_for(replace(spec, amendment_id=None))
    for i, heading in enumerate(headings):
        aid, title, when = heading.groups()
        block = body[heading.end():headings[i+1].start() if i+1 < len(headings) else len(body)]
        def value(label):
            match = re.search(rf"^- \*\*{label}:\*\*[ \t]*(.+)$", block, re.M)
            return match.group(1) if match else ""
        components = [x.strip() for x in value("Components").split(",") if x.strip()]
        acs = re.findall(r"AC-\d{2,}", value("AC"))
        tasks = [t for t in rows if f"[{aid}]" in t[2]]
        if aid in result:
            errors.append(f"duplicate amendment {aid}")
        if not _valid_date(when):
            errors.append(f"{aid}: invalid date")
        if not components or len(components) != len(set(components)) or set(components) - set(spec.components):
            errors.append(f"{aid}: components must be a unique nonempty subset of the spec")
        if not acs or len(acs) != len(set(acs)) or set(acs) - set(AC_RE.findall(spec.body)) or claimed.intersection(acs):
            errors.append(f"{aid}: needs unique exclusive new AC references")
        claimed.update(acs)
        for component in components:
            owned = [t for t in tasks if f"[{component}]" in t[2]]
            if not owned:
                errors.append(f"{aid}: missing [{component}] tasks")
            cited = {ac for _, _, rest in owned for sid, ac in re.findall(r"\[(\d{3,})/(AC-\d{2,})\]", rest) if sid == spec.id}
            if set(acs) - cited:
                errors.append(f"{aid}: [{component}] tasks do not cover amendment ACs")
        for _, identifier, rest in tasks:
            owners = re.findall(r"\[([a-z][a-z0-9-]*)\]", rest)
            if any(owner not in [*components, "specs"] for owner in owners):
                errors.append(f"{aid}: {identifier} targets a component outside amendment")
        result[aid] = Amendment(aid, title, when, components, acs, tasks)
    for _, identifier, rest in rows:
        tags = re.findall(r"\[(A\d+)\]", rest)
        if len(tags) > 1 or any(tag not in result for tag in tags):
            errors.append(f"{identifier}: unknown or multiple amendment tags")
    if result and spec.status != "done":
        errors.append("amendments belong only to done specs")
    return result, errors


def task_errors(project: Project, spec: Spec, required: bool = False) -> list[str]:
    path = spec.path / "tasks.md"
    if not path.is_file():
        return ["implementation needs tasks.md"] if required else []
    body = visible_markdown(path.read_text(encoding="utf-8"))
    found = TASK_RE.findall(body)
    errors = []
    if not found:
        return ["tasks.md needs at least one task"]
    ids = [identifier for _, identifier, _ in found]
    if len(ids) != len(set(ids)):
        errors.append("duplicate task id")
    for line in body.splitlines():
        if re.match(r"^\s*[-*+] \[[ xX]\]", line) and not TASK_RE.fullmatch(line):
            errors.append("malformed task checkbox (expected TNNN)")
    covered = set()
    acs = set(AC_RE.findall(spec.body))
    for marker, identifier, rest in found:
        owners = re.findall(r"\[([a-z][a-z0-9-]*)\]", rest)
        if len(owners) != 1 or owners[0] not in {*spec.components, "specs"}:
            errors.append(f"{identifier} needs exactly one configured component tag or [specs]")
        citations = re.findall(r"\[(\d{3,})/(AC-\d{2,})\]", rest)
        for spec_id, ac in citations:
            if spec_id != spec.id or ac not in acs:
                errors.append(f"{identifier} cites unknown [{spec_id}/{ac}]")
            else:
                covered.add(ac)
        if spec.status == "done" and marker == " " and not re.search(r"\[A\d+\]", rest):
            errors.append(f"{identifier} is open in a done spec")
    if required:
        errors += [f"tasks do not cover [{spec.id}/{ac}]" for ac in sorted(acs - covered)]
    return errors


def _check_spec(project: Project, spec: Spec) -> list[str]:
    errors = list(spec.parse_errors)
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
    if spec.status == "clarified":
        if "[NEEDS CLARIFICATION" in spec.body:
            errors.append("clarified spec has unresolved clarification marker")
        if not AC_RE.findall(spec.body):
            errors.append("clarified spec needs AC-NN acceptance criteria")
    if spec.status in {"ready", "in-progress", "done"}:
        for filename in (("plan.md",) if spec.status == "ready" else ("plan.md", "tasks.md")):
            if not (spec.path / filename).is_file() or not (spec.path / filename).read_text(encoding="utf-8").strip():
                errors.append(f"{spec.status} needs {filename}")
    errors.extend(parse_amendments(spec)[1])
    errors.extend(task_errors(project, spec, required=spec.status in {"in-progress", "done"}))
    return errors


def release_criteria_errors(body: str) -> list[str]:
    body = visible_markdown(body)
    section = re.search(r"^## Release criteria\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    rows = re.findall(r"^- \[([ xX])\] (RC-\d{2,}) (.+)$", section.group(1), re.M) if section else []
    if not rows:
        return ["complete real RC-NN release criteria before closing"]
    errors = []
    if len(rows) != len(set(identifier for _, identifier, _ in rows)):
        errors.append("duplicate release criterion id")
    for line in section.group(1).splitlines():
        if line.startswith("- ") and not re.fullmatch(r"- \[[xX]\] RC-\d{2,} .+", line):
            errors.append("release criteria must have RC-NN IDs and all be checked")
    if any("Define publication" in text for _, _, text in rows):
        errors.append("replace placeholder release criteria before closing")
    return list(dict.fromkeys(errors))


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


def git_commit(repo: Path, ref: str) -> str | None:
    result = subprocess.run(["git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"], cwd=repo, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def release_policy_errors(project: Project, release: Release, releases: list[Release]) -> list[str]:
    errors = []
    version = version_key(release.version)
    modern = release.modern
    if release.kind not in {"release", "hotfix", "bugfix"}:
        errors.append("Kind must be release, hotfix or bugfix")
    if modern:
        if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", release.version):
            errors.append("new versions must be vX.Y.Z")
        if release.kind == "release" and version[2] != 0:
            errors.append("normal release requires Z = 0")
        if release.kind == "release":
            predecessors = [r for r in releases if r.component == release.component and r.status == "released"
                            and r.path != release.path and version_key(r.version) < version]
            if predecessors:
                previous = max(version_key(r.version) for r in predecessors)
                if version[:2] <= previous[:2] or (version[0] > previous[0] and version[1] != 0):
                    errors.append("normal release must increase X or Y and reset subordinate numbers")
        if release.status == "released" and (not release.commit or release.tag != release.version):
            errors.append("published release requires Commit and matching Tag")
    if release.kind in {"hotfix", "bugfix"}:
        if not version[2] or release.specs or release.amendments:
            errors.append("hotfix/bugfix requires Z > 0 and ships only fixes")
        repo = project.components[release.component].repo
        base = release.base_tag
        if not re.fullmatch(r"v\d+\.\d+\.\d+", base) or version_key(base)[:2] != version[:2] or version_key(base) >= version:
            errors.append("correction needs an earlier Base tag in the same X.Y line")
        elif not git_commit(repo, "refs/tags/" + base):
            errors.append("Base tag does not exist in configured repo")
        else:
            tags = subprocess.run(["git", "tag", "--list"], cwd=repo, capture_output=True, text=True)
            same = [tag for tag in tags.stdout.splitlines() if re.fullmatch(r"v\d+\.\d+\.\d+", tag)
                    and version_key(tag)[:2] == version[:2] and tag != release.tag]
            if release.status == "planning" and same and (version_key(base) != max(map(version_key, same)) or version <= max(map(version_key, same))):
                errors.append("Base tag must be the latest published tag of the line")
    return errors


def _load_releases(project: Project, specs: list[Spec], overrides: dict[Path, str] | None = None) -> tuple[list[Release], dict[str, dict[str, str]], list[str]]:
    errors = []
    by_name = {spec.name: spec for spec in specs}
    membership = {spec.name: {} for spec in specs}
    releases = []
    overrides = overrides or {}
    for component in project.components:
        folder = project.releases / component
        if not folder.is_dir():
            errors.append(f"roadmap/releases/{component} is missing")
        paths = set(folder.glob("v*.md")) | {p for p in overrides if p.parent == folder}
        versions = set()
        for path in sorted(paths):
            where = str(path.relative_to(project.root))
            if not VERSION_RE.fullmatch(path.stem):
                errors.append(f"{where}: invalid version name")
                continue
            key = version_key(path.stem)
            if key in versions:
                errors.append(f"{where}: ambiguous normalized version")
            versions.add(key)
            body = visible_markdown(overrides[path] if path in overrides else path.read_text(encoding="utf-8"))
            heading = re.search(rf"^# {re.escape(component)} {re.escape(path.stem)} — (.+)$", body, re.M)
            if not heading:
                errors.append(f"{where}: invalid release heading")
                continue
            status, started, released = (_release_field(body, x) for x in ("Status", "Started", "Released"))
            local = []
            if status not in {"planning", "released"}:
                local.append("Status must be planning or released")
            if not _valid_date(started) or (status == "released" and not _valid_date(released)):
                local.append("invalid release date")
            if status == "planning" and released not in {"—", "-"}:
                local.append("planning release cannot have a Released date")
            if not re.search(r"^## Specs[ \t]*$", body, re.M):
                local.append("missing Specs section")
            names = []
            amendments = []
            for label, collection in (("Specs", names), ("Amendments", amendments)):
                for line in section(body, label).splitlines():
                    if not line.startswith("- "):
                        continue
                    pattern = r"^- \[[^]]+\]\(\.\./\.\./\.\./specs/([^/]+)/spec\.md\)$" if label == "Specs" else r"^- \[(\d{3,}) (A[1-9]\d*) — [^]]+\]\(\.\./\.\./\.\./specs/([^/]+)/spec\.md\)$"
                    match = re.fullmatch(pattern, line)
                    if not match:
                        local.append(f"{label} needs valid links")
                        continue
                    if label == "Specs":
                        name = match[1]
                        target = name
                    else:
                        sid, aid, name = match.groups()
                        target = name + "-" + aid
                    spec = by_name.get(name)
                    if not spec:
                        local.append(f"unknown spec {name}")
                        continue
                    scope = spec.components
                    if label == "Amendments":
                        amendment = spec.amendments.get(aid)
                        if sid != spec.id or not amendment:
                            local.append(f"unknown amendment {target}")
                            continue
                        scope = amendment.components
                        if status == "released" and amendment.open_tasks(component):
                            local.append(f"released amendment {target} has open [{component}] tasks")
                    if component not in scope:
                        local.append(f"{target} does not target {component}")
                    if spec.status == "deferred" or (status == "released" and spec.status != "done"):
                        local.append(f"released spec {name} is not done or is deferred")
                    if target in collection:
                        local.append(f"duplicate spec link or amendment {target}")
                    collection.append(target)
                    previous = membership.setdefault(target, {}).get(component)
                    if previous:
                        local.append(f"{target}: assigned to {component} {previous} and {path.stem}")
                    membership[target][component] = path.stem
            fixes = [line for line in section(body, "Fixes").splitlines() if line.startswith("- ")]
            for line in fixes:
                match = re.fullmatch(r"- (?:\[(\d{3,})\]\(\.\./\.\./\.\./specs/([^/]+)/spec\.md\)|No spec) — (.+)", line)
                if not match:
                    local.append("invalid fix line")
                    continue
                sid, name, description = match.groups()
                if name:
                    spec = by_name.get(name)
                    if not spec or spec.id != sid or spec.status != "done" or component not in spec.components:
                        local.append("fix requires a done spec targeting this component")
                if status == "released" and not re.search(r"`[0-9a-f]{7,40}`|https://[^\s)]+/pull/\d+", description):
                    local.append("released fix needs a commit or PR reference")
            if not (names or amendments or fixes):
                local.append("version needs at least one spec, amendment or fix")
            release = Release(path, component, path.stem, heading[1], status, started, released, names, amendments, fixes,
                              _release_field(body, "Kind") or "release", _release_field(body, "Base tag"),
                              _release_field(body, "Commit"), _release_field(body, "Tag"), bool(_release_field(body, "Kind")))
            releases.append(release)
            if status == "released":
                local.extend(release_criteria_errors(body))
                if not section(body, "Release Notes").strip():
                    local.append("write Release Notes before closing")
            errors.extend(f"{where}: {error}" for error in local)
    for release in releases:
        errors.extend(f"{release.path.relative_to(project.root)}: {e}" for e in release_policy_errors(project, release, releases))
    for spec in specs:
        if spec.status in {"in-progress", "done"}:
            for component in spec.components:
                if component not in membership[spec.name]:
                    errors.append(f"{spec.name}: missing {component} release assignment")
        for aid, amendment in spec.amendments.items():
            assigned = membership.get(spec.name + "-" + aid, {})
            for component in amendment.components:
                version = assigned.get(component)
                original = membership[spec.name].get(component)
                if version and original and version_key(version) <= version_key(original):
                    errors.append(f"{spec.name}-{aid}: must ship after original {component} release")
                if not version and any(mark != " " for mark, _, _ in amendment.tasks):
                    errors.append(f"{spec.name}-{aid}: missing {component} release assignment after work started")
    return releases, membership, errors


def scan(project: Project, overrides: dict[Path, str] | None = None) -> State:
    specs = load_specs(project)
    errors = [f"{spec.name}: {error}" for spec in specs for error in _check_spec(project, spec)]
    ids: dict[str, str] = {}
    for spec in specs:
        if spec.id in ids:
            errors.append(f"{spec.name}: id {spec.id} also used by {ids[spec.id]}")
        ids[spec.id] = spec.name
    releases, membership, release_errors = _load_releases(project, specs, overrides)
    errors.extend(release_errors)
    errors.extend(_check_future(project, specs))
    return State(specs, releases, membership, errors)


def version_key(version: str) -> tuple[int, ...]:
    parts = tuple(int(part) for part in version[1:].split("."))
    return parts + (0,) * (3 - len(parts))


def render_index(component: str, releases: list[Release]) -> str:
    rows = sorted((r for r in releases if r.component == component), key=lambda r: version_key(r.version))
    released = [r.version for r in rows if r.status == "released"]
    lines = [f"# {component} releases", "", "> Generated by `roclec check --write`. Edit version files instead.", "", "## Current release", "", released[-1] if released else "—", "", "| Version | Title | Kind | Specs / Amendments / Fixes | Status | Released |", "| ------- | ----- | ---- | ------------------------- | ------ | -------- |"]
    lines += [f"| [{r.version}]({r.version}.md) | {r.title} | {r.kind} | {len(r.specs)} / {len(r.amendments)} / {len(r.fixes)} | {r.status} | {r.released} |" for r in rows]
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
    lines += ["## Amendments", "", "| Amendment | Components | Releases |", "| --------- | ---------- | -------- |"]
    for spec in state.specs:
        for aid, amendment in spec.amendments.items():
            versions = ", ".join(f"{c} {v}" for c, v in sorted(state.membership.get(spec.name + "-" + aid, {}).items())) or "—"
            pending = ", ".join(c for c in amendment.components if amendment.open_tasks(c)) or "complete"
            lines.append(f"| [{spec.id}-{aid} — {amendment.title}](../specs/{spec.name}/spec.md) | {pending} | {versions} |")
    return "\n".join(lines) + "\n"


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


def check_coverage(project: Project, state: State, targets: set[str] | None = None, only_component: str | None = None) -> list[str]:
    corpus: dict[str, str] = {}
    for component, settings in project.components.items():
        if only_component and component != only_component:
            continue
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
        if targets is not None and spec.name not in targets and not any(spec.name + "-" + aid in targets for aid in spec.amendments):
            continue
        if spec.status != "done":
            continue
        for component in spec.components:
            if only_component and component != only_component:
                continue
            if component not in corpus:
                errors.append(f"{spec.name}: no configured repo for coverage in {component}")
                continue
            amendment_acs = {ac for a in spec.amendments.values() for ac in a.acs}
            required = set(AC_RE.findall(spec.body)) - amendment_acs if targets is None or spec.name in targets else set()
            for aid, amendment in spec.amendments.items():
                if component in amendment.components and not amendment.open_tasks(component) and (targets is None or spec.name + "-" + aid in targets):
                    required.update(amendment.acs)
            for ac in sorted(required):
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
