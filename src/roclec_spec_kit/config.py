"""Project-local configuration for a Roclec installation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib

NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
CONFIG_PATH = Path(".roclec/project.toml")
LINK_PATH = Path(".roclec/link.toml")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Component:
    name: str
    repo: Path
    user_facing: bool = False
    product: dict[str, str] | None = None


@dataclass(frozen=True)
class Project:
    root: Path
    name: str
    components: dict[str, Component]

    @property
    def specs(self) -> Path:
        return self.root / "specs"

    @property
    def releases(self) -> Path:
        return self.root / "roadmap/releases"


def find_config(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_PATH
        if candidate.is_file():
            return candidate
        link = directory / LINK_PATH
        if link.is_file():
            try:
                data = tomllib.loads(link.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                raise ConfigError(f"Cannot read {link}: {exc}") from exc
            target = data.get("project_root")
            if data.get("schema") != 1 or not isinstance(target, str) or not target or Path(target).is_absolute():
                raise ConfigError(f"Invalid {link}")
            linked_config = (directory / target / CONFIG_PATH).resolve()
            if not linked_config.is_file():
                raise ConfigError(f"Broken Roclec link: {linked_config}")
            return linked_config
    raise ConfigError(f"No {CONFIG_PATH} found from {start}")


def load_project(start: Path) -> Project:
    config_path = find_config(start)
    root = config_path.parent.parent
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Cannot read {config_path}: {exc}") from exc
    if data.get("schema") != 1:
        raise ConfigError("project.toml needs schema = 1")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("project.toml needs a nonempty name")
    raw_components = data.get("components")
    if not isinstance(raw_components, dict) or not raw_components:
        raise ConfigError("project.toml needs at least one [components.<name>] table")
    components: dict[str, Component] = {}
    for key, value in raw_components.items():
        if not NAME_RE.fullmatch(key) or not isinstance(value, dict):
            raise ConfigError(f"Invalid component name or table: {key}")
        repo = value.get("repo")
        if not isinstance(repo, str) or not repo or Path(repo).is_absolute():
            raise ConfigError(f"{key}.repo must be a relative path")
        user_facing = value.get("user_facing", False)
        if not isinstance(user_facing, bool):
            raise ConfigError(f"{key}.user_facing must be true or false")
        product = value.get("product")
        if product is not None:
            if not user_facing or not isinstance(product, dict) or set(product) - {"core", "source", "output", "design"}:
                raise ConfigError(f"{key}.product needs a user-facing component and supported paths")
            defaults = {"core": "product/core.md", "source": f"product/{key}.md", "output": f"components/{key}/PRODUCT.md", "design": f"components/{key}/DESIGN.md"}
            product = {**defaults, **product}
            for label, relative in product.items():
                if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or not (root / relative).resolve().is_relative_to(root):
                    raise ConfigError(f"{key}.product.{label} must stay within project root")
            if len({(root / p).resolve() for p in product.values()}) != 4:
                raise ConfigError(f"{key}.product sources and outputs must be distinct")
        components[key] = Component(key, (root / repo).resolve(), user_facing, product)
    outputs = [(root / c.product["output"]).resolve() for c in components.values() if c.product]
    inputs = {(root / c.product[k]).resolve() for c in components.values() if c.product for k in ("core", "source", "design")}
    if len(outputs) != len(set(outputs)) or inputs.intersection(outputs):
        raise ConfigError("product outputs must be unique and cannot overwrite sources/design")
    return Project(root, name, components)


def render_config(name: str, components: dict[str, tuple[str, bool]]) -> str:
    lines = ["# Roclec project profile. Paths are relative to this project root.", "schema = 1", f"name = {json.dumps(name)}", ""]
    for component, (repo, user_facing) in components.items():
        lines += [f"[components.{component}]", f"repo = {json.dumps(repo)}", f"user_facing = {str(user_facing).lower()}", ""]
    return "\n".join(lines)


# The public CLI uses this profile. The schema-1 functions above remain available
# only to characterize the pre-redesign implementation during C1/C2 development.
@dataclass(frozen=True)
class Profile:
    root: Path
    data: dict

    @property
    def components(self):
        return self.data["components"]

    def repo(self, component: str) -> Path:
        from .model import need
        need(component in self.components, "INVALID_REFERENCE", "Unknown component", entity=component)
        return (self.root / self.components[component]["repo"]).resolve()


def validate_profile(root: Path, data: dict) -> Profile:
    from .model import fields, need, text
    fields(data, ("schema", "name", "components"))
    need(type(data["schema"]) is int and data["schema"] == 2, "UNSUPPORTED_SCHEMA",
         "The native CLI requires project.toml schema = 2; schema 1 is not migrated or modified",
         exit_code=2, expected=2, actual=data["schema"],
         remediation="Use the previous wheel for a schema-1 project; initialize schema 2 in a separate project.")
    need(text(data["name"]) and isinstance(data["components"], dict) and bool(data["components"]),
         "INVALID_INPUT", "A project needs a name and configured components", exit_code=2)
    for name, entry in data["components"].items():
        need(NAME_RE.fullmatch(name) is not None, "INVALID_INPUT", "Invalid component name", exit_code=2)
        fields(entry, ("repo", "user_facing", "inputs", "generated", "verification"), ("excluded",))
        relative = entry["repo"]
        need(text(relative) and not Path(relative).is_absolute() and "\\" not in relative,
             "INVALID_PATH", "Component repo must be a relative configured path", exit_code=2)
        repo = (root / relative).resolve()
        need(repo == root.resolve() or repo.is_dir(), "INVALID_REFERENCE", "Configured code repo is missing", path=relative)
        need(type(entry["user_facing"]) is bool, "INVALID_INPUT", "user_facing must be boolean", exit_code=2)
        for key in ("inputs", "generated", "excluded"):
            patterns = entry.get(key, [])
            need(isinstance(patterns, list) and all(text(p) and not p.startswith("/") and
                 ".." not in Path(p).parts and "\\" not in p for p in patterns),
                 "INVALID_PATH", f"{key} must be relative path patterns", exit_code=2)
            need(len(patterns) == len(set(patterns)), "INVALID_INPUT", "Duplicate path pattern", exit_code=2)
        need(bool(entry["inputs"]) and not set(entry["inputs"]) & set(entry["generated"]),
             "INVALID_INPUT", "Declare nonempty inputs distinct from generated paths", exit_code=2)
        checks = entry["verification"]
        need(isinstance(checks, list), "INVALID_INPUT", "verification must be a list", exit_code=2)
        check_ids = []
        for check in checks:
            fields(check, ("id", "argv", "cwd", "timeout_seconds"), ("acceptance_ids",))
            from .model import identifier, strings
            for ac in strings(check.get("acceptance_ids", [])):
                identifier(ac, "AC")
            need(text(check["id"]) and isinstance(check["argv"], list) and bool(check["argv"])
                 and all(text(arg) and "\x00" not in arg for arg in check["argv"]), "INVALID_INPUT", "Checks need id and argv", exit_code=2)
            cwd = check["cwd"]
            need(text(cwd) and not Path(cwd).is_absolute() and ".." not in Path(cwd).parts and "\\" not in cwd
                 and (repo / cwd).resolve().is_relative_to(repo), "INVALID_PATH", "Check cwd must stay in repo", exit_code=2)
            need(type(check["timeout_seconds"]) is int and check["timeout_seconds"] > 0,
                 "INVALID_INPUT", "Check timeout must be a positive integer", exit_code=2)
            check_ids.append(check["id"])
        need(len(check_ids) == len(set(check_ids)), "ID_COLLISION", "Duplicate verification check ID")
    return Profile(root.resolve(), data)


def load_profile(start: Path) -> Profile:
    from .model import ModelError, local_path
    config_path = find_config(start)
    root = config_path.parent.parent.resolve()
    local_path(root, ".roclec/project.toml")
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise ModelError("INVALID_INPUT", f"Invalid project profile: {exc}", exit_code=2, path=config_path) from exc
    return validate_profile(root, data)
