"""Generate optional spec-kit aliases from Roclec's canonical skills and templates."""

from importlib.resources import files
import json
from pathlib import Path
import re
import subprocess
import tempfile

from . import __version__
from .config import Project


class AdapterError(ValueError):
    pass


CORE_STAGES = ("specify", "clarify", "plan", "tasks", "analyze", "implement", "converge", "constitution", "checklist")
EXTRA_STAGES = ("idea", "foundation", "ux", "prototype", "release", "coordinator", "amend", "reviewer")
SUPPORTED_SPECIFY = ">=0.13.4,<0.14.0"


def generate_adapter(project: Project, destination: Path) -> tuple[Path, Path]:
    assets = files("roclec_spec_kit").joinpath("assets")
    if isinstance(project, Project):
        assets = assets.joinpath("legacy")
    preset = destination / "preset"
    extension = destination / "extension"
    provides = []
    commands = []
    for folder, stages, core in ((preset, CORE_STAGES, True), (extension, EXTRA_STAGES, False)):
        (folder / "commands").mkdir(parents=True)
        for stage in stages:
            source = assets.joinpath(f"skills/roclec-{stage}/SKILL.md").read_text(encoding="utf-8")
            body = source.split("\n---\n", 1)[1].lstrip()
            refs = assets.joinpath(f"skills/roclec-{stage}/references")
            if refs.is_dir():
                target_refs = folder / "commands" / "references" / f"roclec-{stage}"
                target_refs.mkdir(parents=True)
                for reference in refs.iterdir():
                    (target_refs / reference.name).write_text(reference.read_text(encoding="utf-8"), encoding="utf-8")
                body = body.replace("](references/", "](" + str(project.root / ".agents/skills" / f"roclec-{stage}" / "references") + "/")
            name = f"speckit.{stage}" if core else f"speckit.roclec.{stage}"
            relative = f"commands/{name}.md"
            text = ('---\ndescription: Roclec ' + stage + ' (generated alias)\n---\n\n'
                    'User input: $ARGUMENTS\n\n' + body)
            (folder / relative).write_text(text, encoding="utf-8")
            item = {"name": name, "file": relative, "description": f"Roclec {stage}: same native workflow"}
            if core:
                provides.append({"type": "command", **item, "replaces": name})
            else:
                commands.append(item)
    (preset / "templates").mkdir()
    for source in sorted((project.root / ".roclec/templates").glob("*-template.md")):
        (preset / "templates" / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        provides.append({"type": "template", "name": source.stem, "file": f"templates/{source.name}",
                         "description": "Project-owned Roclec template", "replaces": source.stem})
    for folder in (preset, extension):
        (folder / "LICENSE.spec-kit").write_text(assets.joinpath("notices/spec-kit-LICENSE.txt").read_text(encoding="utf-8"), encoding="utf-8")
    common = {"id": "roclec", "version": __version__, "author": "Roclec", "license": "UNLICENSED"}
    (preset / "preset.yml").write_text(json.dumps({"schema_version": "1.0", "preset": {
        **common, "name": "Roclec native workflow", "description": "Aliases generated from native skills and project templates"},
        "requires": {"speckit_version": SUPPORTED_SPECIFY}, "provides": {"templates": provides}}, indent=2), encoding="utf-8")
    (extension / "extension.yml").write_text(json.dumps({"schema_version": "1.0", "extension": {
        **common, "name": "Roclec lifecycle aliases", "description": "Native stages exposed in spec-kit", "category": "process", "effect": "read-write"},
        "requires": {"speckit_version": SUPPORTED_SPECIFY}, "provides": {"commands": commands}}, indent=2), encoding="utf-8")
    return preset, extension


def install_speckit(project: Project) -> None:
    version = subprocess.run(["specify", "version"], capture_output=True, text=True, check=False)
    match = re.search(r"CLI Version\s+(\d+)\.(\d+)\.(\d+)", version.stdout)
    if version.returncode or not match or not ((0, 13, 4) <= tuple(map(int, match.groups())) < (0, 14, 0)):
        raise AdapterError(f"optional adapter requires specify-cli {SUPPORTED_SPECIFY}; tested with 0.13.4")
    with tempfile.TemporaryDirectory(prefix="roclec-adapter-") as temp:
        preset, extension = generate_adapter(project, Path(temp))
        operations = []
        if (project.root / ".specify/presets/roclec").exists():
            operations.append(["specify", "preset", "remove", "roclec"])
        operations.extend((["specify", "preset", "add", "--dev", str(preset)],
                           ["specify", "extension", "add", "--dev", str(extension), "--force"]))
        for command in operations:
            result = subprocess.run(command, cwd=project.root, capture_output=True, text=True, check=False)
            if result.returncode:
                raise AdapterError(f"{' '.join(command[:3])} failed: {result.stdout}\n{result.stderr}")
    context = project.root / ".roclec/feature.json"
    if isinstance(project, Project) and context.exists():
        from .lifecycle import resolve_spec, select_spec
        from .workflow import scan
        select_spec(project, resolve_spec(project, scan(project), None))
